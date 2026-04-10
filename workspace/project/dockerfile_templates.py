################################################################################
#  Filename:      project/dockerfile_templates.py                              #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Friday, April 10th 2026, 6:07:13 am                          #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday April 10th 2026 6:25:53 am                            #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""Dockerfile template system — JSON-based, composable by language.

Builds Dockerfiles by combining per-language blocks based on the
Pipeline Configuration selections (languages, package managers, test
runners).  Completely decoupled from the CI template store.

Usage::

    from dockerfile_templates import build_dockerfile, build_compose

    df = build_dockerfile(
        languages=["python", "node"],
        scan=scan_result,           # from scanner.scan_repo()
        base_image="ubuntu:22.04",
    )
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Language registry
# ---------------------------------------------------------------------------
# Each entry describes what a language needs inside the Dockerfile.
#
#   system_packages  : extra apt packages beyond the shared base set
#   toolchain        : optional RUN block to install the runtime *before*
#                      COPY . .  (e.g. curl-based installers)
#   package_managers : dict[pm_name → install command template]
#                      The placeholder ``{guard_file}`` is replaced at render
#                      time with the detected dependency file.
#   test_runners     : dict[runner_name → extra pip / npm install line]
#                      Empty string means the runner ships with the stdlib.
#
LANGUAGE_BLOCKS: dict[str, dict[str, Any]] = {
    "python": {
        "system_packages": ["python3", "python3-pip", "python3-venv"],
        "toolchain": None,
        "package_managers": {
            "pip": (
                "# Python — install deps\n"
                "RUN if [ -f requirements.txt ]; then "
                "pip3 install --no-cache-dir -r requirements.txt; fi"
            ),
            "pip (pyproject)": (
                "# Python — install from pyproject.toml\n"
                "RUN if [ -f pyproject.toml ]; then "
                "pip3 install --no-cache-dir .; fi"
            ),
            "pipenv": (
                "# Python — install via Pipenv\n"
                "RUN pip3 install --no-cache-dir pipenv \\\n"
                " && if [ -f Pipfile ]; then pipenv install --system --deploy; fi"
            ),
            "poetry": (
                "# Python — install via Poetry\n"
                "RUN pip3 install --no-cache-dir poetry \\\n"
                " && if [ -f pyproject.toml ]; then poetry install --no-interaction; fi"
            ),
        },
        "default_pm": "pip",
        "test_runners": {
            "pytest": "RUN pip3 install --no-cache-dir pytest",
            "unittest": "",  # built-in
        },
    },
    "node": {
        "system_packages": [],
        "toolchain": (
            "# Node.js LTS (via NodeSource)\n"
            "RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \\\n"
            "    && apt-get install -y nodejs"
        ),
        "package_managers": {
            "npm": (
                "# Node — install deps\n"
                "RUN if [ -f package-lock.json ]; then npm ci; "
                "elif [ -f package.json ]; then npm install; fi"
            ),
            "yarn": (
                "# Node — install via Yarn\n"
                "RUN npm install -g yarn \\\n"
                " && if [ -f yarn.lock ]; then yarn install --frozen-lockfile; fi"
            ),
            "pnpm": (
                "# Node — install via pnpm\n"
                "RUN npm install -g pnpm \\\n"
                " && if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; fi"
            ),
        },
        "default_pm": "npm",
        "test_runners": {
            "jest": "RUN npm install -g jest",
            "mocha": "RUN npm install -g mocha",
            "vitest": "",  # project-local
        },
    },
    "typescript": {
        # Shares the same blocks as node
        "system_packages": [],
        "toolchain": (
            "# Node.js LTS (via NodeSource)\n"
            "RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \\\n"
            "    && apt-get install -y nodejs"
        ),
        "package_managers": {
            "npm": (
                "# Node/TS — install deps\n"
                "RUN if [ -f package-lock.json ]; then npm ci; "
                "elif [ -f package.json ]; then npm install; fi"
            ),
            "yarn": (
                "# Node/TS — install via Yarn\n"
                "RUN npm install -g yarn \\\n"
                " && if [ -f yarn.lock ]; then yarn install --frozen-lockfile; fi"
            ),
            "pnpm": (
                "# Node/TS — install via pnpm\n"
                "RUN npm install -g pnpm \\\n"
                " && if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; fi"
            ),
        },
        "default_pm": "npm",
        "test_runners": {
            "jest": "RUN npm install -g jest",
            "mocha": "RUN npm install -g mocha",
            "vitest": "",
        },
    },
    "go": {
        "system_packages": [],
        "toolchain": (
            "# Go toolchain\n"
            "RUN curl -fsSL https://go.dev/dl/go1.22.0.linux-amd64.tar.gz \\\n"
            "    | tar -C /usr/local -xz\n"
            "ENV PATH=$PATH:/usr/local/go/bin"
        ),
        "package_managers": {
            "go modules": ("# Go — download modules\n" "RUN if [ -f go.mod ]; then go mod download; fi"),
        },
        "default_pm": "go modules",
        "test_runners": {
            "go test": "",  # built-in
        },
    },
    "rust": {
        "system_packages": [],
        "toolchain": (
            "# Rust toolchain (rustup)\n"
            "RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs "
            "| sh -s -- -y\n"
            "ENV PATH=$PATH:/root/.cargo/bin"
        ),
        "package_managers": {
            "cargo": ("# Rust — prefetch crate registry\n" "RUN if [ -f Cargo.toml ]; then cargo fetch; fi"),
        },
        "default_pm": "cargo",
        "test_runners": {
            "cargo test": "",  # built-in
        },
    },
    "ruby": {
        "system_packages": ["ruby", "ruby-dev", "libffi-dev", "libssl-dev"],
        "toolchain": None,
        "package_managers": {
            "bundler": (
                "# Ruby — install gems\n"
                "RUN if [ -f Gemfile ]; then "
                "gem install bundler --no-document && bundle install; fi"
            ),
        },
        "default_pm": "bundler",
        "test_runners": {
            "rspec": "RUN gem install rspec --no-document",
            "minitest": "",  # built-in
        },
    },
    "java": {
        "system_packages": ["default-jdk"],
        "toolchain": None,
        "package_managers": {
            "maven": (
                "# Java — resolve Maven dependencies\n" "RUN if [ -f pom.xml ]; then mvn dependency:resolve -q; fi"
            ),
            "gradle": (
                "# Java — resolve Gradle dependencies\n" "RUN if [ -f build.gradle ]; then gradle dependencies -q; fi"
            ),
        },
        "default_pm": "maven",
        "test_runners": {
            "junit": "",  # bundled via build tool
        },
    },
    "kotlin": {
        "system_packages": ["default-jdk"],
        "toolchain": None,
        "package_managers": {
            "maven": (
                "# Kotlin — resolve Maven dependencies\n" "RUN if [ -f pom.xml ]; then mvn dependency:resolve -q; fi"
            ),
            "gradle": (
                "# Kotlin — resolve Gradle dependencies\n"
                "RUN if [ -f build.gradle ] || [ -f build.gradle.kts ]; then "
                "gradle dependencies -q; fi"
            ),
        },
        "default_pm": "gradle",
        "test_runners": {
            "junit": "",
        },
    },
    "php": {
        "system_packages": ["php", "php-cli", "php-mbstring", "php-xml"],
        "toolchain": (
            "# PHP Composer\n"
            "RUN curl -sS https://getcomposer.org/installer \\\n"
            "    | php -- --install-dir=/usr/local/bin --filename=composer"
        ),
        "package_managers": {
            "composer": (
                "# PHP — install composer packages\n"
                "RUN if [ -f composer.json ]; then "
                "composer install --no-dev --optimize-autoloader; fi"
            ),
        },
        "default_pm": "composer",
        "test_runners": {
            "phpunit": "RUN composer global require phpunit/phpunit",
        },
    },
    "dotnet": {
        "system_packages": [],
        "toolchain": (
            "# .NET SDK\n"
            "RUN curl -fsSL https://dot.net/v1/dotnet-install.sh \\\n"
            "    | bash /dev/stdin --channel 8.0\n"
            "ENV PATH=$PATH:/root/.dotnet:/root/.dotnet/tools"
        ),
        "package_managers": {
            "nuget": ("# .NET — restore packages\n" "RUN if ls *.csproj 1>/dev/null 2>&1; then dotnet restore; fi"),
        },
        "default_pm": "nuget",
        "test_runners": {
            "dotnet test": "",  # built-in
        },
    },
}

# Shared base apt packages present in every generated Dockerfile.
_BASE_APT = {"curl", "ca-certificates", "git", "build-essential", "unzip"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_dockerfile(
    languages: list[str],
    scan: dict | None = None,
    *,
    base_image: str = "ubuntu:22.04",
) -> str:
    """Compose a multi-language Dockerfile from template blocks.

    Args:
        languages:  List of language names selected in Pipeline Config.
        scan:       Output from ``scanner.scan_repo()`` — used to pick
                    the right package-manager and test-runner variants.
                    Pass ``None`` to use defaults.
        base_image: Docker base image (FROM line).

    Returns:
        Complete Dockerfile content as a string.
    """
    scan = scan or {}
    apt_pkgs: set[str] = set(_BASE_APT)
    toolchain_blocks: list[str] = []
    install_blocks: list[str] = []
    test_blocks: list[str] = []

    # Deduplicate (node + typescript share toolchain)
    seen_toolchains: set[str] = set()

    for lang in languages:
        block = LANGUAGE_BLOCKS.get(lang.lower())
        if not block:
            continue

        # ── system packages ───────────────────────────────────────────
        apt_pkgs.update(block.get("system_packages") or [])

        # ── toolchain (before COPY) ──────────────────────────────────
        tc = block.get("toolchain")
        if tc and tc not in seen_toolchains:
            seen_toolchains.add(tc)
            toolchain_blocks.append(tc)

        # ── package-manager install (after COPY) ─────────────────────
        pm_map = block.get("package_managers") or {}
        detected_pm = _detect_pm_for_lang(lang, scan)
        pm_cmd = pm_map.get(detected_pm) or pm_map.get(block.get("default_pm", ""))
        if pm_cmd:
            install_blocks.append(pm_cmd)

        # ── test runner ──────────────────────────────────────────────
        tr_map = block.get("test_runners") or {}
        detected_tr = _detect_test_runner(lang, scan)
        tr_cmd = tr_map.get(detected_tr, "")
        if tr_cmd:
            test_blocks.append(tr_cmd)

    # ── Assemble Dockerfile ───────────────────────────────────────────────
    pkgs_str = " \\\n    ".join(sorted(apt_pkgs))
    parts: list[str] = [
        f"FROM {base_image}",
        "",
        'LABEL maintainer="cicd-gen"',
        "",
        "# Avoid interactive prompts during apt installs",
        "ENV DEBIAN_FRONTEND=noninteractive",
        "WORKDIR /app",
        "",
        "# ── 1. System packages ───────────────────────────────────────────────",
        f"RUN apt-get update && apt-get install -y \\\n    {pkgs_str} \\\n    && rm -rf /var/lib/apt/lists/*",
        "",
    ]

    if toolchain_blocks:
        parts.append("# ── 2. Language toolchain installs ──────────────────────────────────")
        for blk in toolchain_blocks:
            parts.append(blk)
            parts.append("")

    parts += [
        "# ── 3. Copy application source ──────────────────────────────────────",
        "COPY . .",
        "",
    ]

    if install_blocks:
        parts.append("# ── 4. Install language dependencies ────────────────────────────────")
        for blk in install_blocks:
            parts.append(blk)
            parts.append("")

    if test_blocks:
        parts.append("# ── 5. Install test runners ─────────────────────────────────────────")
        for blk in test_blocks:
            parts.append(blk)
            parts.append("")

    parts += [
        "# Override CMD in docker-compose or at 'docker run' time",
        'CMD ["bash"]',
        "",
    ]
    return "\n".join(parts)


def build_compose(
    image_name: str,
    languages: list[str],
    *,
    docker_push: bool = False,
) -> str:
    """Generate a ``docker-compose.yml`` for the project.

    Args:
        image_name:   Repository / service name.
        languages:    Selected languages (unused for now — reserved).
        docker_push:  If *True*, prefix image with ``${DOCKER_USERNAME}/``.

    Returns:
        ``docker-compose.yml`` content as a string.
    """
    safe_name = re.sub(r"[^a-z0-9_-]", "-", image_name.lower()) if image_name else "app"
    if docker_push:
        image_ref = f"${{DOCKER_USERNAME}}/{safe_name}:latest"
    else:
        image_ref = f"{safe_name}:latest"
    return (
        'version: "3.8"\n'
        "\n"
        "services:\n"
        f"  {safe_name}:\n"
        "    build:\n"
        "      context: .\n"
        "      dockerfile: Dockerfile\n"
        f"    image: {image_ref}\n"
        "    # Uncomment to expose a port:\n"
        "    # ports:\n"
        '    #   - "8080:8080"\n'
        "    # Uncomment to set environment variables:\n"
        "    # environment:\n"
        "    #   - ENV_VAR=value\n"
        "    # Uncomment to mount source for live-reload:\n"
        "    # volumes:\n"
        "    #   - .:/app\n"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_pm_for_lang(lang: str, scan: dict) -> str:
    """Pick the right package manager for *lang* from scan data."""
    # scan["package_manager"] is a single string for the primary language.
    # For multi-language builds, fall back to the language default.
    pm = (scan.get("package_manager") or "").lower()

    mapping: dict[str, dict[str, str]] = {
        "python": {
            "pip": "pip",
            "pip (pyproject)": "pip (pyproject)",
            "pipenv": "pipenv",
            "poetry": "poetry",
        },
        "node": {"npm": "npm", "yarn": "yarn", "pnpm": "pnpm"},
        "typescript": {"npm": "npm", "yarn": "yarn", "pnpm": "pnpm"},
        "java": {"maven": "maven", "gradle": "gradle"},
        "kotlin": {"maven": "maven", "gradle": "gradle"},
    }

    lang_map = mapping.get(lang.lower(), {})
    for key, value in lang_map.items():
        if key in pm:
            return value

    # Default for this language
    block = LANGUAGE_BLOCKS.get(lang.lower(), {})
    return block.get("default_pm", "")


def _detect_test_runner(lang: str, scan: dict) -> str:
    """Pick the right test runner for *lang* from scan data."""
    runner = (scan.get("tests", {}).get("test_runner") or "").lower()

    mapping: dict[str, dict[str, str]] = {
        "python": {"pytest": "pytest", "unittest": "unittest"},
        "node": {"jest": "jest", "mocha": "mocha", "vitest": "vitest"},
        "typescript": {"jest": "jest", "mocha": "mocha", "vitest": "vitest"},
        "ruby": {"rspec": "rspec", "minitest": "minitest"},
    }

    lang_map = mapping.get(lang.lower(), {})
    for key, value in lang_map.items():
        if key in runner:
            return value

    # Return first available runner as default
    block = LANGUAGE_BLOCKS.get(lang.lower(), {})
    runners = block.get("test_runners", {})
    return next(iter(runners), "")
