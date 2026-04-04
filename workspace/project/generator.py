################################################################################
#  Filename:      project/generator.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Wednesday, February 25th 2026, 6:44:09 am                    #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday April 4th 2026 8:00:56 am                           #
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


def build_generation_prompt(scan: dict, platform: str, extra_requirements: str = "") -> str:
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
11. IMPORTANT — Docker builds: when `Docker build needed: true`, a single multi-language
   Dockerfile is already committed to the repo root (it covers ALL selected languages in
   one image — do NOT create per-language images).
   Use these exact commands for the Docker build step:
   - GitHub Actions : docker build -t ${{{{github.repository}}}}:${{{{github.sha}}}} .
   - GitLab CI      : docker build -t $CI_PROJECT_PATH:$CI_COMMIT_SHA .
   - Jenkins        : sh "docker build -t ${{env.JOB_NAME}}:${{env.GIT_COMMIT}} ."
   For push, add: docker push <image>:<tag>
   Never reference per-language base images (python:3.12, node:20, ruby:3.3 etc.)
   in the CI Docker step — the Dockerfile already handles the multi-language setup.
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
        # Per-minute / per-project rate limit — wait and retry once
        wait = min(delay if delay > 0 else 60, 120)
        time.sleep(wait)
        try:
            return _attempt()
        except ResourceExhausted as exc2:
            delay2 = _parse_retry_delay(exc2)
            raise EnvironmentError(
                f"Gemini rate limit hit twice. "
                f"Please wait {delay2 or 60}s and try again, or switch to the Groq provider."
            ) from exc2
    except Exception as exc:
        # Surface any other Gemini error cleanly
        raise EnvironmentError(f"Gemini API error: {exc}") from exc


def _call_groq(prompt: str, api_key: str, max_tokens: int = 2048) -> str:
    """Call Groq (free tier, Llama 3.3)."""
    try:
        from groq import AuthenticationError as GroqAuthError  # type: ignore
        from groq import Groq  # type: ignore
    except ImportError:
        raise ImportError("groq is not installed. Run: pip install groq")
    client = Groq(api_key=api_key)
    try:
        completion = client.chat.completions.create(
            model=PROVIDER_DEFAULTS["groq"]["model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
    except GroqAuthError as exc:
        raise EnvironmentError(
            "Groq API key is invalid or has been revoked. "
            'Please check the key you entered (it should start with "gsk_") and try again. '
            "Get a valid key at https://console.groq.com"
        ) from exc
    except Exception as exc:
        raise EnvironmentError(f"Groq API error: {exc}") from exc
    return completion.choices[0].message.content.strip()


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


def generate_pipeline(
    scan: dict,
    platform: str = "github-actions",
    extra_requirements: str = "",
    api_key: str | None = None,
    provider: str = "gemini",
) -> str:
    """
    Generate a CI/CD pipeline config from scan results.

    Args:
        scan:                Output from scanner.scan_repo()
        platform:            Target CI/CD platform
        extra_requirements:  Optional extra requirements in plain English

    Returns:
        Generated YAML string
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform '{platform}'. Choose from: {SUPPORTED_PLATFORMS}")

    prompt = build_generation_prompt(scan, platform, extra_requirements)
    raw = _call_llm(prompt, provider=provider, api_key=api_key)
    return _strip_markdown_fences(raw)


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
