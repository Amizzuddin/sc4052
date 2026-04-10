################################################################################
#  Filename:      project/ai_handler.py                                        #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Monday, April 6th 2026, 7:25:01 am                           #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday April 10th 2026 10:52:59 am                           #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

################################################################################
#  Filename:      project/ai_handler.py                                        #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Monday, April 6th 2026, 7:25:01 am                           #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday April 10th 2026 6:14:19 am                            #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

################################################################################
#  Filename:      project/ai_handler.py                                        #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 10:04:55 am                        #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday April 10th 2026 6:14:14 am                            #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
ai_handler.py
-------------
AI-driven CI/CD self-healing for cicd-gen.

Responsibilities:
  - GitHub REST API helpers (polling Actions runs, downloading logs)
  - LLM prompt builder for CI fix suggestions
  - Background watch-and-heal loop (_watch_ci_and_heal)
  - Shared in-memory state for watch progress (consumed by dashboard callbacks)
"""

import io
import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

# Valid JSON escape characters after a backslash
_VALID_JSON_ESCAPES = frozenset('"\\bfnrtu/')


def _repair_llm_json(text: str) -> dict:
    """Parse *text* as JSON, repairing common LLM output problems.

    Handles:
    1. Invalid backslash escapes (``\\e``, ``\\033`` from ANSI codes)
    2. Truncated output (LLM hit max_tokens mid-string)
    3. Unescaped control characters
    4. Structural issues (missing closing braces/quotes)

    Falls back to regex extraction of ``ci_yaml`` and ``dockerfile`` keys
    when ``json.loads`` cannot recover the structure.
    """
    # ── Attempt 1: direct parse ──────────────────────────────────────────
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass

    # ── Attempt 2: repair invalid backslash escapes ──────────────────────
    def _fix_escape(m: re.Match) -> str:
        ch = m.group(1)
        if ch in _VALID_JSON_ESCAPES:
            return m.group(0)
        return "\\\\" + ch

    repaired = re.sub(r"\\(.)", _fix_escape, text)
    try:
        return json.loads(repaired, strict=False)
    except json.JSONDecodeError:
        pass

    # ── Attempt 3: regex extraction (handles truncation / structural breakage) ─
    result: dict = {}
    for key in ("ci_yaml", "dockerfile"):
        # Match  "key": "..." — the value may be truncated (no closing quote).
        # First try a properly closed string, then fall back to unclosed.
        pat_closed = rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"'
        pat_unclosed = rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)'
        m = re.search(pat_closed, repaired, re.DOTALL)
        if not m:
            m = re.search(pat_unclosed, repaired, re.DOTALL)
        if m:
            val = m.group(1)
            # Unescape JSON string escapes
            try:
                val = json.loads(f'"{val}"')
            except Exception:
                val = val.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
            result[key] = val

    # source_files is a nested object — skip regex extraction for it
    # (auto-formatters handle most source issues anyway)

    if result:
        return result
    raise json.JSONDecodeError("Could not extract any keys from LLM response", text, 0)


import git
from git_handler import _ensure_trailing_newline, _run_precommit_local, _run_precommit_on_files
from writer import write_config

# ── CI watch state (shared with dashboard callbacks) ─────────────────────────
# { watch_id: {"messages": [...], "steps": [...], "status": ..., "done": bool,
#              "attempt": int, "progress": 0-100} }
_ci_watch_results: dict[str, dict] = {}
_ci_watch_lock = threading.Lock()
# Cancel events keyed by watch_id — set() to request graceful shutdown
_ci_cancel_flags: dict[str, threading.Event] = {}


def snapshot_run_ids(owner: str, repo_name: str, branch_name: str, token: str) -> set[int]:
    """Return the set of Actions run IDs currently on *branch_name*.

    Call this **before** pushing a commit so the CI watcher can distinguish
    pre-existing runs from the newly triggered one — even if the new run
    completes (or fails) almost instantly.
    """
    result = _github_api(
        f"/repos/{owner}/{repo_name}/actions/runs" f"?branch={urllib.parse.quote(branch_name)}&per_page=20",
        token,
    )
    return {r["id"] for r in (result or {}).get("workflow_runs", [])}


# ── GitHub URL parsing ────────────────────────────────────────────────────────


def _parse_github_repo(repo_url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub HTTPS or SSH URL, or None."""
    # HTTPS: https://github.com/owner/repo[.git]
    m = re.match(r"https?://(?:[^@]+@)?github\.com/([^/]+)/([^/\s]+?)(?:\.git)?$", repo_url.strip())
    if m:
        return m.group(1), m.group(2)
    # SSH: git@github.com:owner/repo[.git]
    m = re.match(r"git@github\.com:([^/]+)/([^\s]+?)(?:\.git)?$", repo_url.strip())
    if m:
        return m.group(1), m.group(2)
    return None


def validate_github_pat(token: str) -> dict:
    """Validate a GitHub PAT by calling GET /user.

    Returns ``{"valid": True, "user": "<login>"}`` on success or
    ``{"valid": False, "error": "<message>"}`` on failure.
    """
    url = "https://api.github.com/user"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cicd-gen/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            data = json.loads(resp.read().decode())
            return {"valid": True, "user": data.get("login", "unknown")}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"valid": False, "error": "Invalid or expired token (HTTP 401)"}
        if e.code == 403:
            return {"valid": False, "error": "Token lacks required permissions (HTTP 403)"}
        return {"valid": False, "error": f"GitHub API error (HTTP {e.code})"}
    except Exception as e:
        return {"valid": False, "error": f"Connection error: {e}"}


# ── GitHub REST API helpers ───────────────────────────────────────────────────


def _github_api(path: str, token: str, method: str = "GET", body: bytes | None = None) -> dict | list | None:
    """Make a GitHub REST API call; return parsed JSON or None on error."""
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cicd-gen/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[cicd-gen] GitHub API {method} {path} → HTTP {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[cicd-gen] GitHub API error: {e}", file=sys.stderr)
        return None


def _github_api_raw(path: str, token: str) -> bytes | None:
    """Fetch raw bytes from a GitHub API endpoint (used for log zip download).

    GitHub's /actions/runs/{run_id}/logs returns a 302 redirect to a
    time-limited presigned S3 URL.  If we forward the Authorization header to
    S3 it rejects the request (duplicate auth), so we must follow the redirect
    manually without headers.
    """
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cicd-gen/1.0",
        },
    )

    # Build an opener that does NOT follow redirects so we can handle them
    # manually (strip auth before hitting the presigned S3 URL).
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # type: ignore[override]
            return None

    no_redirect_opener = urllib.request.build_opener(_NoRedirect)
    try:
        with no_redirect_opener.open(req, timeout=30) as resp:
            return resp.read()  # direct 200, no redirect needed
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            location = e.headers.get("Location", "")
            if location:
                # Fetch the presigned URL without any auth header
                plain_req = urllib.request.Request(location, headers={"User-Agent": "cicd-gen/1.0"})
                try:
                    with urllib.request.urlopen(plain_req, timeout=60) as r:  # nosec B310
                        return r.read()
                except Exception as e2:
                    print(f"[cicd-gen] log presigned fetch error: {e2}", file=sys.stderr)
                    return None
            print(f"[cicd-gen] GitHub raw fetch error: HTTP {e.code} (no Location header)", file=sys.stderr)
            return None
        print(f"[cicd-gen] GitHub raw fetch error: HTTP Error {e.code}: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[cicd-gen] GitHub raw fetch error: {e}", file=sys.stderr)
        return None


def check_repo_secrets(
    owner: str,
    repo: str,
    token: str,
    names: list[str],
) -> dict:
    """Check which of *names* exist as Actions secrets in the repository.

    Uses ``GET /repos/{owner}/{repo}/actions/secrets`` which returns secret
    names only — values are never exposed by the GitHub API.  Requires a
    token with at least ``repo`` scope (or ``secrets:read`` fine-grained).

    Returns a dict::

        {
            "found"    : list[str]   # secret names that exist
            "missing"  : list[str]   # secret names that are absent
            "error"    : str | None  # human-readable error, or None
            "can_check": bool        # False when prerequisites are missing
        }
    """
    if not token or not owner or not repo:
        return {"found": [], "missing": list(names), "error": None, "can_check": False}

    # Paginate through all secrets (GitHub returns up to 100 per page)
    found_names: set[str] = set()
    page = 1
    while True:
        data = _github_api(
            f"/repos/{owner}/{repo}/actions/secrets?per_page=100&page={page}",
            token,
        )
        if data is None:
            return {
                "found": [],
                "missing": list(names),
                "error": (
                    "Could not read secrets — ensure your token has 'repo' scope " "and that the repository exists."
                ),
                "can_check": True,
            }
        secrets_page = data.get("secrets", []) if isinstance(data, dict) else []
        for s in secrets_page:
            found_names.add(s.get("name", ""))
        if len(secrets_page) < 100:
            break
        page += 1

    found = [n for n in names if n in found_names]
    missing = [n for n in names if n not in found_names]
    return {"found": found, "missing": missing, "error": None, "can_check": True}


def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True if the exception is an LLM rate-limit / quota error."""
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg or "quota" in msg


def _extract_rate_limit_wait(exc: Exception) -> tuple[int, str]:
    """Parse wait-time and retry clock time from a rate-limit error.

    Returns ``(seconds, retry_at_str)`` where *retry_at_str* is a
    human-readable clock time like ``"10:45:30"`` extracted from the
    error message, or computed from *seconds* if not present.
    """
    msg = str(exc)
    # Try to extract "until HH:MM:SS"
    m_time = re.search(r"until\s+(\d{1,2}:\d{2}:\d{2})", msg)
    # Try to extract "~Ns"
    m_secs = re.search(r"~(\d+)s", msg)
    wait = int(m_secs.group(1)) if m_secs else 60
    if m_time:
        retry_at = m_time.group(1)
    else:
        import datetime

        retry_at = (datetime.datetime.now() + datetime.timedelta(seconds=wait)).strftime("%H:%M:%S")
    return wait, retry_at


def _extract_log_text(zip_bytes: bytes, max_chars: int = 8_000) -> str:
    """Extract the most relevant lines from a GitHub Actions log zip.

    Strategy: collect the *last* 120 lines of every log file first (these
    contain the real failure output), then append lines mentioning actionable
    error keywords.  Docker-build noise (package install logs) is filtered
    out so the LLM sees the actual failure reason.
    """
    tail_lines: list[str] = []
    error_lines: list[str] = []
    # Docker build output lines that mention "error" in package names but aren't real errors
    _NOISE = re.compile(r"#\d+\s+\d+\.\d+\s+(Selecting|Preparing|Unpacking|Setting up|Get:\d+)", re.I)
    # pip freeze / package-list lines (e.g. "requests==2.31.0") — not useful for debugging
    _PKG_LIST = re.compile(r"^\S+==\S+$")
    # Git remote transfer progress lines — pure noise
    _GIT_REMOTE = re.compile(r"remote:\s*(Counting|Compressing|Enumerating|Resolving|Receiving|Total)\s+\w+", re.I)
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in sorted(zf.namelist()):
                if not name.endswith(".txt"):
                    continue
                try:
                    text = zf.read(name).decode("utf-8", errors="replace")
                except Exception:
                    continue
                all_lines = text.splitlines()
                # Last 120 lines — most likely to contain the actual failure
                for ln in all_lines[-120:]:
                    # Strip timestamp prefix for the noise check
                    stripped = re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*", "", ln).strip()
                    if _PKG_LIST.match(stripped) or _NOISE.search(ln) or _GIT_REMOTE.search(stripped):
                        continue
                    if ln not in tail_lines:
                        tail_lines.append(ln)
                # Lines matching real error keywords (skip Docker build noise)
                for ln in all_lines:
                    stripped = re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*", "", ln).strip()
                    if _NOISE.search(ln) or _GIT_REMOTE.search(stripped):
                        continue
                    if re.search(r"error|fail|denied|cannot|not found|exit code", ln, re.I):
                        if ln not in error_lines and ln not in tail_lines:
                            error_lines.append(ln)
    except Exception as e:
        return f"(Could not parse log zip: {e})"
    # Put tail first (most important), then supplemental error lines
    combined = tail_lines + error_lines
    joined = "\n".join(combined)
    return joined[-max_chars:] if len(joined) > max_chars else joined


def _sanitize_expressions(yaml_content: str, platform: str) -> str:
    """Normalize CI expression syntax that the LLM sometimes garbles.

    GitHub Actions:  ${ {expr} }  →  ${{ expr }}
    The LLM occasionally inserts spaces between the dollar-brace delimiters
    (e.g. ``${ {github.sha} }``), which causes a bash "bad substitution" error
    at runtime.  A single regex pass corrects every occurrence.
    """
    if platform != "github-actions":
        return yaml_content
    # Match: $  followed by optional-space  {  optional-space  {  ... content ...  }  optional-space  }
    # and replace with: ${{ content }}
    import re as _re

    fixed = _re.sub(
        r"\$\{\s*\{\s*(.*?)\s*\}\s*\}",
        lambda m: "${{ " + _strip_expr_quotes(m.group(1).strip()) + " }}",
        yaml_content,
    )
    return fixed


def _strip_expr_quotes(expr: str) -> str:
    """Remove surrounding quotes the LLM sometimes adds inside ${{ }} expressions."""
    if len(expr) >= 2 and expr[0] in ('"', "'") and expr[-1] == expr[0]:
        return expr[1:-1]
    return expr


# Deprecated GitHub-hosted runner images that will leave a job permanently queued.
_DEPRECATED_RUNNERS = re.compile(
    r"\bubuntu-(?:16\.04|18\.04|20\.04)\b" r"|\bmacos-(?:10\.15|11|12)\b" r"|\bwindows-2016\b"
)


def _sanitize_runner(yaml_content: str, platform: str) -> str:
    """Replace deprecated GitHub-hosted runner labels with ubuntu-latest.

    ubuntu-20.04 (and older) are retired – jobs that request them are permanently
    queued and never picked up.  This function rewrites any ``runs-on:`` value
    that matches a known-deprecated label to ``ubuntu-latest``.
    """
    if platform != "github-actions":
        return yaml_content
    return _DEPRECATED_RUNNERS.sub("ubuntu-latest", yaml_content)


# ── LLM prompt builder ───────────────────────────────────────────────────────


def _build_ci_fix_prompt(
    error_log: str,
    yaml_content: str,
    dockerfile_content: str | None,
    platform: str,
) -> str:
    """Build a prompt asking the LLM to fix failing CI/CD files."""
    df_section = f"\n\nDOCKERFILE (current):\n```dockerfile\n{dockerfile_content}\n```" if dockerfile_content else ""
    return f"""You are a senior DevOps engineer. A CI/CD pipeline just failed on {platform}.
Analyse the error log and return FIXED file contents.

CI/CD YAML (current):
```yaml
{yaml_content}
```{df_section}

FAILURE LOG (last ~8000 chars):
```
{error_log}
```

Return ONLY a JSON object with these keys (omit a key if that file does not need changing):
{{
  "ci_yaml": "<complete fixed YAML content>",
  "dockerfile": "<complete fixed Dockerfile content>",
  "source_files": {{
    "<relative/path/to/file>": "<complete fixed file content>",
    ...
  }}
}}
Notes on "source_files":
- Only include files that the error log proves need a CODE-LEVEL fix that
  automatic formatters (black, isort, end-of-file-fixer) cannot handle
  (e.g. unused imports reported by flake8, type errors, missing modules).
- Formatters will run automatically — do NOT fix whitespace / trailing-newline /
  import-order issues; those are handled.
- Each value must be the COMPLETE file content (not a diff).
- Omit "source_files" entirely if no source changes are needed.

CRITICAL RULES for the fixed YAML:
- GitHub Actions expressions MUST use exactly two braces with NO spaces: ${{{{ github.sha }}}}
  NEVER write ${{ {{github.sha}} }} or ${{ github.sha }} or ${{ "{{" }}github.sha{{ "}}" }}
- NEVER use `secrets.*` in a step-level or job-level `if:` expression — GitHub Actions raises
  "Unrecognized named-value: 'secrets'" for this usage. Instead, map secrets to `env:` vars
  and test them with shell guards like `if [ -z "$VAR" ]; then ... fi` inside `run:`.
- NEVER use `docker build` or `docker push` directly when a compose file is present.
  When a docker-compose.yml exists, use `sed` to update the image name, then `docker compose push`:
    REPO_NAME="${{{{github.event.repository.name}}}}"
    sed -i "s|image:.*|image: $DOCKER_USERNAME/$REPO_NAME:latest|" docker-compose.yml docker-compose.yaml 2>/dev/null || true
    docker compose build
    docker compose push
  For non-compose builds, build and push as: $DOCKER_USERNAME/$REPO_NAME:${{{{github.sha}}}}
- Every step MUST have either `run:` or `uses:` — never a name-only step.
- Runner label MUST be `ubuntu-latest` (or `ubuntu-22.04`/`ubuntu-24.04`).
  NEVER use `ubuntu-20.04`, `ubuntu-18.04`, or any other deprecated image — they are
  retired by GitHub and will leave jobs permanently queued.
- The file MUST end with a single newline character.
- Shell one-liners like `if [ -f file ]; then cmd; fi` already contain the closing `fi`.
  Do NOT add an extra `fi` on a separate line after such one-liners — it causes
  `syntax error near unexpected token 'fi'`.

No explanation. No markdown wrapping. Just the JSON object."""


# ── CI watch / self-heal loop ─────────────────────────────────────────────────


def _watch_ci_and_heal(
    watch_id: str,
    owner: str,
    repo_name: str,
    branch_name: str,
    token: str,
    clone_path: str,
    platform: str,
    scan: dict,
    provider: str,
    api_key: str,
    max_retries: int = 10,
    cancel_event: "threading.Event | None" = None,
    pre_push_run_ids: "set[int] | None" = None,
) -> None:
    """
    Background thread: poll GitHub Actions, auto-fix failures, push fixes,
    and retry indefinitely until CI passes or cancel_event is set.
    """
    from generator import _call_llm, _fix_shell_if_fi, _strip_markdown_fences  # local import
    from template_store import save_template  # cache known-good templates

    _cancel = cancel_event or threading.Event()

    def _log(msg: str) -> None:
        with _ci_watch_lock:
            _ci_watch_results[watch_id]["messages"].append(msg)

    def _set_step(index: int, status: str, label: str | None = None) -> None:
        with _ci_watch_lock:
            steps = _ci_watch_results[watch_id].get("steps", [])
            if 0 <= index < len(steps):
                steps[index]["status"] = status
                if label:
                    steps[index]["label"] = label

    def _add_step(label: str, status: str = "pending") -> int:
        """Append a step and return its index."""
        with _ci_watch_lock:
            steps = _ci_watch_results[watch_id].setdefault("steps", [])
            steps.append({"label": label, "status": status})
            return len(steps) - 1

    def _finish(status: str) -> None:
        with _ci_watch_lock:
            _ci_watch_results[watch_id]["status"] = status
            _ci_watch_results[watch_id]["done"] = True

    def _cancelled() -> bool:
        return _cancel.is_set()

    # Use the pre-push snapshot of run IDs provided by the caller (taken
    # BEFORE the commit was pushed) so that even an instantly-failing run
    # is recognised as "new".  Fall back to a live snapshot only when the
    # caller did not supply one (backwards compat / manual invocations).
    if pre_push_run_ids is not None:
        seen_run_ids: set = set(pre_push_run_ids)
        _log(f"Using pre-push run snapshot ({len(seen_run_ids)} IDs)")
    else:
        seen_run_ids = set()
        _log("Snapshotting existing runs on branch before watching...")
        _snapshot = _github_api(
            f"/repos/{owner}/{repo_name}/actions/runs" f"?branch={urllib.parse.quote(branch_name)}&per_page=20",
            token,
        )
        for _r in (_snapshot or {}).get("workflow_runs", []):
            seen_run_ids.add(_r["id"])
    if seen_run_ids:
        _log(f"  Pre-existing run IDs skipped: {sorted(seen_run_ids)}")

    attempt = 0
    while True:
        attempt += 1
        if _cancelled():
            _finish("cancelled")
            return
        with _ci_watch_lock:
            _ci_watch_results[watch_id]["attempt"] = attempt

        if attempt == 1:
            wait_run_idx = 0
            run_progress_idx = 1
            _set_step(0, "running")
        else:
            wait_run_idx = _add_step(f"Attempt {attempt}: waiting for new Actions run", "running")
            run_progress_idx = _add_step(f"Attempt {attempt}: CI run in progress", "pending")

        # Wait for an Actions run to appear on this branch
        run_id = None
        for _ in range(25):
            if _cancelled():
                _finish("cancelled")
                return
            result = _github_api(
                f"/repos/{owner}/{repo_name}/actions/runs" f"?branch={urllib.parse.quote(branch_name)}&per_page=5",
                token,
            )
            runs = (result or {}).get("workflow_runs", [])
            # Require the run to be strictly newer than every run we have
            # already processed.  GitHub returns run IDs in descending order
            # (higher ID = newer), so filtering by id > max(seen) prevents
            # a stale / already-completed older run from being picked up on
            # a retry after a fix commit is pushed.
            min_new_id = max(seen_run_ids) if seen_run_ids else 0
            new_runs = [r for r in runs if r["id"] not in seen_run_ids and r["id"] > min_new_id]
            if new_runs:
                run_id = new_runs[0]["id"]
                seen_run_ids.add(run_id)
                _log(f"Found run #{run_id}  status={new_runs[0].get('status', '')}")
                break
            _log("Waiting for GitHub Actions run to appear...")
            _cancel.wait(12)

        if not run_id:
            _set_step(wait_run_idx, "failed", "No Actions run found — attempting fix")
            _log("⚠ No Actions run found for this branch. The workflow YAML may be invalid.")
            _log("  Fetching current YAML and asking LLM to fix it...")

            # ── Self-heal: the workflow file itself may be broken ────────────
            current_yaml = ""
            current_dockerfile = None
            try:
                for pat in ("ci.yml", "*.yml"):
                    yp = next(Path(clone_path).rglob(pat), None)
                    if yp:
                        current_yaml = yp.read_text()
                        break
                df_p = Path(clone_path) / "Dockerfile"
                if df_p.exists():
                    current_dockerfile = df_p.read_text()
            except Exception:
                pass

            if not current_yaml:
                _log("⚠ Could not locate a workflow YAML to fix.")
                _cancel.wait(15)
                continue

            error_log = (
                "GitHub Actions did NOT create a workflow run at all. "
                "This usually means the YAML file has a syntax error that "
                "prevents GitHub from parsing it (e.g. invalid expression "
                "like 'secrets.X != ...' outside of a valid context, or a "
                "malformed 'on:' trigger). Fix the YAML so GitHub can parse it."
            )

            llm_idx = _add_step(f"Fix attempt {attempt}: fixing invalid YAML", "running")
            _log(f"🤖 Asking {provider} for a fix (no-run scenario)...")
            if _cancelled():
                _finish("cancelled")
                return

            fix_prompt = _build_ci_fix_prompt(error_log, current_yaml, current_dockerfile, platform)
            try:
                nr_raw = _call_llm(fix_prompt, provider=provider, api_key=api_key, max_tokens=4096)
                nr_raw = _strip_markdown_fences(nr_raw)
                nr_fix = _repair_llm_json(nr_raw)
            except Exception as e:
                _set_step(llm_idx, "failed")
                if _is_rate_limit_error(e):
                    wait, retry_at = _extract_rate_limit_wait(e)
                    _log(f"\u23f3 Rate limit hit \u2014 retrying at {retry_at} (waiting {wait}s)...")
                    _set_step(llm_idx, "pending")
                    _cancel.wait(wait)
                    if _cancelled():
                        _finish("cancelled")
                        return
                    continue
                _log(f"⚠ Could not parse LLM fix: {e}. Retrying next attempt...")
                _cancel.wait(15)
                continue

            _set_step(llm_idx, "passed")

            # ── dedup: skip if LLM returned the same YAML and no source fixes ──
            _has_source_fixes = bool(nr_fix.get("source_files"))
            if nr_fix.get("ci_yaml") and not _has_source_fixes:
                _nr_candidate = _sanitize_expressions(nr_fix["ci_yaml"], platform)
                _nr_candidate = _sanitize_runner(_nr_candidate, platform)
                _nr_candidate = _fix_shell_if_fi(_nr_candidate)
                if _nr_candidate.strip() == current_yaml.strip():
                    _log("⚠ LLM returned identical YAML — skipping this attempt.")
                    _cancel.wait(10)
                    continue

            push_idx = _add_step(f"Fix attempt {attempt}: pushing commit", "running")
            repo_obj = git.Repo(clone_path)
            repo_obj.config_writer().set_value("user", "name", "cicd-gen").release()
            repo_obj.config_writer().set_value("user", "email", "cicd-gen@auto.fix").release()
            nr_changed: list = []
            try:
                if nr_fix.get("ci_yaml"):
                    raw_yaml = _sanitize_expressions(nr_fix["ci_yaml"], platform)
                    raw_yaml = _sanitize_runner(raw_yaml, platform)
                    raw_yaml = _fix_shell_if_fi(raw_yaml)
                    yo = write_config(raw_yaml, clone_path, platform)
                    nr_changed.append(str(yo.relative_to(clone_path)))
                if nr_fix.get("dockerfile"):
                    df_p = Path(clone_path) / "Dockerfile"
                    df_p.write_text(nr_fix["dockerfile"])
                    nr_changed.append("Dockerfile")
                for sf_path, sf_content in (nr_fix.get("source_files") or {}).items():
                    sf_full = Path(clone_path) / sf_path
                    sf_full.parent.mkdir(parents=True, exist_ok=True)
                    sf_full.write_text(sf_content)
                    nr_changed.append(sf_path)
            except Exception as e:
                _set_step(push_idx, "failed")
                _log(f"⚠ Could not write fix files: {e}. Retrying...")
                _cancel.wait(15)
                continue

            # Run pre-commit on ALL repo files, not just changed CI files.
            # CI often fails because source files need formatting (black,
            # end-of-file-fixer, isort).  Running --all-files auto-fixes them
            # so `git add .` picks up everything.
            _run_precommit_local(clone_path)

            # Check for ANY changes (LLM files + pre-commit auto-fixes)
            repo_obj.git.add(".")
            if not repo_obj.is_dirty(index=True, working_tree=True) and not repo_obj.git.diff("--cached"):
                _set_step(push_idx, "skipped")
                _log("⚠ No effective changes after pre-commit. Retrying...")
                _cancel.wait(15)
                continue
            _run_precommit_local(clone_path)

            if _cancelled():
                _finish("cancelled")
                return

            try:
                origin = repo_obj.remote("origin")
                origin.set_url(f"https://{token}@github.com/{owner}/{repo_name}.git")
                _backups = Path(clone_path) / ".cicd-gen-backups"
                if _backups.exists():
                    import shutil as _shutil

                    _shutil.rmtree(_backups, ignore_errors=True)
                repo_obj.git.add(".")
                repo_obj.git.commit("-m", f"ci(fix): auto-fix attempt {attempt} (no-run) via cicd-gen", "--allow-empty")
                # Rebase onto remote so the push is fast-forward
                try:
                    repo_obj.git.fetch("origin", branch_name)
                    repo_obj.git.rebase(f"origin/{branch_name}")
                except Exception:
                    try:
                        repo_obj.git.rebase("--abort")
                    except Exception:
                        pass
                origin.push(refspec=f"{branch_name}:{branch_name}", force=True)
                _set_step(push_idx, "passed")
                _log(f"🚀 Fix pushed ({', '.join(nr_changed)}). Waiting for new run...")
            except Exception as e:
                _set_step(push_idx, "failed")
                _log(f"⚠ Push failed: {e}. Retrying...")

            _cancel.wait(15)
            continue

        _set_step(wait_run_idx, "passed")
        _set_step(run_progress_idx, "running")

        # Poll until the run completes
        timeout_ticks = 90
        conclusion = ""
        for tick in range(timeout_ticks):
            if _cancelled():
                _finish("cancelled")
                return
            run_data = _github_api(f"/repos/{owner}/{repo_name}/actions/runs/{run_id}", token) or {}
            run_status = run_data.get("status", "")
            conclusion = run_data.get("conclusion", "")
            elapsed = tick * 12
            _log(f"Run #{run_id}  status={run_status}  conclusion={conclusion}  elapsed={elapsed}s")
            if run_status == "completed":
                break
            _cancel.wait(12)
        else:
            _set_step(run_progress_idx, "failed", "Timed out")
            _finish("error")
            _log("⚠ Timed out waiting for CI run to complete.")
            return

        if conclusion == "success":
            _set_step(run_progress_idx, "passed")
            _finish("passed")
            _log(f"✅ CI passed on attempt {attempt}!")
            # Cache the working YAML as a template for this language
            try:
                raw_lang = scan.get("languages") or scan.get("language")
                langs = raw_lang if isinstance(raw_lang, list) else ([raw_lang] if raw_lang else [])
                working_yaml = ""
                for pat in ("ci.yml", "*.yml"):
                    yp = next(Path(clone_path).rglob(pat), None)
                    if yp:
                        working_yaml = yp.read_text()
                        break
                if working_yaml:
                    save_template(
                        langs,
                        platform,
                        ci_yaml=working_yaml,
                    )
                    _log("📋 Template updated with working CI config.")
            except Exception:
                pass  # template caching is best-effort
            return

        _set_step(run_progress_idx, "failed")

        # ── Identify which job step(s) failed ────────────────────────────────
        jobs_data = _github_api(f"/repos/{owner}/{repo_name}/actions/runs/{run_id}/jobs", token) or {}
        failed_steps: list[str] = []
        for _job in jobs_data.get("jobs", []):
            for _step in _job.get("steps", []):
                if _step.get("conclusion") in ("failure", "timed_out"):
                    failed_steps.append(f"{_job['name']} → {_step['name']}")
        if failed_steps:
            with _ci_watch_lock:
                _ci_watch_results[watch_id]["last_failure"] = failed_steps
            for _lbl in failed_steps:
                _log(f"❌ Failed step: {_lbl}")
        else:
            _log(f"❌ CI failed (attempt {attempt}) — no individual step identified.")

        # Fetch logs & ask LLM (no limit — user cancels when done)
        llm_idx = _add_step(f"Fix attempt {attempt}: fetching logs & asking LLM", "running")
        _log(f"Fetching full logs for attempt {attempt}...")

        log_bytes = _github_api_raw(f"/repos/{owner}/{repo_name}/actions/runs/{run_id}/logs", token)
        error_log = _extract_log_text(log_bytes) if log_bytes else "(log unavailable)"
        _log(f"Log snippet:\n{error_log[:500]}...")

        current_yaml, current_dockerfile = "", None
        try:
            for pat in ("ci.yml", "*.yml"):
                yp = next(Path(clone_path).rglob(pat), None)
                if yp:
                    current_yaml = yp.read_text()
                    break
            df_p = Path(clone_path) / "Dockerfile"
            if df_p.exists():
                current_dockerfile = df_p.read_text()
        except Exception:
            pass

        _log(f"🤖 Asking {provider} for a fix...")
        if _cancelled():
            _finish("cancelled")
            return
        fix_prompt = _build_ci_fix_prompt(error_log, current_yaml, current_dockerfile, platform)
        try:
            raw_fix = _call_llm(fix_prompt, provider=provider, api_key=api_key, max_tokens=4096)
            raw_fix = _strip_markdown_fences(raw_fix)
            fix_data: dict = _repair_llm_json(raw_fix)
        except Exception as e:
            _set_step(llm_idx, "failed")
            if _is_rate_limit_error(e):
                wait, retry_at = _extract_rate_limit_wait(e)
                _log(f"\u23f3 Rate limit hit — retrying at {retry_at} (waiting {wait}s)...")
                _set_step(llm_idx, "pending")
                _cancel.wait(wait)
                if _cancelled():
                    _finish("cancelled")
                    return
                continue
            _log(f"\u26a0 Could not parse LLM fix: {e}. Retrying next attempt...")
            _cancel.wait(15)
            continue

        # Apply fixes & push
        _set_step(llm_idx, "passed")

        # ── dedup: skip if LLM returned the same YAML and no source fixes ──
        _has_source_fixes = bool(fix_data.get("source_files"))
        if fix_data.get("ci_yaml") and not _has_source_fixes:
            _candidate = _sanitize_expressions(fix_data["ci_yaml"], platform)
            _candidate = _sanitize_runner(_candidate, platform)
            _candidate = _fix_shell_if_fi(_candidate)
            if _candidate.strip() == current_yaml.strip():
                _log("⚠ LLM returned identical YAML — skipping this attempt.")
                _cancel.wait(10)
                continue

        push_idx = _add_step(f"Fix attempt {attempt}: pushing commit", "running")
        repo_obj = git.Repo(clone_path)
        repo_obj.config_writer().set_value("user", "name", "cicd-gen").release()
        repo_obj.config_writer().set_value("user", "email", "cicd-gen@auto.fix").release()
        files_changed: list = []
        try:
            if fix_data.get("ci_yaml"):
                raw_yaml = _sanitize_expressions(fix_data["ci_yaml"], platform)
                raw_yaml = _sanitize_runner(raw_yaml, platform)
                raw_yaml = _fix_shell_if_fi(raw_yaml)
                yo = write_config(raw_yaml, clone_path, platform)
                files_changed.append(str(yo.relative_to(clone_path)))
            if fix_data.get("dockerfile"):
                df_p = Path(clone_path) / "Dockerfile"
                df_p.write_text(fix_data["dockerfile"])
                files_changed.append("Dockerfile")
            for sf_path, sf_content in (fix_data.get("source_files") or {}).items():
                sf_full = Path(clone_path) / sf_path
                sf_full.parent.mkdir(parents=True, exist_ok=True)
                sf_full.write_text(sf_content)
                files_changed.append(sf_path)
        except Exception as e:
            _set_step(push_idx, "failed")
            _log(f"⚠ Could not write fix files: {e}.")
            _finish("error")
            return

        # Run pre-commit on ALL repo files, not just the changed CI files.
        # CI pre-commit runs --all-files, so source-code formatting issues
        # (black, end-of-file-fixer, isort) must also be fixed here.
        # The 2-pass _run_precommit_local auto-fixes and then verifies;
        # `git add .` below will pick up every modified file.
        _run_precommit_local(clone_path)

        # Check for ANY changes (LLM files + pre-commit auto-fixes)
        repo_obj.git.add(".")
        if not repo_obj.is_dirty(index=True, working_tree=True) and not repo_obj.git.diff("--cached"):
            _set_step(push_idx, "skipped")
            _log("⚠ No effective changes after pre-commit. Stopping.")
            _finish("error")
            return

        if _cancelled():
            _finish("cancelled")
            return

        try:
            # Commit first while the index is clean except for our changes,
            # then rebase onto remote so the push is fast-forward.
            origin = repo_obj.remote("origin")
            origin.set_url(f"https://{token}@github.com/{owner}/{repo_name}.git")
            # Remove leftover backup dir so it is never committed
            _backups = Path(clone_path) / ".cicd-gen-backups"
            if _backups.exists():
                import shutil as _shutil

                _shutil.rmtree(_backups, ignore_errors=True)
            repo_obj.git.add(".")
            repo_obj.git.commit("-m", f"ci(fix): auto-fix attempt {attempt} via cicd-gen", "--allow-empty")
            # Rebase onto remote so the push is fast-forward
            try:
                repo_obj.git.fetch("origin", branch_name)
                repo_obj.git.rebase(f"origin/{branch_name}")
            except Exception:
                try:
                    repo_obj.git.rebase("--abort")
                except Exception:
                    pass
            origin.push(refspec=f"{branch_name}:{branch_name}", force=True)
            _set_step(push_idx, "passed")
            _log(f"🚀 Fix pushed ({', '.join(files_changed)}). Waiting for new run...")
        except Exception as e:
            _set_step(push_idx, "failed")
            _log(f"⚠ Push failed: {e}")
            _finish("error")
            return

        _cancel.wait(15)
