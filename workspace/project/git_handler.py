################################################################################
#  Filename:      project/git_handler.py                                       #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 10:03:01 am                        #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday April 10th 2026 11:10:06 am                           #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
git_handler.py
--------------
Git helpers for cicd-gen.

Responsibilities:
  - URL utilities: injecting tokens, masking credentials
  - Pre-commit config generation
  - Stub dependency file creation
  - Branch management (create, commit, push)
  - Temporary clone cleanup
"""

import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import git
from writer import write_config

# ── Stub dependency file templates ───────────────────────────────────────────

# Keyed by language name; value is {filename: default_content}.
# These are written when no dependency file exists so that CI hooks
# (e.g. pip install, npm ci) have something to operate on.
LANG_STUB_FILES: dict[str, dict[str, str]] = {
    "python": {
        "requirements.txt": (
            "# Python dependencies — add your packages here, one per line.\n"
            "# Examples:\n"
            "#   requests>=2.31.0\n"
            "#   flask>=3.0.0\n"
        ),
    },
    "node": {
        "package.json": (
            "{\n"
            '  "name": "app",\n'
            '  "version": "1.0.0",\n'
            '  "description": "",\n'
            '  "scripts": {\n'
            '    "test": "echo \\\\ No tests yet && exit 0",\n'
            '    "lint": "echo \\\\ No lint yet"\n'
            "  },\n"
            '  "dependencies": {},\n'
            '  "devDependencies": {}\n'
            "}\n"
        ),
    },
    "ruby": {
        "Gemfile": (
            "# frozen_string_literal: true\n"
            "\n"
            "source 'https://rubygems.org'\n"
            "\n"
            "# Add your gems here. Examples:\n"
            "# gem 'rails', '~> 7.1'\n"
            "# gem 'rspec', group: :test\n"
        ),
    },
    "php": {
        "composer.json": '{\n  "require": {},\n  "require-dev": {}\n}\n',
    },
}

# ── Pre-commit config generation ─────────────────────────────────────────────

_PRECOMMIT_COMMON = """\
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-merge-conflict
"""

_PRECOMMIT_LANG_HOOKS: dict[str, str] = {
    "python": """\
  - repo: https://github.com/psf/black
    rev: 24.10.0
    hooks:
      - id: black
  - repo: https://github.com/PyCQA/flake8
    rev: 7.1.1
    hooks:
      - id: flake8
        args: ['--max-line-length=120']
  - repo: https://github.com/PyCQA/isort
    rev: 5.13.2
    hooks:
      - id: isort
        args: ['--profile=black']
""",
    "node": """\
  - repo: local
    hooks:
      - id: npm-lint
        name: npm run lint
        entry: bash -c '[ -f package.json ] && npm run lint --if-present || echo "Skipping npm lint (no package.json)"'
        language: system
        pass_filenames: false
""",
    "go": """\
  - repo: https://github.com/dnephin/pre-commit-golang
    rev: v0.5.1
    hooks:
      - id: go-fmt
      - id: go-vet
      - id: go-lint
""",
    "rust": """\
  - repo: local
    hooks:
      - id: cargo-fmt
        name: cargo fmt
        entry: bash -c '[ -f Cargo.toml ] && cargo fmt -- || echo "Skipping cargo fmt (no Cargo.toml)"'
        language: system
        types: [rust]
        pass_filenames: false
      - id: cargo-clippy
        name: cargo clippy
        entry: bash -c '[ -f Cargo.toml ] && cargo clippy -- -D warnings || echo "Skipping cargo clippy (no Cargo.toml)"'
        language: system
        pass_filenames: false
""",
    "ruby": """\
  - repo: https://github.com/rubocop/rubocop
    rev: v1.68.0
    hooks:
      - id: rubocop
        args: ['--autocorrect']
""",
    "php": """\
  - repo: https://github.com/digitalpulp/pre-commit-php
    rev: 1.4.0
    hooks:
      - id: php-lint
""",
    "bash": """\
  - repo: https://github.com/shellcheck-py/shellcheck-py
    rev: v0.10.0.1
    hooks:
      - id: shellcheck
""",
    "typescript": """\
  - repo: local
    hooks:
      - id: npm-lint-ts
        name: npm run lint (TypeScript)
        entry: bash -c '[ -f package.json ] && npm run lint --if-present || echo "Skipping npm lint (no package.json)"'
        language: system
        pass_filenames: false
""",
}


def _build_precommit_config(langs: list[str]) -> str:
    """Build a .pre-commit-config.yaml combining common + per-language hooks."""
    body = "repos:\n" + _PRECOMMIT_COMMON
    for lang in langs:
        if lang in _PRECOMMIT_LANG_HOOKS:
            body += _PRECOMMIT_LANG_HOOKS[lang]
    body += (
        "\n"
        "# To skip a hook for a specific commit: git commit -n\n"
        "# To update all hooks to latest versions: pre-commit autoupdate\n"
    )
    return body


# ── URL helpers ───────────────────────────────────────────────────────────────


def _is_ssh_url(url: str) -> bool:
    """Return True for git@host:owner/repo style URLs."""
    return bool(re.match(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:", url.strip()))


def _inject_token(https_url: str, token: str) -> str:
    """
    Embed *token* into *https_url* as a URL credential so gitpython can
    authenticate without an interactive prompt.

    GitHub  : https://<token>@github.com/owner/repo.git
    GitLab  : https://oauth2:<token>@gitlab.com/owner/repo.git
    Generic : https://<token>@host/...
    """
    parsed = urllib.parse.urlparse(https_url)
    host = parsed.netloc.lower()
    if "gitlab" in host:
        netloc = f"oauth2:{token}@{host}"
    else:
        netloc = f"{token}@{host}"
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


def _safe_url(https_url: str) -> str:
    """Strip credentials from a URL so it is safe to display."""
    parsed = urllib.parse.urlparse(https_url)
    safe_netloc = re.sub(r"^[^@]+@", "", parsed.netloc)
    return urllib.parse.urlunparse(parsed._replace(netloc=safe_netloc))


# ── README generation ─────────────────────────────────────────────────────────


def _github_readme(platform: str, yaml_rel: str, branch_name: str) -> str:
    """Return the content for .github/README.md."""
    branch_section = ""
    if platform == "github-actions":
        branch_section = """
## Changing which branches trigger CI

Open `{yaml_rel}` and find the `on:` block near the top:

```yaml
on:
  push:
    # Runs on every branch. To restrict, replace '**' with a list:
    # branches: [main, develop, 'release/**']
    branches: ["**"]
  pull_request:
    branches: ["**"]
```

Replace `["**"]` with the branch names you want, for example:

```yaml
    branches: [main, develop]
```
""".format(
            yaml_rel=yaml_rel
        )
    elif platform == "gitlab-ci":
        branch_section = """
## Changing which branches trigger CI

Open `.gitlab-ci.yml`. Each job can have an `only:` key to restrict branches:

```yaml
build:
  only:
    - main
    - develop
```

Omitting `only:` (the default) means the job runs on every branch.
"""
    elif platform == "jenkins":
        branch_section = """
## Changing which branches trigger CI

Open the `Jenkinsfile` and add or update the `when` condition inside each stage:

```groovy
when { branch pattern: 'main|develop', comparator: 'REGEXP' }
```

Remove the `when` block entirely to run all stages on every branch.
"""

    return f"""# CI/CD Pipeline — generated by cicd-gen

This pipeline was automatically generated and committed to the
`{branch_name}` branch.  Review the file before merging into your default branch.

## Generated file

| Platform | Config file |
|---|---|
| `{platform}` | `{yaml_rel}` |
{branch_section}
## Making changes

1. Review the generated config in `{yaml_rel}`.
2. Edit it directly on GitHub or check out the `{branch_name}` branch locally.
3. Open a Pull Request from `{branch_name}` into your default branch when satisfied.

## Resources

- [GitHub Actions docs](https://docs.github.com/en/actions)
- [GitLab CI/CD docs](https://docs.gitlab.com/ee/ci/)
- [Jenkins Pipeline docs](https://www.jenkins.io/doc/book/pipeline/)

---
*Generated by [cicd-gen](https://github.com) — AI-powered CI/CD generator.*
"""


# ── Stub dependency file creation ────────────────────────────────────────────


def _create_stub_dep_files(clone_path: str, scan: dict) -> list[str]:
    """
    Create stub dependency files and .pre-commit-config.yaml for any
    language that needs them but is missing them.
    Returns a list of relative path strings that were created (for git staging).
    """
    created: list[str] = []
    raw_lang = scan.get("languages") or scan.get("language")
    langs = raw_lang if isinstance(raw_lang, list) else ([raw_lang] if raw_lang else [])
    for lang in langs:
        for filename, content in LANG_STUB_FILES.get(lang, {}).items():
            target = Path(clone_path) / filename
            if not target.exists():
                target.write_text(content)
                created.append(filename)

    # Always ensure a .pre-commit-config.yaml exists
    precommit_path = Path(clone_path) / ".pre-commit-config.yaml"
    if not precommit_path.exists() and langs:
        precommit_path.write_text(_build_precommit_config(langs))
        created.append(".pre-commit-config.yaml")

    return created


def _ensure_trailing_newline(path: Path) -> None:
    """Match the behaviour of *end-of-file-fixer*:
    - Whitespace-only files → empty (0 bytes).
    - Non-empty files → end with exactly one ``\n``.
    """
    content = path.read_text()
    # end-of-file-fixer treats whitespace-only files as empty
    if not content.strip():
        if content:  # was non-empty whitespace → truncate
            path.write_text("")
        return
    stripped = content.rstrip()
    if content != stripped + "\n":
        path.write_text(stripped + "\n")


def _run_precommit_on_files(clone_path: str, rel_files: list[str]) -> None:
    """
    Run `pre-commit run --files <rel_files>` (up to two passes) against a
    specific subset of files.  Used for a focused Docker pre-flight check
    before the broader --all-files scan.

    Pass 1 — hooks auto-fix issues (exit 1 = files modified, expected).
    Pass 2 — verify the fixes are stable (exit 0 = clean).
    Warnings are printed but never block the commit.
    """
    pre_commit_bin = shutil.which("pre-commit")
    if not pre_commit_bin or not rel_files:
        return

    # Only check files that actually exist
    existing = [f for f in rel_files if (Path(clone_path) / f).exists()]
    if not existing:
        return

    def _run_once():
        return subprocess.run(
            [pre_commit_bin, "run", "--files", *existing],
            cwd=clone_path,
            capture_output=True,
            text=True,
        )

    r1 = _run_once()
    if r1.returncode == 0:
        return  # clean on first pass
    if r1.returncode == 1:
        r2 = _run_once()
        if r2.returncode not in (0, 1):
            print(
                f"[cicd-gen] pre-commit (docker pass 2, exit {r2.returncode}):\n{r2.stderr}",
                file=sys.stderr,
            )
    else:
        print(
            f"[cicd-gen] pre-commit (docker, exit {r1.returncode}):\n{r1.stderr}",
            file=sys.stderr,
        )


def _run_precommit_local(clone_path: str) -> None:
    """Format every file in *clone_path* so pre-commit in CI passes cleanly.

    Strategy (belt-and-suspenders):
    1. Fix end-of-file newlines ourselves (matches ``end-of-file-fixer``).
    2. Run ``black`` and ``isort`` **directly** on every ``*.py`` file —
       this is the guaranteed formatter pass that does NOT depend on
       pre-commit hook environments being downloadable inside the
       container.
    3. *Then* attempt ``pre-commit run --all-files`` (2-pass) as a
       best-effort catch-all for any remaining hooks.
    """
    repo_root = Path(clone_path)

    # ── 1. end-of-file newlines ──────────────────────────────────────────
    for p in repo_root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            try:
                _ensure_trailing_newline(p)
            except Exception:
                pass

    # ── 2. Direct black + isort (guaranteed, no hook env needed) ─────────
    py_files = [str(p) for p in repo_root.rglob("*.py") if ".git" not in p.parts]
    if py_files:
        black_bin = shutil.which("black")
        if black_bin:
            r = subprocess.run(
                [black_bin, "--quiet", *py_files],
                cwd=clone_path,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                print(
                    f"[cicd-gen] black warning (exit {r.returncode}):\n{r.stderr}",
                    file=sys.stderr,
                )
        isort_bin = shutil.which("isort")
        if isort_bin:
            r = subprocess.run(
                [isort_bin, "--profile", "black", "--quiet", *py_files],
                cwd=clone_path,
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                print(
                    f"[cicd-gen] isort warning (exit {r.returncode}):\n{r.stderr}",
                    file=sys.stderr,
                )

    # Re-fix newlines after formatters may have added trailing whitespace
    for p in repo_root.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            try:
                _ensure_trailing_newline(p)
            except Exception:
                pass

    # ── 3. Best-effort pre-commit (catches any remaining hooks) ──────────
    pre_commit_bin = shutil.which("pre-commit")
    if not pre_commit_bin:
        return

    def _run_once():
        return subprocess.run(
            [pre_commit_bin, "run", "--all-files"],
            cwd=clone_path,
            capture_output=True,
            text=True,
        )

    r1 = _run_once()
    if r1.returncode == 0:
        return  # already clean on first pass
    if r1.returncode == 1:
        # Formatters modified files — run again to verify stability
        r2 = _run_once()
        if r2.returncode not in (0, 1):
            print(
                f"[cicd-gen] pre-commit warning (pass 2, exit {r2.returncode}):\n{r2.stderr}",
                file=sys.stderr,
            )
    else:
        print(
            f"[cicd-gen] pre-commit warning (exit {r1.returncode}):\n{r1.stderr}",
            file=sys.stderr,
        )


# ── Branch management ────────────────────────────────────────────────────────


def _commit_on_branch(
    repo: git.Repo,
    clone_path: str,
    branch_name: str,
    platform: str,
    yaml_content: str,
    scan: dict | None = None,
    extra_files: dict[str, str] | None = None,
) -> str:
    """Write the generated config + .github/README.md + stub dep files and commit on *branch_name*."""
    is_empty = len(repo.heads) == 0
    output_path = write_config(yaml_content, clone_path, platform)
    rel = output_path.relative_to(clone_path)

    # Write any extra generated files (Dockerfile, docker-compose.yml, etc.)
    extra_rels: list[str] = []
    for rel_name, content in (extra_files or {}).items():
        target = Path(clone_path) / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Guarantee a trailing newline so end-of-file-fixer never trips in CI.
        if not content.endswith("\n"):
            content += "\n"
        target.write_text(content)
        extra_rels.append(rel_name)

    # Write .github/README.md alongside the pipeline
    readme_path = Path(clone_path) / ".github" / "README.md"
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(_github_readme(platform, str(rel), branch_name))
    readme_rel = readme_path.relative_to(clone_path)

    # Create stub dependency files for languages that have none yet
    stub_rels = _create_stub_dep_files(clone_path, scan or {})

    # ── Docker pre-flight check ──────────────────────────────────────────────
    # Run pre-commit only on Docker files first so issues are caught and
    # auto-fixed in a focused pass before the broader --all-files scan.
    docker_files = [r for r in extra_rels if r in ("Dockerfile", "docker-compose.yml")]
    if docker_files:
        _run_precommit_on_files(clone_path, docker_files)

    # Run pre-commit locally to auto-fix end-of-file, trailing whitespace, etc.
    # This prevents the GitHub Actions run from failing on trivial formatting issues.
    _run_precommit_local(clone_path)

    # Remove any leftover .cicd-gen-backups directory so it is never committed.
    _backups_dir = Path(clone_path) / ".cicd-gen-backups"
    if _backups_dir.exists():
        shutil.rmtree(_backups_dir, ignore_errors=True)

    # Stage EVERYTHING (including any files auto-fixed by pre-commit hooks)
    if is_empty:
        repo.git.symbolic_ref("HEAD", f"refs/heads/{branch_name}")
        repo.git.add(".")
        repo.index.commit("ci: bootstrap CI/CD pipeline via cicd-gen")
        stub_note = f", {', '.join(stub_rels)}" if stub_rels else ""
        extra_note = f", {', '.join(extra_rels)}" if extra_rels else ""
        return f"Initial commit on branch '{branch_name}'. Files: {rel}, {readme_rel}{stub_note}{extra_note}."

    if branch_name in [h.name for h in repo.heads]:
        repo.git.checkout(branch_name)
        created = False
    else:
        repo.git.checkout("-b", branch_name)
        created = True

    repo.git.add(".")
    repo.index.commit("ci: add CI/CD pipeline via cicd-gen")
    stub_note = f", {', '.join(stub_rels)}" if stub_rels else ""
    extra_note = f", {', '.join(extra_rels)}" if extra_rels else ""
    return f"Branch '{branch_name}' {'created' if created else 'updated'}. Files: {rel}, {readme_rel}{stub_note}{extra_note}."


def _push_branch(repo: git.Repo, push_url: str, branch_name: str, auth_type: str) -> None:
    """Push *branch_name* to the remote."""
    env = dict(os.environ)
    origin = repo.remote("origin")
    origin.set_url(push_url)
    origin.push(refspec=f"{branch_name}:{branch_name}", env=env)


def _cleanup(path: str) -> None:
    """Remove a temporary clone directory, ignoring errors."""
    try:
        if path and Path(path).exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
