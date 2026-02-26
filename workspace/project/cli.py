"""
cli.py
------
Command-line interface for cicd-gen.

Commands
--------
  init     Scan a repo and generate a new CI/CD pipeline config
  refine   Iteratively refine an existing generated config
  scan     Show the scan results for a repo without generating anything
"""

import sys
from pathlib import Path

import click
from generator import SUPPORTED_PLATFORMS, generate_pipeline, refine_pipeline
from scanner import scan_repo
from writer import get_output_path, git_commit, load_config, write_config

# ── Colour helpers ────────────────────────────────────────────────────────────


def _header(msg: str) -> None:
    click.echo(click.style(f"\n{'─' * 60}", fg="bright_black"))
    click.echo(click.style(f"  {msg}", fg="cyan", bold=True))
    click.echo(click.style(f"{'─' * 60}", fg="bright_black"))


def _success(msg: str) -> None:
    click.echo(click.style(f"  ✔ {msg}", fg="green"))


def _info(msg: str) -> None:
    click.echo(click.style(f"  · {msg}", fg="bright_white"))


def _warn(msg: str) -> None:
    click.echo(click.style(f"  ⚠ {msg}", fg="yellow"))


def _error(msg: str) -> None:
    click.echo(click.style(f"  ✘ {msg}", fg="red"), err=True)


def _print_scan(scan: dict) -> None:
    """Pretty-print scan results."""
    _header("Repository Scan Results")
    _info(f"Name        : {scan['repo_name']}")
    _info(f"Path        : {scan['repo_path']}")
    _info(f"Language    : {scan['language'] or 'unknown'}")
    _info(f"Frameworks  : {', '.join(scan['frameworks']) or 'none'}")
    _info(f"Pkg manager : {scan['package_manager'] or 'unknown'}")
    _info(f"Has tests   : {scan['tests']['has_tests']}")
    if scan["tests"].get("test_runner"):
        _info(f"Test runner : {scan['tests']['test_runner']}")
    _info(f"Deploy      : {', '.join(scan['deploy_targets']) or 'none'}")
    if scan["existing_ci"]:
        _warn(f"Existing CI : {', '.join(scan['existing_ci'])}")


# ── CLI group ─────────────────────────────────────────────────────────────────


@click.group()
@click.version_option("0.1.0", prog_name="cicd-gen")
def cli():
    """
    \b
    ╔═══════════════════════════════════╗
    ║   cicd-gen  —  CICD-as-a-Service  ║
    ║   AI-powered pipeline generator   ║
    ╚═══════════════════════════════════╝

    Scan your repo, generate a CI/CD config, and iterate in plain English.
    """


# ── cicd-gen scan ─────────────────────────────────────────────────────────────


@cli.command()
@click.argument("repo_path", default=".", metavar="[REPO_PATH]")
def scan(repo_path: str):
    """
    Scan a repository and display its detected tech stack.

    \b
    Examples:
      cicd-gen scan .
      cicd-gen scan ~/projects/my-app
    """
    try:
        result = scan_repo(repo_path)
        _print_scan(result)
    except FileNotFoundError as e:
        _error(str(e))
        sys.exit(1)


# ── cicd-gen init ─────────────────────────────────────────────────────────────


@cli.command()
@click.argument("repo_path", default=".", metavar="[REPO_PATH]")
@click.option(
    "--platform",
    "-p",
    type=click.Choice(SUPPORTED_PLATFORMS),
    default="github-actions",
    show_default=True,
    help="Target CI/CD platform.",
)
@click.option(
    "--requirements",
    "-r",
    default="",
    help="Extra requirements in plain English, e.g. 'deploy to AWS Lambda on main'.",
)
@click.option(
    "--commit",
    "-c",
    is_flag=True,
    default=False,
    help="Auto-commit the generated config with git.",
)
@click.option(
    "--preview",
    "-P",
    is_flag=True,
    default=False,
    help="Print the generated config to stdout without writing to disk.",
)
def init(repo_path: str, platform: str, requirements: str, commit: bool, preview: bool):
    """
    Scan a repo and generate a CI/CD pipeline configuration.

    \b
    Examples:
      cicd-gen init .
      cicd-gen init ~/projects/my-app --platform gitlab-ci
      cicd-gen init . --requirements "deploy to AWS Lambda after tests pass"
      cicd-gen init . --commit
    """
    # ── 1. Scan ──────────────────────────────────────────────────────────────
    _header("Scanning Repository")
    try:
        scan = scan_repo(repo_path)
    except FileNotFoundError as e:
        _error(str(e))
        sys.exit(1)

    _print_scan(scan)

    if scan["existing_ci"] and platform in [ci.replace("-", "_") for ci in scan["existing_ci"]]:
        _warn(f"A {platform} config already exists. It will be backed up before overwriting.")

    # ── 2. Generate ──────────────────────────────────────────────────────────
    _header(f"Generating {platform} Pipeline")
    click.echo(click.style("  Calling Claude API…", fg="bright_black", italic=True))

    try:
        yaml_content = generate_pipeline(scan, platform, requirements)
    except EnvironmentError as e:
        _error(str(e))
        sys.exit(1)
    except Exception as e:
        _error(f"Generation failed: {e}")
        sys.exit(1)

    # ── 3. Preview / Write ───────────────────────────────────────────────────
    if preview:
        _header("Generated Configuration (preview mode — not written to disk)")
        click.echo(yaml_content)
        return

    output_path = write_config(yaml_content, repo_path, platform)
    _success(f"Config written to: {output_path}")

    # ── 4. Show a preview snippet ────────────────────────────────────────────
    _header("Preview (first 30 lines)")
    lines = yaml_content.splitlines()
    for line in lines[:30]:
        click.echo(f"    {line}")
    if len(lines) > 30:
        _info(f"  … ({len(lines) - 30} more lines — open {output_path} to see full config)")

    # ── 5. Optional git commit ───────────────────────────────────────────────
    if commit:
        ok = git_commit(repo_path, output_path)
        if ok:
            _success("Config committed to git.")
        else:
            _warn("Git commit failed (is this a git repo? Are there any changes?).")

    # ── 6. Next-step hint ────────────────────────────────────────────────────
    click.echo()
    _info(f"To refine this config in plain English, run:")
    click.echo(click.style(f"    cicd-gen refine {repo_path} --platform {platform}", fg="cyan"))
    click.echo()


# ── cicd-gen refine ───────────────────────────────────────────────────────────


@cli.command()
@click.argument("repo_path", default=".", metavar="[REPO_PATH]")
@click.option(
    "--platform",
    "-p",
    type=click.Choice(SUPPORTED_PLATFORMS),
    default="github-actions",
    show_default=True,
    help="Target CI/CD platform.",
)
@click.option(
    "--commit",
    "-c",
    is_flag=True,
    default=False,
    help="Auto-commit after each refinement.",
)
def refine(repo_path: str, platform: str, commit: bool):
    """
    Interactively refine an existing generated pipeline in plain English.

    \b
    Examples:
      cicd-gen refine .
      cicd-gen refine ~/projects/my-app --platform github-actions
    """
    # ── Load existing config ─────────────────────────────────────────────────
    current_yaml = load_config(repo_path, platform)
    if current_yaml is None:
        output_path = get_output_path(repo_path, platform)
        _error(f"No existing config found at: {output_path}")
        _info("Run 'cicd-gen init' first to generate a config.")
        sys.exit(1)

    _header(f"Refine Mode  —  {platform}")
    _info("Type your change request in plain English, then press Enter.")
    _info("Type 'show' to display the current config.")
    _info("Type 'done' or Ctrl-C to exit.\n")

    iteration = 0
    while True:
        try:
            request = click.prompt(click.style("  your request", fg="cyan"))
        except (click.Abort, KeyboardInterrupt):
            click.echo()
            _info("Exiting refine mode.")
            break

        stripped = request.strip().lower()
        if stripped in ("done", "exit", "quit", "q"):
            _info("Exiting refine mode.")
            break

        if stripped == "show":
            _header("Current Configuration")
            click.echo(current_yaml)
            continue

        # ── Call Claude to refine ────────────────────────────────────────────
        click.echo(click.style("  Updating pipeline…", fg="bright_black", italic=True))
        try:
            updated_yaml = refine_pipeline(current_yaml, request, platform)
        except EnvironmentError as e:
            _error(str(e))
            sys.exit(1)
        except Exception as e:
            _error(f"Refinement failed: {e}")
            continue

        # ── Write updated config ─────────────────────────────────────────────
        output_path = write_config(updated_yaml, repo_path, platform)
        iteration += 1
        _success(f"[iteration {iteration}] Config updated → {output_path}")

        # Diff summary: count changed lines
        old_lines = set(current_yaml.splitlines())
        new_lines = set(updated_yaml.splitlines())
        added = len(new_lines - old_lines)
        removed = len(old_lines - new_lines)
        _info(f"Changes: +{added} lines added, -{removed} lines removed")

        current_yaml = updated_yaml

        if commit:
            ok = git_commit(repo_path, output_path, message=f"ci: refine pipeline — {request[:60]}")
            if ok:
                _success("Committed to git.")
            else:
                _warn("Git commit failed.")

    click.echo()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
