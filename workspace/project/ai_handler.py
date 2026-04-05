################################################################################
#  Filename:      project/ai_handler.py                                        #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 10:04:55 am                        #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Sunday April 5th 2026 9:10:53 am                             #
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

import git
from git_handler import _ensure_trailing_newline, _run_precommit_on_files
from writer import write_config

# ── CI watch state (shared with dashboard callbacks) ─────────────────────────
# { watch_id: {"messages": [...], "steps": [...], "status": ..., "done": bool,
#              "attempt": int, "progress": 0-100} }
_ci_watch_results: dict[str, dict] = {}
_ci_watch_lock = threading.Lock()
# Cancel events keyed by watch_id — set() to request graceful shutdown
_ci_cancel_flags: dict[str, threading.Event] = {}


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


def _extract_log_text(zip_bytes: bytes, max_chars: int = 8_000) -> str:
    """Extract the most relevant lines from a GitHub Actions log zip."""
    lines_out: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Sort jobs so we get consistent ordering
            for name in sorted(zf.namelist()):
                if not name.endswith(".txt"):
                    continue
                try:
                    text = zf.read(name).decode("utf-8", errors="replace")
                except Exception:
                    continue
                # Keep lines mentioning errors, failures, or the last 60 lines
                error_lines = [ln for ln in text.splitlines() if re.search(r"error|fail|cannot|not found", ln, re.I)]
                tail_lines = text.splitlines()[-60:]
                for ln in error_lines + tail_lines:
                    if ln not in lines_out:
                        lines_out.append(ln)
    except Exception as e:
        return f"(Could not parse log zip: {e})"
    joined = "\n".join(lines_out)
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
  "dockerfile": "<complete fixed Dockerfile content>"
}}

CRITICAL RULES for the fixed YAML:
- GitHub Actions expressions MUST use exactly two braces with NO spaces: ${{{{ github.sha }}}}
  NEVER write ${{ {{github.sha}} }} or ${{ github.sha }} or ${{ "{{" }}github.sha{{ "}}" }}
- Every step MUST have either `run:` or `uses:` — never a name-only step.
- Runner label MUST be `ubuntu-latest` (or `ubuntu-22.04`/`ubuntu-24.04`).
  NEVER use `ubuntu-20.04`, `ubuntu-18.04`, or any other deprecated image — they are
  retired by GitHub and will leave jobs permanently queued.
- The file MUST end with a single newline character.

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
    max_retries: int = 5,
    cancel_event: "threading.Event | None" = None,
) -> None:
    """
    Background thread: poll GitHub Actions, auto-fix failures, push fixes,
    repeat up to max_retries times.  Respects cancel_event for clean shutdown.
    """
    from generator import _call_llm, _strip_markdown_fences  # local import

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

    def _set_progress(pct: int) -> None:
        with _ci_watch_lock:
            _ci_watch_results[watch_id]["progress"] = max(0, min(100, pct))

    def _finish(status: str, progress: int = 100) -> None:
        with _ci_watch_lock:
            _ci_watch_results[watch_id]["status"] = status
            _ci_watch_results[watch_id]["done"] = True
            _ci_watch_results[watch_id]["progress"] = progress

    def _cancelled() -> bool:
        return _cancel.is_set()

    # Pre-populate seen_run_ids with EVERY run that already exists on the
    # branch right now, before the first commit is pushed.  This prevents
    # the watcher from picking up a stale completed run (e.g. from a prior
    # session) as if it were the freshly-triggered pipeline.
    seen_run_ids: set = set()
    _log("Snapshotting existing runs on branch before watching...")
    _snapshot = _github_api(
        f"/repos/{owner}/{repo_name}/actions/runs" f"?branch={urllib.parse.quote(branch_name)}&per_page=20",
        token,
    )
    for _r in (_snapshot or {}).get("workflow_runs", []):
        seen_run_ids.add(_r["id"])
    if seen_run_ids:
        _log(f"  Pre-existing run IDs skipped: {sorted(seen_run_ids)}")

    for attempt in range(1, max_retries + 2):
        with _ci_watch_lock:
            _ci_watch_results[watch_id]["attempt"] = attempt

        if attempt == 1:
            wait_run_idx = 0
            run_progress_idx = 1
            _set_step(0, "running")
        else:
            wait_run_idx = _add_step(f"Attempt {attempt}: waiting for new Actions run", "running")
            run_progress_idx = _add_step(f"Attempt {attempt}: CI run in progress", "pending")

        _set_progress(5 + (attempt - 1) * 30)

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
            _set_step(wait_run_idx, "failed", "No Actions run found")
            _finish("error")
            _log("⚠ No Actions run found for this branch.")
            return

        _set_step(wait_run_idx, "passed")
        _set_step(run_progress_idx, "running")
        _set_progress(15 + (attempt - 1) * 30)

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
            _set_progress(int(15 + (tick / timeout_ticks) * 40) + (attempt - 1) * 30)
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
            _finish("passed", progress=100)
            _log(f"✅ CI passed on attempt {attempt}!")
            return

        _set_step(run_progress_idx, "failed")

        if attempt > max_retries:
            _finish("gave_up")
            _log(f"❌ CI still failing after {max_retries} fix attempt(s). Giving up.")
            return

        # Fetch logs & ask LLM
        _set_progress(60 + (attempt - 1) * 30)
        llm_idx = _add_step(f"Fix attempt {attempt}: fetching logs & asking LLM", "running")
        _log(f"❌ CI failed (attempt {attempt}). Fetching logs...")

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
        fix_prompt = _build_ci_fix_prompt(error_log, current_yaml, current_dockerfile, platform)
        try:
            raw_fix = _call_llm(fix_prompt, provider=provider, api_key=api_key, max_tokens=3000)
            raw_fix = _strip_markdown_fences(raw_fix)
            fix_data: dict = json.loads(raw_fix)
        except Exception as e:
            _set_step(llm_idx, "failed")
            _log(f"⚠ Could not parse LLM fix: {e}. Stopping.")
            _finish("gave_up")
            return

        # Apply fixes & push
        _set_step(llm_idx, "passed")
        push_idx = _add_step(f"Fix attempt {attempt}: pushing commit", "running")
        repo_obj = git.Repo(clone_path)
        files_changed: list = []
        try:
            if fix_data.get("ci_yaml"):
                raw_yaml = _sanitize_expressions(fix_data["ci_yaml"], platform)
                raw_yaml = _sanitize_runner(raw_yaml, platform)
                yo = write_config(raw_yaml, clone_path, platform)
                files_changed.append(str(yo.relative_to(clone_path)))
            if fix_data.get("dockerfile"):
                df_p = Path(clone_path) / "Dockerfile"
                df_p.write_text(fix_data["dockerfile"])
                files_changed.append("Dockerfile")
        except Exception as e:
            _set_step(push_idx, "failed")
            _log(f"⚠ Could not write fix files: {e}.")
            _finish("gave_up")
            return

        if not files_changed:
            _set_step(push_idx, "skipped")
            _log("⚠ LLM returned no file changes. Stopping.")
            _finish("gave_up")
            return

        # Ensure every fixed file has a trailing newline, then run a focused
        # pre-commit pass on changed files before committing.  This prevents
        # the end-of-file-fixer hook from failing on CI for the same reason
        # it failed on the original commit.
        for rel_path in files_changed:
            try:
                _ensure_trailing_newline(Path(clone_path) / rel_path)
            except Exception:
                pass
        _run_precommit_on_files(clone_path, files_changed)

        try:
            # Rebase onto the remote before committing so the push is always
            # fast-forward (avoids "failed to push some refs" if the remote
            # branch moved since our last push).
            origin = repo_obj.remote("origin")
            origin.set_url(f"https://{token}@github.com/{owner}/{repo_name}.git")
            try:
                repo_obj.git.fetch("origin", branch_name)
                repo_obj.git.rebase(f"origin/{branch_name}")
            except Exception:
                pass  # ignore if branch doesn't exist on remote yet
            repo_obj.git.add(".")
            repo_obj.index.commit(f"ci(fix): auto-fix attempt {attempt} via cicd-gen")
            origin.push(refspec=f"{branch_name}:{branch_name}")
            _set_step(push_idx, "passed")
            _log(f"🚀 Fix pushed ({', '.join(files_changed)}). Waiting for new run...")
        except Exception as e:
            _set_step(push_idx, "failed")
            _log(f"⚠ Push failed: {e}")
            _finish("error")
            return

        _cancel.wait(15)

    _finish("gave_up")
