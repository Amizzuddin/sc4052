"""
scanner.py
----------
Scans a local repository and fingerprints its tech stack.
Returns a structured dict that is later fed into the AI prompt.
"""

import json
import os
from pathlib import Path
from typing import Optional

# ── Language detection ────────────────────────────────────────────────────────

LANGUAGE_SIGNATURES: dict[str, list[str]] = {
    "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
    "node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "go": ["go.mod", "go.sum"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "rust": ["Cargo.toml"],
    "ruby": ["Gemfile", "Rakefile"],
    "php": ["composer.json"],
    "dotnet": [".csproj", ".fsproj", ".sln"],
}

FRAMEWORK_SIGNATURES: dict[str, dict[str, list[str]]] = {
    "python": {
        "django": ["manage.py", "django"],
        "flask": ["flask"],
        "fastapi": ["fastapi"],
        "pytest": ["pytest.ini", "conftest.py"],
    },
    "node": {
        "react": ["react"],
        "next": ["next.config.js", "next.config.ts"],
        "express": ["express"],
        "jest": ["jest.config.js", "jest.config.ts"],
    },
    "go": {
        "gin": ["gin-gonic"],
        "fiber": ["gofiber"],
    },
}

TEST_SIGNATURES: dict[str, list[str]] = {
    "python": ["test_*.py", "*_test.py", "tests/", "test/"],
    "node": ["*.test.js", "*.spec.js", "*.test.ts", "*.spec.ts", "__tests__/"],
    "go": ["*_test.go"],
    "java": ["src/test/"],
    "rust": ["tests/"],
    "ruby": ["spec/", "test/"],
}

DEPLOY_SIGNATURES: dict[str, str] = {
    "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "serverless.yml": "serverless",
    "serverless.yaml": "serverless",
    "terraform": "terraform",  # directory
    "k8s": "kubernetes",  # directory
    "helm": "helm",  # directory
    ".ebextensions": "elastic-beanstalk",  # directory
}


def _glob_exists(root: Path, pattern: str) -> bool:
    """Check if any file matches a glob pattern under root."""
    return any(True for _ in root.glob(f"**/{pattern}"))


def _read_json_file(path: Path) -> dict:
    """Safely read a JSON file."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def detect_language(root: Path) -> Optional[str]:
    """Return the dominant language of the repository."""
    for lang, markers in LANGUAGE_SIGNATURES.items():
        for marker in markers:
            if (root / marker).exists() or _glob_exists(root, marker):
                return lang
    # Fallback: count source file extensions
    ext_counts: dict[str, int] = {}
    for f in root.rglob("*"):
        if f.is_file() and not any(p in f.parts for p in [".git", "node_modules", "__pycache__", ".venv"]):
            ext_counts[f.suffix] = ext_counts.get(f.suffix, 0) + 1
    ext_map = {
        ".py": "python",
        ".js": "node",
        ".ts": "node",
        ".go": "go",
        ".rb": "ruby",
        ".rs": "rust",
        ".java": "java",
    }
    if ext_counts:
        dominant = max(ext_counts, key=ext_counts.get)
        return ext_map.get(dominant)
    return None


def detect_framework(root: Path, language: Optional[str]) -> list[str]:
    """Return detected frameworks for the given language."""
    if language not in FRAMEWORK_SIGNATURES:
        return []
    found = []
    sigs = FRAMEWORK_SIGNATURES[language]

    # For Python, check requirements.txt / pyproject.toml content
    if language == "python":
        dep_files = ["requirements.txt", "requirements-dev.txt"]
        deps_text = ""
        for dep_file in dep_files:
            p = root / dep_file
            if p.exists():
                deps_text += p.read_text(encoding="utf-8").lower()
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            deps_text += pyproject.read_text(encoding="utf-8").lower()
        for fw, keywords in sigs.items():
            if any(kw in deps_text for kw in keywords):
                found.append(fw)
            # also check files
            for kw in keywords:
                if (root / kw).exists():
                    found.append(fw)
                    break

    # For Node, check package.json
    elif language == "node":
        pkg = _read_json_file(root / "package.json")
        all_deps = {
            **pkg.get("dependencies", {}),
            **pkg.get("devDependencies", {}),
        }
        for fw, keywords in sigs.items():
            if any(kw in all_deps for kw in keywords):
                found.append(fw)
            for kw in keywords:
                if (root / kw).exists():
                    found.append(fw)
                    break

    return list(set(found))


def detect_tests(root: Path, language: Optional[str]) -> dict:
    """Return test-related information."""
    result = {"has_tests": False, "test_dirs": [], "test_runner": None}
    if language not in TEST_SIGNATURES:
        return result

    patterns = TEST_SIGNATURES[language]
    found_paths = []
    for pattern in patterns:
        if pattern.endswith("/"):
            d = root / pattern.rstrip("/")
            if d.is_dir():
                found_paths.append(pattern)
        else:
            matches = list(root.rglob(pattern))
            # Exclude venv / node_modules
            matches = [
                m for m in matches if not any(p in m.parts for p in [".venv", "venv", "node_modules", "__pycache__"])
            ]
            if matches:
                found_paths.append(pattern)

    result["has_tests"] = bool(found_paths)
    result["test_dirs"] = found_paths

    # Infer test runner
    runner_map = {
        "python": "pytest",
        "node": "npm test",
        "go": "go test ./...",
        "java": "mvn test",
        "rust": "cargo test",
        "ruby": "bundle exec rspec",
    }
    if result["has_tests"]:
        result["test_runner"] = runner_map.get(language, "unknown")

    return result


def detect_deploy_targets(root: Path) -> list[str]:
    """Detect deployment-related tooling."""
    found = []
    for marker, label in DEPLOY_SIGNATURES.items():
        p = root / marker
        if p.exists():
            found.append(label)
    return list(set(found))


def detect_package_manager(root: Path, language: Optional[str]) -> Optional[str]:
    """Detect the package manager in use."""
    if language == "python":
        if (root / "Pipfile").exists():
            return "pipenv"
        if (root / "pyproject.toml").exists():
            return "pip (pyproject)"
        return "pip"
    if language == "node":
        if (root / "yarn.lock").exists():
            return "yarn"
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        return "npm"
    if language == "go":
        return "go modules"
    if language == "rust":
        return "cargo"
    if language == "java":
        if (root / "pom.xml").exists():
            return "maven"
        return "gradle"
    return None


def detect_existing_ci(root: Path) -> list[str]:
    """Check if a CI/CD config already exists."""
    found = []
    checks = {
        "github-actions": root / ".github" / "workflows",
        "gitlab-ci": root / ".gitlab-ci.yml",
        "circleci": root / ".circleci" / "config.yml",
        "jenkins": root / "Jenkinsfile",
        "travis": root / ".travis.yml",
    }
    for name, path in checks.items():
        if path.exists():
            found.append(name)
    return found


# ── Main entry point ──────────────────────────────────────────────────────────


def scan_repo(repo_path: str) -> dict:
    """
    Scan a repository and return a structured fingerprint dict.

    Args:
        repo_path: Absolute or relative path to the repository root.

    Returns:
        A dict with keys: language, frameworks, tests, deploy_targets,
        package_manager, existing_ci, repo_name.
    """
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path not found: {root}")

    language = detect_language(root)
    frameworks = detect_framework(root, language)
    tests = detect_tests(root, language)
    deploy_targets = detect_deploy_targets(root)
    package_manager = detect_package_manager(root, language)
    existing_ci = detect_existing_ci(root)

    result = {
        "repo_name": root.name,
        "repo_path": str(root),
        "language": language,
        "frameworks": frameworks,
        "package_manager": package_manager,
        "tests": tests,
        "deploy_targets": deploy_targets,
        "existing_ci": existing_ci,
    }
    return result


if __name__ == "__main__":
    import pprint
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "."
    pprint.pprint(scan_repo(path))
