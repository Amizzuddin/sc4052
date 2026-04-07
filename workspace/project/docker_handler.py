"""
docker_handler.py
-----------------
Docker file generators for cicd-gen.

Generates:
  - A single multi-language Dockerfile (one image covering all selected languages)
  - A matching docker-compose.yml
"""

import re

DEFAULT_DOCKER_BASE_IMAGE = "ubuntu:22.04"


def _generate_dockerfile(langs: list[str], base_image: str = "ubuntu:22.04") -> str:
    """
    Generate a single multi-language Dockerfile covering all selected languages.

    Structure:
      1. System apt packages
      2. Language runtime/toolchain installs  (no COPY — avoids build failure
         when optional dependency files are absent from the repo)
      3. COPY . .  (copies everything including dep files)
      4. Per-language dependency install commands (guarded by file existence checks)
    """
    apt_pkgs: set[str] = {"curl", "ca-certificates", "git", "build-essential", "unzip"}
    toolchain_blocks: list[str] = []  # Before COPY . .
    install_blocks: list[str] = []  # After  COPY . .

    if "python" in langs:
        apt_pkgs.update(["python3", "python3-pip", "python3-venv"])
        install_blocks.append(
            "# Python — install deps\n"
            "RUN if [ -f requirements.txt ]; then pip3 install --no-cache-dir -r requirements.txt; fi"
        )

    if "node" in langs or "typescript" in langs:
        toolchain_blocks.append(
            "# Node.js LTS (via NodeSource)\n"
            "RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \\\n"
            "    && apt-get install -y nodejs"
        )
        install_blocks.append(
            "# Node — install deps\n"
            "RUN if [ -f package-lock.json ]; then npm ci; elif [ -f package.json ]; then npm install; fi"
        )

    if "go" in langs:
        toolchain_blocks.append(
            "# Go toolchain\n"
            "RUN curl -fsSL https://go.dev/dl/go1.22.0.linux-amd64.tar.gz \\\n"
            "    | tar -C /usr/local -xz\n"
            "ENV PATH=$PATH:/usr/local/go/bin"
        )
        install_blocks.append("# Go — download modules\n" "RUN if [ -f go.mod ]; then go mod download; fi")

    if "rust" in langs:
        toolchain_blocks.append(
            "# Rust toolchain (rustup)\n"
            "RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y\n"
            "ENV PATH=$PATH:/root/.cargo/bin"
        )
        install_blocks.append("# Rust — prefetch crate registry\n" "RUN if [ -f Cargo.toml ]; then cargo fetch; fi")

    if "ruby" in langs:
        apt_pkgs.update(["ruby", "ruby-dev", "libffi-dev", "libssl-dev"])
        install_blocks.append(
            "# Ruby — install gems\n"
            "RUN if [ -f Gemfile ]; then gem install bundler --no-document && bundle install; fi"
        )

    if "java" in langs or "kotlin" in langs:
        apt_pkgs.add("default-jdk")
        install_blocks.append(
            "# Java / Kotlin — resolve dependencies\n"
            "RUN if [ -f pom.xml ]; then mvn dependency:resolve -q; \\\n"
            "    elif [ -f build.gradle ]; then gradle dependencies -q; fi"
        )

    if "php" in langs:
        apt_pkgs.update(["php", "php-cli", "php-mbstring", "php-xml"])
        toolchain_blocks.append(
            "# PHP Composer\n"
            "RUN curl -sS https://getcomposer.org/installer \\\n"
            "    | php -- --install-dir=/usr/local/bin --filename=composer"
        )
        install_blocks.append(
            "# PHP — install composer packages\n"
            "RUN if [ -f composer.json ]; then composer install --no-dev --optimize-autoloader; fi"
        )

    if "dotnet" in langs:
        toolchain_blocks.append(
            "# .NET SDK\n"
            "RUN curl -fsSL https://dot.net/v1/dotnet-install.sh \\\n"
            "    | bash /dev/stdin --channel 8.0\n"
            "ENV PATH=$PATH:/root/.dotnet:/root/.dotnet/tools"
        )

    pkgs_str = " \\\n    ".join(sorted(apt_pkgs))
    parts = [
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
        for block in toolchain_blocks:
            parts.append(block)
            parts.append("")

    parts += [
        "# ── 3. Copy application source ──────────────────────────────────────",
        "COPY . .",
        "",
    ]

    if install_blocks:
        parts.append("# ── 4. Install language dependencies ────────────────────────────────")
        for block in install_blocks:
            parts.append(block)
            parts.append("")

    parts += [
        "# Override CMD in docker-compose or at 'docker run' time",
        'CMD ["bash"]',
        "",
    ]
    return "\n".join(parts)


def _generate_compose(image_name: str, langs: list[str], docker_push: bool = False) -> str:
    """Generate a docker-compose.yml for the project."""
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
