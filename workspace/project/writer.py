################################################################################
#  Filename:      project/writer.py                                            #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Wednesday, February 25th 2026, 6:44:09 am                    #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday April 4th 2026 10:05:02 am                          #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

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
    If a file already exists at output_path, back it up to
    ``<repo_root>/.cicd-gen-backups/`` with a timestamp suffix.

    Backups are kept outside .github/workflows/ so GitHub Actions does not
    treat them as additional workflow files.
    Returns the backup path, or None if no backup was needed.
    """
    if not output_path.exists():
        return None
    # Repo root = the directory that contains .github/ (two levels up from ci.yml)
    # For non-GitHub platforms the file is at repo_root/Jenkinsfile etc., so just
    # go up from the file's parent until we find a .git or hit the fs root.
    backups_dir = output_path.parent
    # Walk up to find repo root (directory containing .git)
    candidate = output_path.parent
    for _ in range(10):  # guard against infinite loops
        if (candidate / ".git").exists() or candidate.parent == candidate:
            backups_dir = candidate / ".cicd-gen-backups"
            break
        candidate = candidate.parent
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backups_dir / f"{output_path.stem}.bak_{timestamp}{output_path.suffix}"
    import shutil

    shutil.copy2(output_path, backup_path)
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

    # Always end with exactly one newline — GitHub Actions YAML parser
    # drops the last step's `run:` block when there is no trailing newline,
    # which causes the cryptic "not enough info" validation error.
    if not yaml_content.endswith("\n"):
        yaml_content += "\n"

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
