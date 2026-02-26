"""
writer.py
---------
Writes generated CI/CD configs to the correct location in the repository.
Optionally commits the file via git.
"""

import subprocess
from datetime import datetime
from pathlib import Path

# ── Output path mapping ───────────────────────────────────────────────────────

PLATFORM_OUTPUT_PATHS = {
    "github-actions": ".github/workflows/ci.yml",
    "gitlab-ci": ".gitlab-ci.yml",
    "jenkins": "Jenkinsfile",
}


def get_output_path(repo_path: str, platform: str) -> Path:
    """Return the full output path for the generated config."""
    relative = PLATFORM_OUTPUT_PATHS.get(platform, ".github/workflows/ci.yml")
    return Path(repo_path) / relative


def backup_existing(output_path: Path) -> Path | None:
    """
    If a file already exists at output_path, back it up with a timestamp.
    Returns the backup path, or None if no backup was needed.
    """
    if not output_path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = output_path.with_suffix(f".bak_{timestamp}{output_path.suffix}")
    output_path.rename(backup_path)
    return backup_path


def write_config(
    yaml_content: str,
    repo_path: str,
    platform: str = "github-actions",
    overwrite: bool = True,
) -> Path:
    """
    Write the generated YAML to the correct location in the repo.

    Args:
        yaml_content:  The YAML string to write
        repo_path:     Root of the repository
        platform:      CI/CD platform (determines output path)
        overwrite:     If True, back up existing file before overwriting

    Returns:
        The Path where the config was written
    """
    output_path = get_output_path(repo_path, platform)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    backup_path = None
    if overwrite:
        backup_path = backup_existing(output_path)

    output_path.write_text(yaml_content, encoding="utf-8")

    return output_path


def git_commit(repo_path: str, output_path: Path, message: str = "ci: add CI/CD pipeline via cicd-gen") -> bool:
    """
    Stage and commit the generated config file using git.

    Args:
        repo_path:    Root of the repository
        output_path:  Path to the file to commit
        message:      Commit message

    Returns:
        True if commit succeeded, False otherwise
    """
    try:
        rel_path = output_path.relative_to(repo_path)
        subprocess.run(["git", "add", str(rel_path)], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False


def load_config(repo_path: str, platform: str = "github-actions") -> str | None:
    """
    Load an existing config from disk (used for refinement sessions).

    Returns the config as a string, or None if it doesn't exist.
    """
    output_path = get_output_path(repo_path, platform)
    if output_path.exists():
        return output_path.read_text(encoding="utf-8")
    return None
