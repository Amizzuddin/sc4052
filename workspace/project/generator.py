################################################################################
#  Filename:      project/generator.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Wednesday, February 25th 2026, 6:44:09 am                    #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Thursday April 9th 2026 1:52:44 pm                           #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
generator.py
------------
Builds structured prompts from scan results and calls an LLM to
generate (or refine) a CI/CD pipeline YAML configuration.

Supported providers
-------------------
  gemini    Google Gemini Flash  — free tier (1 500 req/day)
              https://aistudio.google.com/app/apikey
  groq      Groq  (Llama 3.3)   — free tier (14 400 req/day)
              https://console.groq.com
  anthropic Anthropic Claude     — paid plan required
              https://console.anthropic.com
"""

import os
import re
import time
from typing import Optional

# Provider packages are imported lazily inside each call function so that
# missing optional packages only raise at call time, not at import time.

# ── Supported LLM providers ─────────────────────────────────────────────────────

SUPPORTED_PROVIDERS = ["gemini", "groq", "anthropic"]

PROVIDER_DEFAULTS = {
    "gemini": {"model": "gemini-2.0-flash", "max_tokens": 2048},
    "groq": {"model": "llama-3.3-70b-versatile", "max_tokens": 2048},
    "anthropic": {"model": "claude-opus-4-6", "max_tokens": 2048},
}

# ── Supported CI/CD platforms ─────────────────────────────────────────────────

SUPPORTED_PLATFORMS = ["github-actions", "gitlab-ci", "jenkins"]

# ── Test-runner install configuration ────────────────────────────────────────
# Keyed by the exact string returned by scanner.detect_tests() as test_runner.
# install_cmd : shell command to install the runner; None = toolchain built-in
# find_re     : regex that matches the runner command inside a run: block
# rewrite_re  : (old, new) pair for rewriting the invocation; None = no rewrite
# extra_env   : dict of extra env vars to inject on the step; None = none
TEST_RUNNER_INSTALL: dict[str, dict] = {
    "pytest": {
        "install_cmd": "pip install pytest --quiet",
        "find_re": r"\bpytest\b",
        "rewrite_re": (r"\bpytest\b", "python -m pytest"),
        "extra_env": {"PYTHONPATH": "."},
    },
    # Node: npm/yarn/pnpm install already handles jest/mocha etc. via package.json
    "npm test": {"install_cmd": None, "find_re": None, "rewrite_re": None, "extra_env": None},
    # Go, Rust, Java: runners are part of the language toolchain
    "go test ./...": {"install_cmd": None, "find_re": None, "rewrite_re": None, "extra_env": None},
    "cargo test": {"install_cmd": None, "find_re": None, "rewrite_re": None, "extra_env": None},
    "mvn test": {"install_cmd": None, "find_re": None, "rewrite_re": None, "extra_env": None},
    # Ruby: bundle install handles rspec, but gem install acts as a safety net
    "bundle exec rspec": {
        "install_cmd": "gem install rspec --no-document -q 2>/dev/null || true",
        "find_re": r"bundle\s+exec\s+rspec\b",
        "rewrite_re": None,
        "extra_env": None,
    },
}

PLATFORM_NOTES = {
    "github-actions": (
        "Generate a GitHub Actions workflow YAML. "
        "File should start with 'name:' and use 'on:' trigger syntax. "
        "Output path: .github/workflows/ci.yml"
    ),
    "gitlab-ci": (
        "Generate a GitLab CI/CD YAML (.gitlab-ci.yml). "
        "Use 'stages:' at the top level and define jobs under each stage."
    ),
    "jenkins": (
        "Generate a declarative Jenkins pipeline (Jenkinsfile). " "Use the 'pipeline { ... }' declarative syntax."
    ),
}

# ── Install / test command templates ──────────────────────────────────────────

LANGUAGE_DEFAULTS = {
    "python": {
        "install": {
            "pip": "pip install -r requirements.txt",
            "pipenv": "pipenv install --dev",
            "pip (pyproject)": "pip install .[dev]",
        },
        "test": "pytest --tb=short -q",
        "lint": "pre-commit run --all-files",
        "runtime": "python:3.12",
    },
    "node": {
        "install": {
            "npm": "if [ -f package-lock.json ]; then npm ci; else npm install; fi",
            "yarn": "yarn install --frozen-lockfile",
            "pnpm": "pnpm install --frozen-lockfile",
        },
        "test": "npm test",
        "lint": "pre-commit run --all-files",
        "runtime": "node:20",
    },
    "go": {
        "install": {"go modules": "go mod download"},
        "test": "go test ./... -v",
        "lint": "pre-commit run --all-files",
        "runtime": "go:1.22",
    },
    "java": {
        "install": {
            "maven": "mvn dependency:resolve",
            "gradle": "gradle dependencies",
        },
        "test": "mvn test",
        "lint": "pre-commit run --all-files",
        "runtime": "java:21",
    },
    "rust": {
        "install": {"cargo": "cargo fetch"},
        "test": "cargo test",
        "lint": "pre-commit run --all-files",
        "runtime": "rust:latest",
    },
    "ruby": {
        "install": {
            "bundler": 'gem install bundler --user-install --no-document -q && export PATH="$(ruby -e \'puts Gem.user_dir + "/bin"\'):$PATH" && bundle install'
        },
        "test": "bundle exec rspec",
        "lint": "pre-commit run --all-files",
        "runtime": "ruby:3.3",
    },
    "bash": {
        "install": {},
        "test": "bats tests/ 2>/dev/null || echo 'No BATS tests found'",
        "lint": "pre-commit run --all-files",
        "runtime": "ubuntu-latest",
    },
    "typescript": {
        "install": {
            "npm": "if [ -f package-lock.json ]; then npm ci; else npm install; fi",
            "yarn": "yarn install --frozen-lockfile",
            "pnpm": "pnpm install --frozen-lockfile",
        },
        "test": "npm test",
        "lint": "pre-commit run --all-files",
        "runtime": "node:20",
    },
    "kotlin": {
        "install": {
            "gradle": "gradle dependencies",
            "maven": "mvn dependency:resolve",
        },
        "test": "gradle test",
        "lint": "pre-commit run --all-files",
        "runtime": "java:21",
    },
}


def _build_context_summary(scan: dict) -> str:
    """Convert scan results into a human-readable summary for the prompt."""
    # Support both single language (str) and multi-language (list)
    raw_lang = scan.get("languages") or scan.get("language")
    if isinstance(raw_lang, list):
        lang_str = ", ".join(raw_lang) if raw_lang else "unknown"
    else:
        lang_str = raw_lang or "unknown"
    lines = [
        f"Repository name : {scan.get('repo_name', 'unknown')}",
        f"Language(s)     : {lang_str}",
        f"Frameworks      : {', '.join(scan.get('frameworks', [])) or 'none detected'}",
        f"Package manager : {scan.get('package_manager') or 'unknown'}",
        f"Deploy targets  : {', '.join(scan.get('deploy_targets', [])) or 'none detected'}",
    ]
    tests = scan.get("tests", {})
    lines.append(f"Has tests       : {tests.get('has_tests', False)}")
    if tests.get("test_runner"):
        lines.append(f"Test runner     : {tests['test_runner']}")
    existing = scan.get("existing_ci", [])
    if existing:
        lines.append(f"Existing CI/CD  : {', '.join(existing)}")
    return "\n".join(lines)


def _build_install_commands(scan: dict) -> list[str]:
    """Return install commands for all detected/selected languages."""
    raw_lang = scan.get("languages") or scan.get("language")
    langs = raw_lang if isinstance(raw_lang, list) else ([raw_lang] if raw_lang else [])
    pm = scan.get("package_manager")
    cmds = []
    for lang in langs:
        defaults = LANGUAGE_DEFAULTS.get(lang, {})
        install_map = defaults.get("install", {})
        if install_map:
            cmd = install_map.get(pm) or list(install_map.values())[0]
            cmds.append(f"({lang}) {cmd}")
    return cmds or ["echo 'no install step'"]


def _build_install_command(scan: dict) -> str:  # kept for compat
    """Single-line install command summary (backward compat)."""
    return "  &&  ".join(_build_install_commands(scan))


def build_generation_prompt(
    scan: dict, platform: str, extra_requirements: str = "", docker_push_enabled: bool = False
) -> str:
    """
    Build the full system + user prompt for initial config generation.

    Args:
        scan:                Output from scanner.scan_repo()
        platform:            One of SUPPORTED_PLATFORMS
        extra_requirements:  Any additional user requirements (free text)

    Returns:
        A string prompt to send to the LLM.
    """
    platform_note = PLATFORM_NOTES.get(platform, PLATFORM_NOTES["github-actions"])
    context = _build_context_summary(scan)
    install_cmds = _build_install_commands(scan)
    install_summary = "\n".join(f"    {c}" for c in install_cmds)

    # Use primary language for runtime/test/lint defaults
    raw_lang = scan.get("languages") or scan.get("language")
    langs = raw_lang if isinstance(raw_lang, list) else ([raw_lang] if raw_lang else [])
    lang = langs[0] if langs else "unknown"
    defaults = LANGUAGE_DEFAULTS.get(lang, {})
    test_cmd = scan.get("tests", {}).get("test_runner") or defaults.get("test", "echo 'no tests'")
    lint_cmd = defaults.get("lint") or "echo 'no lint'"
    runtime = defaults.get("runtime", "ubuntu-latest")
    has_docker = "docker" in scan.get("deploy_targets", [])
    has_compose = "docker-compose" in scan.get("deploy_targets", [])

    extra_section = f"\nAdditional requirements:\n{extra_requirements.strip()}" if extra_requirements.strip() else ""

    prompt = f"""You are a senior DevOps engineer and CI/CD expert. Generate a complete, production-ready CI/CD pipeline configuration.

REPOSITORY CONTEXT:
{context}

INFERRED COMMANDS:
- Install dependencies :
{install_summary}
- Run tests            : {test_cmd}
- Lint                 : {lint_cmd}
- Primary runtime      : {runtime}
- Docker build needed  : {has_docker}
- Docker Compose file  : {has_compose}
- Docker push enabled  : {docker_push_enabled}

PLATFORM INSTRUCTIONS:
{platform_note}
{extra_section}

RULES:
1. Output ONLY the raw YAML (or Jenkinsfile) — no markdown fences, no explanation.
2. Include these pipeline stages in order: install deps → lint → test → (Docker build & push if Docker build needed) → (optional deploy placeholder).
3. Use caching for dependencies where possible.
4. Pin runner/agent versions explicitly (do not use 'latest' for runner images in CI job definitions).
5. Add meaningful step names so the pipeline is easy to read.
6. If tests are not detected, add a placeholder test step with a comment.
7. Trigger on push to ALL branches and on all pull requests by default.
   For GitHub Actions use this exact 'on:' block (keep the comments so users know how to restrict):

     on:
       push:
         # Runs on every branch. To restrict, replace '**' with a list:
         # branches: [main, develop, 'release/**']
         branches: ["**"]
       pull_request:
         branches: ["**"]

   For GitLab CI omit 'only:' / 'except:' so all branches are covered; add a comment:
     # Remove the 'only' key below to restrict to specific branches, e.g.:
     # only: [main, develop]
   For Jenkins use 'when {{ branch pattern: "*" }}' and add a comment showing how to narrow it.
8. IMPORTANT — dependency file guards: each install step MUST be wrapped in a shell
   existence check so the pipeline does not fail if the file is absent.
   Use this pattern for every language:
   - Python   : if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
   - Node/npm : if [ -f package-lock.json ]; then npm ci; elif [ -f package.json ]; then npm install; fi
   - Ruby     : if [ -f Gemfile ]; then gem install bundler --user-install --no-document -q && export PATH="$(ruby -e 'puts Gem.user_dir + "/bin"'):$PATH" && bundle install; fi
   - PHP      : if [ -f composer.json ]; then composer install; fi
   - Go       : if [ -f go.mod ]; then go mod download; fi
   - Rust     : if [ -f Cargo.toml ]; then cargo fetch; fi
   - Java/mvn : if [ -f pom.xml ]; then mvn dependency:resolve; fi
   - Java/gradle: if [ -f build.gradle ]; then gradle dependencies; fi
9. IMPORTANT — linting: always use pre-commit for ALL linting and formatting checks.
   Do NOT install or call flake8, eslint, rubocop, go vet or any other linter directly.
   pre-commit manages its own isolated tool environments so nothing extra needs installing.
   - For GitHub Actions, use the dedicated action (handles caching automatically):
       - name: Lint (pre-commit)
         uses: pre-commit/action@v3.0.1
   - For GitLab CI / Jenkins, add TWO steps:
       - pip install pre-commit          # or: pip3 install pre-commit
       - pre-commit run --all-files
   Always run the lint step AFTER the install-dependencies step.
10. If the repository contains multiple languages, generate a job/stage for each language
   so they can be built and tested independently.
11. CRITICAL — Docker builds: when `Docker build needed: true`, a single multi-language
   Dockerfile is already committed to the repo root (it covers ALL selected languages in
   one image — do NOT create per-language images).
   When `Docker Compose file: true`, you MUST use docker compose commands.
   NEVER use `docker build` or `docker push` directly when a compose file is present.
   Use these EXACT patterns — deviation will break the pipeline:

   ── BUILD STEP (always runs) ──────────────────────────────────────────────
   IF Docker Compose file is true (guard for file existence):
   - GitHub Actions / GitLab CI / Jenkins:
       if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then docker compose build; fi

   IF Docker Compose file is false (plain Dockerfile only):
   - GitHub Actions : docker build -t ${{{{github.repository}}}}:${{{{github.sha}}}} .
   - GitLab CI      : docker build -t $CI_PROJECT_PATH:$CI_COMMIT_SHA .
   - Jenkins        : sh "docker build -t ${{env.JOB_NAME}}:${{env.GIT_COMMIT}} ."

   ── LOGIN + PUSH STEP ───────────────────────────────────────────────────
   Check `Docker push enabled`:
   - If `Docker push enabled: False` — OMIT the login and push steps entirely.
     Generate ONLY the build step above. Do NOT add docker login, docker push,
     or any image-upload step.
   - If `Docker push enabled: True` — add the login + push steps below.
     The push MUST be conditional on the DOCKER_TOKEN secret being present.
     NEVER echo, print, log, or expose the token value anywhere.

   For GitHub Actions (push enabled) — map secrets to env vars and use a
   shell-level guard (NEVER use `secrets.*` in a step `if:` — it causes
   "Unrecognized named-value" errors):

     - name: Docker login & push
       env:
         DOCKER_TOKEN: ${{{{ secrets.DOCKER_TOKEN }}}}
         DOCKER_USERNAME: ${{{{ secrets.DOCKER_USERNAME }}}}
       run: |
         if [ -z "$DOCKER_TOKEN" ]; then
           echo "DOCKER_TOKEN not set — skipping Docker push"
           exit 0
         fi
         REPO_NAME="${{{{github.event.repository.name}}}}"
         echo "$DOCKER_TOKEN" | docker login -u "$DOCKER_USERNAME" --password-stdin
         if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then
           # Update compose image to DOCKER_USERNAME/REPO_NAME and push
           sed -i "s|image:.*|image: $DOCKER_USERNAME/$REPO_NAME:latest|" docker-compose.yml docker-compose.yaml 2>/dev/null || true
           docker compose build
           docker compose push
         else
           docker build -t "$DOCKER_USERNAME/$REPO_NAME:${{{{github.sha}}}}" .
           docker push "$DOCKER_USERNAME/$REPO_NAME:${{{{github.sha}}}}"
         fi

   For GitLab CI (push enabled) — wrap login and push in a bash guard:
     script:
       - |
         if [ -n "$DOCKER_TOKEN" ]; then
           echo "$DOCKER_TOKEN" | docker login -u "$DOCKER_USERNAME" --password-stdin
           REPO_NAME=$(basename "$CI_PROJECT_PATH")
           if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then
             sed -i "s|image:.*|image: $DOCKER_USERNAME/$REPO_NAME:latest|" docker-compose.yml docker-compose.yaml 2>/dev/null || true
             docker compose build
             docker compose push
           else
             docker build -t "$DOCKER_USERNAME/$REPO_NAME:$CI_COMMIT_SHA" .
             docker push "$DOCKER_USERNAME/$REPO_NAME:$CI_COMMIT_SHA"
           fi
         else
           echo "DOCKER_TOKEN not set — skipping push"
         fi

   For Jenkins (push enabled) — use a bash guard (note: no curly braces around var names):
     sh '''
       if [ -n "${{DOCKER_TOKEN}}" ]; then
         echo "${{DOCKER_TOKEN}}" | docker login -u "${{DOCKER_USERNAME}}" --password-stdin
         REPO_NAME=$(basename "${{env.JOB_NAME}}")
         if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then
           sed -i "s|image:.*|image: ${{DOCKER_USERNAME}}/$REPO_NAME:latest|" docker-compose.yml docker-compose.yaml 2>/dev/null || true
           docker compose build
           docker compose push
         else
           docker build -t "${{DOCKER_USERNAME}}/$REPO_NAME:${{env.GIT_COMMIT}}" .
           docker push "${{DOCKER_USERNAME}}/$REPO_NAME:${{env.GIT_COMMIT}}"
         fi
       else
         echo "DOCKER_TOKEN not set — skipping push"
       fi
     '''

   Never reference per-language base images (python:3.12, node:20, ruby:3.3 etc.)
   in the CI Docker step — the Dockerfile already handles the multi-language setup.
16. CRITICAL — Test runner installation: when a test runner is detected the CI step MUST
   explicitly install it before running tests, even if it may be listed in a dependency
   file — the explicit install acts as a safety net for runners that are absent from
   requirements files and guarantees the binary is on the PATH.

   Use these exact patterns depending on the detected runner:

   Python / pytest:
     - name: Run tests
       run: |
         pip install pytest --quiet
         python -m pytest --tb=short -q
       env:
         PYTHONPATH: .
   (Use `python -m pytest` — NOT bare `pytest` — to keep the project root on sys.path.)

   Ruby / rspec:
     - name: Run tests
       run: |
         gem install rspec --no-document -q 2>/dev/null || true
         bundle exec rspec

   Node (npm test): no extra install step required; npm ci / npm install already
     sets up all test dependencies from package.json.

   Go (go test), Rust (cargo test), Java (mvn test): these runners are part of the
     language toolchain already present on the runner — no additional install needed.
12. CRITICAL — every workflow step MUST have either a `run:` or a `uses:` property.
   NEVER generate a step that contains only a `name:` (with or without comments).
   If a step is optional or a placeholder, still include a real `run:` with an
   `echo` command, e.g.:
     - name: Deploy (optional)
       run: echo "No deployment configured — add your deploy command here."
   Similarly, never comment out the `run:` key itself.
13. CRITICAL — GitHub Actions expression syntax: always use EXACTLY `${{{{ expr }}}}` (two
   opening braces, two closing braces, NO spaces between `$` and `{{`).  The pattern
   `${{ "{{" }}expr{{ "}}" }}` or `${{ {{expr}} }}` or `${{ {{ expr }} }}` are ALL WRONG.
   Correct examples:
     ${{{{github.repository}}}}     ${{{{github.sha}}}}     ${{{{secrets.DOCKER_TOKEN}}}}
   Wrong examples (never output these):
     ${{ {{github.repository}} }}   ${{ "{{" }}github.sha{{ "}}" }}   ${{ github.sha }}
14. CRITICAL — GitHub Actions runner labels: ALWAYS use `runs-on: ubuntu-latest`.
   NEVER use deprecated or unavailable images such as `ubuntu-20.04`, `ubuntu-18.04`,
   `ubuntu-16.04`, `macos-10.15`, or any pinned version that is not `ubuntu-latest`,
   `ubuntu-22.04`, or `ubuntu-24.04`.  Using `ubuntu-20.04` will leave the job
   permanently queued because GitHub has retired that image.
15. CRITICAL — secret safety: NEVER echo, print, log, or expose any secret value.
   The DOCKER_TOKEN / DOCKER_PASSWORD must only ever appear inside the `--password-stdin`
   pipe or a credentials-binding block. Forbidden patterns (never output these):
     echo "${{{{secrets.DOCKER_TOKEN}}}}"   # only acceptable inside | docker login --password-stdin
     run: echo "${{{{secrets.DOCKER_TOKEN}}}}"   # WRONG if not piped to docker login
   The login + push step MUST map secrets to env vars and use shell guards:
     env:
       DOCKER_TOKEN: ${{{{ secrets.DOCKER_TOKEN }}}}
       DOCKER_USERNAME: ${{{{ secrets.DOCKER_USERNAME }}}}
     run: |
       echo "$DOCKER_TOKEN" | docker login -u "$DOCKER_USERNAME" --password-stdin
16. CRITICAL — NEVER use `secrets.*` in a step-level or job-level `if:` expression.
   GitHub Actions raises "Unrecognized named-value: 'secrets'" for this usage.
   WRONG:  if: ${{{{ secrets.DOCKER_TOKEN != '' }}}}
   Instead, map secrets to env vars and test with `[ -z "$VAR" ]` in `run:`.
Generate the pipeline configuration now:"""

    return prompt


def build_refinement_prompt(current_yaml: str, user_request: str, platform: str) -> str:
    """
    Build a prompt to refine an existing pipeline config.

    Args:
        current_yaml:  The existing YAML string
        user_request:  The user's natural language change request
        platform:      The CI/CD platform

    Returns:
        A refinement prompt string
    """
    platform_note = PLATFORM_NOTES.get(platform, PLATFORM_NOTES["github-actions"])

    return f"""You are a senior DevOps engineer. You must update an existing CI/CD pipeline configuration based on a user's request.

CURRENT CONFIGURATION:
---
{current_yaml}
---

USER REQUEST:
{user_request}

PLATFORM:
{platform_note}

RULES:
1. Output ONLY the updated raw YAML — no markdown fences, no explanation.
2. Apply ONLY the changes the user requested; keep everything else intact.
3. Ensure the result is valid YAML and syntactically correct.
4. Preserve existing step names and structure unless the user explicitly asks to change them.

Return the complete updated configuration now:"""


# ── Claude API calls ──────────────────────────────────────────────────────────


def _parse_retry_delay(exc: Exception) -> int:
    """
    Try to extract the suggested retry delay (seconds) from a
    Google API quota error message.  Returns 0 if not found.
    """
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", str(exc))
    if m:
        return int(m.group(1))
    # Fallback: look for "retry in X.X s"
    m2 = re.search(r"retry in (\d+)", str(exc), re.IGNORECASE)
    return int(m2.group(1)) if m2 else 0


def _call_gemini(prompt: str, api_key: str, max_tokens: int = 2048) -> str:
    """Call Google Gemini (free tier via AI Studio)."""
    try:
        import google.generativeai as genai  # type: ignore
        from google.api_core.exceptions import InvalidArgument, PermissionDenied, ResourceExhausted  # type: ignore
    except ImportError:
        raise ImportError("google-generativeai is not installed. Run: pip install google-generativeai")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        PROVIDER_DEFAULTS["gemini"]["model"],
        generation_config={"max_output_tokens": max_tokens},
    )

    def _attempt():
        response = model.generate_content(prompt)
        return response.text.strip()

    try:
        return _attempt()
    except (InvalidArgument, PermissionDenied) as exc:
        err_str = str(exc)
        if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
            raise EnvironmentError(
                "Gemini API key is invalid. "
                'Please check the key you entered (it should start with "AIza") and try again. '
                "Get a valid key at https://aistudio.google.com/app/apikey"
            ) from exc
        raise EnvironmentError(f"Gemini authentication error: {exc}") from exc
    except ResourceExhausted as exc:
        delay = _parse_retry_delay(exc)
        err_str = str(exc)
        # Daily quota hits have limit:0 and cannot be resolved by waiting
        is_daily = "PerDay" in err_str or "limit: 0" in err_str
        if is_daily:
            raise EnvironmentError(
                "Gemini free-tier daily quota exhausted. "
                "Options:\n"
                "  • Wait until midnight Pacific Time for the quota to reset.\n"
                "  • Switch to the Groq provider (free, 14 400 req/day).\n"
                "  • Upgrade to a paid Gemini plan at https://ai.google.dev/pricing"
            ) from exc
        # Per-minute / per-project rate limit — raise immediately with retry time
        wait = min(delay if delay > 0 else 60, 120)
        import datetime

        retry_at = (datetime.datetime.now() + datetime.timedelta(seconds=wait)).strftime("%H:%M:%S")
        raise EnvironmentError(
            f"Gemini rate limit hit (429). "
            f"Please wait until {retry_at} (~{wait}s) and try again, or switch to the Groq provider."
        ) from exc
    except Exception as exc:
        # Surface any other Gemini error cleanly
        raise EnvironmentError(f"Gemini API error: {exc}") from exc


def _parse_groq_retry_delay(exc: Exception) -> int:
    """
    Extract the suggested retry delay (seconds) from a Groq RateLimitError.
    Checks the response headers first, then falls back to parsing the message.
    Returns 0 if not found.
    """
    # Groq SDK attaches the raw httpx response on the exception
    resp = getattr(exc, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", {})
        # retry-after is in seconds
        ra = headers.get("retry-after") or headers.get("Retry-After")
        if ra:
            try:
                return int(float(ra))
            except (ValueError, TypeError):
                pass
        # x-ratelimit-reset-requests  e.g. "1m30s" or "45s"
        reset = headers.get("x-ratelimit-reset-requests") or headers.get("x-ratelimit-reset-tokens")
        if reset:
            m = re.fullmatch(r"(?:(\d+)m)?(\d+)s", reset.strip())
            if m:
                return int(m.group(1) or 0) * 60 + int(m.group(2))
    # Fallback: scan the exception message
    m2 = re.search(r"retry[- ]after[:\s]+(\d+)", str(exc), re.IGNORECASE)
    return int(m2.group(1)) if m2 else 0


def _call_groq(prompt: str, api_key: str, max_tokens: int = 2048) -> str:
    """Call Groq (free tier, Llama 3.3)."""
    try:
        from groq import AuthenticationError as GroqAuthError  # type: ignore
        from groq import Groq  # type: ignore
        from groq import RateLimitError as GroqRateLimitError  # type: ignore
    except ImportError:
        raise ImportError("groq is not installed. Run: pip install groq")
    client = Groq(api_key=api_key)

    def _attempt():
        completion = client.chat.completions.create(
            model=PROVIDER_DEFAULTS["groq"]["model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return completion.choices[0].message.content.strip()

    try:
        return _attempt()
    except GroqAuthError as exc:
        raise EnvironmentError(
            "Groq API key is invalid or has been revoked. "
            'Please check the key you entered (it should start with "gsk_") and try again. '
            "Get a valid key at https://console.groq.com"
        ) from exc
    except GroqRateLimitError as exc:
        delay = _parse_groq_retry_delay(exc)
        wait = min(delay if delay > 0 else 60, 120)
        import datetime

        retry_at = (datetime.datetime.now() + datetime.timedelta(seconds=wait)).strftime("%H:%M:%S")
        raise EnvironmentError(
            f"Groq rate limit hit (429). "
            f"Please wait until {retry_at} (~{wait}s) and try again.\n"
            f"  • Switch to the Gemini provider if Groq stays busy.\n"
            f"  • Check your Groq usage at https://console.groq.com/usage"
        ) from exc
    except Exception as exc:
        raise EnvironmentError(f"Groq API error: {exc}") from exc


def _call_anthropic(prompt: str, api_key: str, max_tokens: int = 2048) -> str:
    """Call Anthropic Claude."""
    try:
        import anthropic as _anthropic  # type: ignore
    except ImportError:
        raise ImportError("anthropic is not installed. Run: pip install anthropic")
    client = _anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model=PROVIDER_DEFAULTS["anthropic"]["model"],
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except _anthropic.AuthenticationError as exc:
        raise EnvironmentError(
            "Anthropic API key is invalid or has been revoked. "
            'Please check the key you entered (it should start with "sk-ant-") and try again. '
            "Get a valid key at https://console.anthropic.com/settings/keys"
        ) from exc
    except _anthropic.RateLimitError as exc:
        import datetime

        retry_at = (datetime.datetime.now() + datetime.timedelta(seconds=60)).strftime("%H:%M:%S")
        raise EnvironmentError(
            f"Anthropic rate limit hit (429). "
            f"Please wait until {retry_at} (~60s) and try again.\n"
            f"  \u2022 Check your Anthropic usage at https://console.anthropic.com/settings/usage"
        ) from exc
    except _anthropic.BadRequestError as exc:
        # Extract the human-readable message from the JSON body if present
        raw = str(exc)
        try:
            import json as _json

            # The SDK str() looks like: "Error code: 400 - {...}"
            json_start = raw.index("{")
            body = _json.loads(raw[json_start:])
            clean = body.get("error", {}).get("message") or raw
        except Exception:
            clean = raw
        # Billing / credit errors get structured guidance
        if "credit" in clean.lower() or "billing" in clean.lower() or "plans" in clean.lower():
            raise EnvironmentError(
                f"Anthropic billing error — insufficient credits.\n"
                f"  \u2022 {clean}\n"
                f"  \u2022 Top up or upgrade at https://console.anthropic.com/settings/billing\n"
                f"  \u2022 Switch to Groq (free) or Gemini (free tier) while credits are low."
            ) from exc
        raise EnvironmentError(f"Anthropic request error: {clean}") from exc
    except Exception as exc:
        raise EnvironmentError(f"Anthropic API error: {exc}") from exc
    return message.content[0].text.strip()


def _call_llm(
    prompt: str,
    provider: str = "gemini",
    api_key: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """
    Dispatch to the appropriate LLM provider.

    Priority for the API key:
      1. *api_key* argument (supplied from the UI field)
      2. Environment variable:
           GEMINI_API_KEY / GROQ_API_KEY / ANTHROPIC_API_KEY
    """
    env_vars = {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    resolved = (api_key or "").strip() or os.environ.get(env_vars.get(provider, ""), "")
    if not resolved:
        env_name = env_vars.get(provider, f"{provider.upper()}_API_KEY")
        raise EnvironmentError(
            f"No API key for provider '{provider}'. "
            f"Provide it in the UI or set the {env_name} environment variable."
        )

    if provider == "gemini":
        return _call_gemini(prompt, resolved, max_tokens)
    if provider == "groq":
        return _call_groq(prompt, resolved, max_tokens)
    if provider == "anthropic":
        return _call_anthropic(prompt, resolved, max_tokens)
    raise ValueError(f"Unknown provider '{provider}'. Choose from: {SUPPORTED_PROVIDERS}")


# kept for backward compatibility ──────────────────────────────────────────────────
def _call_claude(prompt: str, max_tokens: int = 2048, api_key: str | None = None) -> str:
    return _call_llm(prompt, provider="anthropic", api_key=api_key, max_tokens=max_tokens)


def _strip_markdown_fences(text: str) -> str:
    """Remove ```yaml ... ``` or ``` ... ``` wrappers if the model adds them."""
    text = re.sub(r"^```[a-z]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```$", "", text, flags=re.MULTILINE)
    return text.strip()


def _patch_docker_steps(yaml_content: str, has_compose: bool) -> str:
    """
    Post-process the LLM-generated YAML to ensure docker compose commands are
    used whenever a docker-compose file is present.

    When ``has_compose`` is True this function replaces:
      • ``TAG=...`` + ``docker build ...`` run bodies → ``docker compose build`` guard
      • bare ``docker build ...`` run bodies          → ``docker compose build`` guard
      • bare ``docker push ...``   run bodies         → ``docker compose push``

    Login lines that pipe into ``--password-stdin`` are intentionally left alone.
    """
    if not has_compose:
        return yaml_content

    compose_build_guard = "if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; " "then docker compose build; fi"

    def _push_guard(bi: str) -> str:
        """Return a docker compose push guard indented at *bi* (body indent)."""
        return (
            f"if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ]; then\n"
            f"{bi}  docker compose push\n"
            f"{bi}else\n"
            f"{bi}  echo 'docker-compose.yml not found \u2014 skipping push'\n"
            f"{bi}fi"
        )

    lines = yaml_content.splitlines()
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # ── Detect a `run: |` or `run: >` block start ────────────────────────
        run_block_match = re.match(r"^(\s*)run:\s*[|>][-]?\s*$", stripped)
        if run_block_match:
            indent = run_block_match.group(1)
            body_indent = indent + "  "
            # Collect all lines belonging to this block
            block_lines = [stripped]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                # A line with strictly more base indentation belongs to this block,
                # OR it is a blank/comment line inside the block.
                if next_line.strip() == "" or next_line.startswith(body_indent):
                    block_lines.append(next_line)
                    i += 1
                else:
                    break
            # Inspect block body for docker build / docker push
            body_text = "\n".join(block_lines[1:])
            if re.search(r"docker\s+build\b", body_text) and not re.search(r"--password-stdin", body_text):
                result.append(f"{indent}run: |")
                result.append(f"{body_indent}{compose_build_guard}")
                continue  # block_lines consumed, i already advanced
            if re.search(r"docker\s+push\b", body_text) and not re.search(r"--password-stdin", body_text):
                result.append(f"{indent}run: |")
                result.append(f"{body_indent}{_push_guard(body_indent)}")
                continue
            # No match — emit block unchanged
            result.extend(block_lines)
            continue

        # ── Detect an inline `run: docker build ...` ─────────────────────────
        inline_build = re.match(r"^(\s*run:\s+)(docker\s+build\b.*)$", stripped)
        if inline_build and "--password-stdin" not in stripped:
            indent_run = inline_build.group(1)
            result.append(
                f"{indent_run[: len(indent_run) - len(inline_build.group(1).lstrip())]}"
                f"run: |\n{' ' * (len(indent_run) + 2)}{compose_build_guard}"
            )
            # Rewrite properly using leading whitespace
            leading = len(stripped) - len(stripped.lstrip())
            result[-1] = f"{' ' * leading}run: |\n{' ' * (leading + 2)}{compose_build_guard}"
            i += 1
            continue

        # ── Detect an inline `run: docker push ...` ──────────────────────────
        inline_push = re.match(r"^(\s*)run:\s+docker\s+push\b", stripped)
        if inline_push and "--password-stdin" not in stripped:
            leading = len(stripped) - len(stripped.lstrip())
            result.append(f"{' ' * leading}run: |\n" f"{' ' * (leading + 2)}{_push_guard(' ' * (leading + 2))}")
            i += 1
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _strip_docker_push_steps(yaml_content: str) -> str:
    """
    Remove any step that contains a ``docker login`` or a bare ``docker push``
    command in its run body.  Used when ``docker_push_enabled=False`` to
    guarantee the LLM hasn't sneaked in push/login steps despite being told
    not to.

    Steps are identified by their leading ``- name:`` marker. A step is removed
    when its body contains ``docker login`` or ``docker push`` but does NOT
    already contain a ``docker compose push`` (the guarded variant that may be
    legitimately generated by _patch_docker_steps).

    Lines that belong to the **parent** structure (job key, steps key, etc.)
    are never touched.
    """
    lines = yaml_content.splitlines(keepends=True)
    # Find the indentation level of the first step bullet to know step depth
    step_indent: str | None = None
    for line in lines:
        m = re.match(r"^(\s+)-\s+name:", line)
        if m:
            step_indent = m.group(1)
            break
    if step_indent is None:
        return yaml_content  # no steps found — nothing to strip

    # Split into step blocks
    # Each block is a list of lines belonging to one step
    step_bullet_pattern = re.compile(r"^" + re.escape(step_indent) + r"-\s")
    blocks: list[list[str]] = []
    preamble: list[str] = []
    current_block: list[str] = []
    in_steps = False

    for line in lines:
        if step_bullet_pattern.match(line):
            in_steps = True
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        elif in_steps:
            # Lines still belonging to the current step (deeper indentation or blank)
            if line.strip() == "" or line.startswith(step_indent + " "):
                current_block.append(line)
            else:
                # We've left the steps list area — flush and stop
                if current_block:
                    blocks.append(current_block)
                    current_block = []
                # Remaining lines go to a trailing section
                preamble.extend(line for line in [line])  # kept for below
                in_steps = False
                # Put remaining lines into a special "tail" block
                # We'll handle them later — reuse preamble var as tail
                preamble = preamble  # already appended above
        else:
            preamble.append(line)

    if current_block:
        blocks.append(current_block)

    tail_lines: list[str] = []
    # Rebuild: collect everything after steps end
    # Re-identify tail by re-scanning
    # Simpler: rebuild from scratch using original approach
    preamble2: list[str] = []
    step_blocks2: list[list[str]] = []
    tail2: list[str] = []
    current2: list[str] = []
    state = "pre"  # pre → in_steps → post

    for line in lines:
        if state == "pre":
            if step_bullet_pattern.match(line):
                state = "in_steps"
                current2 = [line]
            else:
                preamble2.append(line)
        elif state == "in_steps":
            if step_bullet_pattern.match(line):
                step_blocks2.append(current2)
                current2 = [line]
            elif line.strip() == "" or line.startswith(step_indent + " "):
                current2.append(line)
            else:
                step_blocks2.append(current2)
                current2 = []
                state = "post"
                tail2.append(line)
        else:  # post
            tail2.append(line)

    if current2:
        step_blocks2.append(current2)

    def _should_remove(block: list[str]) -> bool:
        body = "".join(block)
        # When called, push is disabled — remove any step that has docker login
        # or any form of docker push (including docker compose push).
        if re.search(r"docker\s+login\b", body):
            return True
        if re.search(r"docker\s+push\b", body):
            return True
        if re.search(r"docker\s+compose\s+push\b", body):
            return True
        return False

    filtered = [b for b in step_blocks2 if not _should_remove(b)]
    return "".join(preamble2) + "".join("".join(b) for b in filtered) + "".join(tail2)


def _patch_test_runner_steps(yaml_content: str, scan: dict) -> str:
    """
    Post-process LLM-generated YAML to guarantee every detected test runner is
    explicitly installed before it is invoked.

    Uses TEST_RUNNER_INSTALL to look up the runner reported by the scanner and,
    when an install_cmd is defined:
      1. Prepends the install command inside the run: block
      2. Applies any invocation rewrite (e.g. pytest → python -m pytest)
      3. Injects an extra ``env:`` block on the step when required
         (e.g. PYTHONPATH for Python)

    Runners whose install_cmd is None (Go, Rust, Java, Node) ship with the
    standard toolchain and are left unchanged.
    """
    test_runner: str = (scan.get("tests") or {}).get("test_runner") or ""
    if not test_runner:
        return yaml_content

    cfg = TEST_RUNNER_INSTALL.get(test_runner)
    if cfg is None:
        # Unknown runner — try to match the first word as a package name
        first_word = test_runner.split()[0]
        cfg = {
            "install_cmd": None,
            "find_re": re.escape(first_word),
            "rewrite_re": None,
            "extra_env": None,
        }

    install_cmd: str | None = cfg["install_cmd"]
    find_re: str | None = cfg["find_re"]
    rewrite_re: tuple | None = cfg["rewrite_re"]
    extra_env: dict | None = cfg["extra_env"]

    # Nothing to do when no install and no rewrite are needed
    if install_cmd is None and rewrite_re is None and extra_env is None:
        return yaml_content
    # Also nothing to do when there is no search pattern
    if not find_re:
        return yaml_content

    lines = yaml_content.splitlines(keepends=True)
    result: list[str] = []
    i = 0

    # Detect step-bullet indent (leading spaces before "- name:" etc.)
    step_indent: str | None = None
    for line in lines:
        m = re.match(r"^(\s+)-\s+", line)
        if m:
            step_indent = m.group(1)
            break
    if step_indent is None:
        return yaml_content

    while i < len(lines):
        line = lines[i]

        # ── Inline `run: <runner> ...` ─────────────────────────────────────
        inline_match = re.match(r"^(\s*)run:\s+(" + find_re + r".*)$", line.rstrip())
        if inline_match and (rewrite_re is None or rewrite_re[1] not in line):
            leading = inline_match.group(1)
            rest = inline_match.group(2)
            if rewrite_re:
                rest = re.sub(rewrite_re[0], rewrite_re[1], rest)
            result.append(f"{leading}run: |\n")
            if install_cmd:
                result.append(f"{leading}  {install_cmd}\n")
            result.append(f"{leading}  {rest}\n")
            if extra_env:
                result.append(f"{leading}env:\n")
                for k, v in extra_env.items():
                    result.append(f'{leading}  {k}: "{v}"\n')
            i += 1
            continue

        # ── `run: |` block ───────────────────────────────────────────────
        run_block_match = re.match(r"^(\s*)run:\s*[|>][-]?\s*$", line.rstrip())
        if run_block_match:
            block_indent = run_block_match.group(1)
            body_indent = block_indent + "  "
            block_lines: list[str] = [line]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "" or nxt.startswith(body_indent):
                    block_lines.append(nxt)
                    i += 1
                else:
                    break
            body_text = "".join(block_lines[1:])

            # Only patch if the runner appears and hasn't been rewritten already
            already_rewritten = rewrite_re and rewrite_re[1] in body_text
            if re.search(find_re, body_text) and not already_rewritten:
                patched: list[str] = [block_lines[0]]  # keep `run: |` line
                if install_cmd and install_cmd not in body_text:
                    patched.append(f"{body_indent}{install_cmd}\n")
                for bl in block_lines[1:]:
                    if rewrite_re:
                        patched.append(re.sub(rewrite_re[0], rewrite_re[1], bl))
                    else:
                        patched.append(bl)
                result.extend(patched)

                # Inject / merge env: block when needed
                if extra_env:
                    env_injected = False
                    if i < len(lines):
                        peek = lines[i].rstrip()
                        if re.match(r"^" + re.escape(block_indent) + r"env:\s*$", peek):
                            result.append(lines[i])
                            i += 1
                            env_body_indent = block_indent + "  "
                            existing_keys: set[str] = set()
                            env_lines: list[str] = []
                            while i < len(lines):
                                el = lines[i]
                                if el.strip() == "" or el.startswith(env_body_indent):
                                    m2 = re.match(r"^\s*(\w+)\s*:", el)
                                    if m2:
                                        existing_keys.add(m2.group(1))
                                    env_lines.append(el)
                                    i += 1
                                else:
                                    break
                            for k, v in extra_env.items():
                                if k not in existing_keys:
                                    result.append(f'{env_body_indent}{k}: "{v}"\n')
                            result.extend(env_lines)
                            env_injected = True
                    if not env_injected:
                        result.append(f"{block_indent}env:\n")
                        for k, v in extra_env.items():
                            result.append(f'{block_indent}  {k}: "{v}"\n')
                continue
            else:
                result.extend(block_lines)
                continue

        result.append(line)
        i += 1

    return "".join(result)

    raw_lang = scan.get("languages") or scan.get("language")
    langs = raw_lang if isinstance(raw_lang, list) else ([raw_lang] if raw_lang else [])
    if "python" not in langs:
        return yaml_content

    lines = yaml_content.splitlines(keepends=True)
    result: list[str] = []
    i = 0

    # Detect step bullets (leading spaces + "- ")
    step_indent: str | None = None
    for line in lines:
        m = re.match(r"^(\s+)-\s+", line)
        if m:
            step_indent = m.group(1)
            break

    if step_indent is None:
        return yaml_content

    step_bullet = re.compile(r"^" + re.escape(step_indent) + r"-\s")

    while i < len(lines):
        line = lines[i]

        # ── Detect an inline `run: pytest ...` ────────────────────────────────
        inline_pytest = re.match(r"^(\s*)run:\s+(pytest\b.*)$", line.rstrip())
        if inline_pytest and "python -m" not in line:
            leading = inline_pytest.group(1)
            rest = inline_pytest.group(2)
            new_rest = re.sub(r"\bpytest\b", "python -m pytest", rest)
            result.append(f"{leading}run: |\n")
            result.append(f"{leading}  pip install pytest --quiet\n")
            result.append(f"{leading}  {new_rest}\n")
            result.append(f"{leading}env:\n")
            result.append(f'{leading}  PYTHONPATH: "."\n')
            i += 1
            continue

        # ── Detect a `run: |` block ────────────────────────────────────────────
        run_block_match = re.match(r"^(\s*)run:\s*[|>][-]?\s*$", line.rstrip())
        if run_block_match:
            block_indent = run_block_match.group(1)
            body_indent = block_indent + "  "
            block_lines: list[str] = [line]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "" or nxt.startswith(body_indent):
                    block_lines.append(nxt)
                    i += 1
                else:
                    break
            body_text = "".join(block_lines[1:])
            # Only patch if block contains bare pytest and NOT already python -m pytest
            if re.search(r"\bpytest\b", body_text) and "python -m pytest" not in body_text:
                # Rewrite line by line inside the block
                patched: list[str] = [block_lines[0]]  # keep the `run: |` line
                has_pip_install = "pip install pytest" in body_text
                if not has_pip_install:
                    patched.append(f"{body_indent}pip install pytest --quiet\n")
                for bl in block_lines[1:]:
                    patched.append(re.sub(r"\bpytest\b", "python -m pytest", bl))
                result.extend(patched)
                # Now look ahead for an existing `env:` block to patch, or inject one
                # Check if the NEXT non-blank content at the same or shallower indent
                # is already an `env:` key belonging to this step
                env_injected = False
                if i < len(lines):
                    peek = lines[i].rstrip()
                    if re.match(r"^" + re.escape(block_indent) + r"env:\s*$", peek):
                        # There's already an env: block — add PYTHONPATH into it
                        result.append(lines[i])
                        i += 1
                        env_body_indent = block_indent + "  "
                        # Consume existing env vars and check for PYTHONPATH
                        existing_pythonpath = False
                        env_lines: list[str] = []
                        while i < len(lines):
                            el = lines[i]
                            if el.strip() == "" or el.startswith(env_body_indent):
                                if "PYTHONPATH" in el:
                                    existing_pythonpath = True
                                env_lines.append(el)
                                i += 1
                            else:
                                break
                        if not existing_pythonpath:
                            result.append(f'{env_body_indent}PYTHONPATH: "."\n')
                        result.extend(env_lines)
                        env_injected = True
                if not env_injected:
                    result.append(f"{block_indent}env:\n")
                    result.append(f'{block_indent}  PYTHONPATH: "."\n')
                continue  # i already advanced past the block
            else:
                result.extend(block_lines)
                continue

        result.append(line)
        i += 1

    return "".join(result)


def _fix_shell_if_fi(yaml_content: str) -> str:
    """Ensure every ``run: |`` shell block has balanced ``if``/``fi`` pairs.

    The LLM occasionally drops a trailing ``fi`` or duplicates one (e.g. a
    one-liner ``if …; then …; fi`` already contains ``fi`` but the LLM
    still emits a standalone ``fi`` on the next line).  This pass scans
    each ``run: |`` block, counts **all** ``if``/``fi`` tokens using word
    boundaries, and either appends missing ``fi`` lines or strips excess
    standalone ``fi`` lines from the end of the block.
    """
    lines = yaml_content.splitlines(keepends=True)
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect `run: |` block
        m = re.match(r"^(\s*)run:\s*\|[-]?\s*\n?$", line)
        if not m:
            result.append(line)
            i += 1
            continue

        indent = m.group(1)
        body_indent = indent + "  "
        block_lines: list[str] = [line]
        i += 1
        # Collect body lines
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() == "" or nxt.startswith(body_indent):
                block_lines.append(nxt)
                i += 1
            else:
                break

        # Count if / fi in the body using word-boundary matches so that
        # inline one-liners like ``if …; fi`` are counted correctly.
        body = "".join(block_lines[1:])
        # \bif\b but NOT elif (negative lookbehind)
        ifs = len(re.findall(r"(?<!el)\bif\b", body))
        fis = len(re.findall(r"\bfi\b", body))

        if ifs > fis:
            # Append missing fi(s) at the end of the block
            for _ in range(ifs - fis):
                block_lines.append(f"{body_indent}fi\n")
        elif fis > ifs:
            # Remove excess standalone ``fi`` lines from the tail
            excess = fis - ifs
            while excess > 0 and len(block_lines) > 1:
                tail = block_lines[-1]
                if tail.strip() == "fi":
                    block_lines.pop()
                    excess -= 1
                elif tail.strip() == "":
                    # skip trailing blanks so we can reach the fi
                    block_lines.pop()
                else:
                    break  # non-fi content → stop

        result.extend(block_lines)

    return "".join(result)


def generate_pipeline(
    scan: dict,
    platform: str = "github-actions",
    extra_requirements: str = "",
    docker_push_enabled: bool = False,
    api_key: str | None = None,
    provider: str = "gemini",
) -> str:
    """
    Generate a CI/CD pipeline config from scan results.

    Args:
        scan:                Output from scanner.scan_repo()
        platform:            Target CI/CD platform
        extra_requirements:  Optional extra requirements in plain English
        docker_push_enabled: Whether to include Docker login + push steps

    Returns:
        Generated YAML string
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform '{platform}'. Choose from: {SUPPORTED_PLATFORMS}")

    prompt = build_generation_prompt(scan, platform, extra_requirements, docker_push_enabled=docker_push_enabled)
    raw = _call_llm(prompt, provider=provider, api_key=api_key)
    has_compose = "docker-compose" in scan.get("deploy_targets", [])
    result = _patch_docker_steps(_strip_markdown_fences(raw), has_compose=has_compose)
    if not docker_push_enabled:
        result = _strip_docker_push_steps(result)
    result = _patch_test_runner_steps(result, scan)
    result = _fix_shell_if_fi(result)
    return result


def refine_pipeline(
    current_yaml: str,
    user_request: str,
    platform: str = "github-actions",
    api_key: str | None = None,
    provider: str = "gemini",
) -> str:
    """
    Refine an existing pipeline config based on a natural language request.

    Args:
        current_yaml:  The current YAML config as a string
        user_request:  What the user wants changed
        platform:      Target CI/CD platform

    Returns:
        Updated YAML string
    """
    prompt = build_refinement_prompt(current_yaml, user_request, platform)
    raw = _call_llm(prompt, provider=provider, api_key=api_key)
    return _strip_markdown_fences(raw)
