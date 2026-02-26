"""
generator.py
------------
Builds structured prompts from scan results and calls the Claude API
to generate (or refine) a CI/CD pipeline YAML configuration.
"""

import os
import re
from typing import Optional

import anthropic

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
        "lint": "flake8 . --count --select=E9,F63,F7,F82 --show-source",
        "runtime": "python:3.12",
    },
    "node": {
        "install": {
            "npm": "npm ci",
            "yarn": "yarn install --frozen-lockfile",
            "pnpm": "pnpm install --frozen-lockfile",
        },
        "test": "npm test",
        "lint": "npm run lint",
        "runtime": "node:20",
    },
    "go": {
        "install": {"go modules": "go mod download"},
        "test": "go test ./... -v",
        "lint": "go vet ./...",
        "runtime": "go:1.22",
    },
    "java": {
        "install": {
            "maven": "mvn dependency:resolve",
            "gradle": "gradle dependencies",
        },
        "test": "mvn test",
        "lint": None,
        "runtime": "java:21",
    },
    "rust": {
        "install": {"cargo": "cargo fetch"},
        "test": "cargo test",
        "lint": "cargo clippy -- -D warnings",
        "runtime": "rust:latest",
    },
    "ruby": {
        "install": {"bundler": "bundle install"},
        "test": "bundle exec rspec",
        "lint": "bundle exec rubocop",
        "runtime": "ruby:3.3",
    },
}


def _build_context_summary(scan: dict) -> str:
    """Convert scan results into a human-readable summary for the prompt."""
    lines = [
        f"Repository name : {scan.get('repo_name', 'unknown')}",
        f"Language        : {scan.get('language') or 'unknown'}",
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


def _build_install_command(scan: dict) -> str:
    """Infer the right install command from language + package manager."""
    lang = scan.get("language")
    pm = scan.get("package_manager")
    defaults = LANGUAGE_DEFAULTS.get(lang, {})
    install_map = defaults.get("install", {})
    return (
        install_map.get(pm, install_map.get(list(install_map.keys())[0], "echo 'no install step'"))
        if install_map
        else "echo 'no install step'"
    )


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
    install_cmd = _build_install_command(scan)

    lang = scan.get("language", "unknown")
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
- Install dependencies : {install_cmd}
- Run tests            : {test_cmd}
- Lint                 : {lint_cmd}
- Primary runtime      : {runtime}
- Docker build needed  : {has_docker}

PLATFORM INSTRUCTIONS:
{platform_note}
{extra_section}

RULES:
1. Output ONLY the raw YAML (or Jenkinsfile) — no markdown fences, no explanation.
2. Include these pipeline stages in order: install deps → lint → test → (build Docker image if Dockerfile present) → (optional deploy placeholder).
3. Use caching for dependencies where possible.
4. Pin runtime versions explicitly (do not use 'latest' for language runtimes).
5. Add meaningful step names so the pipeline is easy to read.
6. If tests are not detected, add a placeholder test step with a comment.
7. For GitHub Actions, trigger on push to main/master AND on pull requests.

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


def _call_claude(prompt: str, max_tokens: int = 2048) -> str:
    """Send a prompt to Claude and return the text response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Export it before running: export ANTHROPIC_API_KEY='sk-ant-...'"
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def _strip_markdown_fences(text: str) -> str:
    """Remove ```yaml ... ``` or ``` ... ``` wrappers if the model adds them."""
    text = re.sub(r"^```[a-z]*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```$", "", text, flags=re.MULTILINE)
    return text.strip()


def generate_pipeline(
    scan: dict,
    platform: str = "github-actions",
    extra_requirements: str = "",
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
    raw = _call_claude(prompt)
    return _strip_markdown_fences(raw)


def refine_pipeline(
    current_yaml: str,
    user_request: str,
    platform: str = "github-actions",
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
    raw = _call_claude(prompt)
    return _strip_markdown_fences(raw)
