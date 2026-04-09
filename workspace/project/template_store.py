"""Template store for caching known-good CI/CD pipeline files.

Caches generated CI YAML, Dockerfile, and docker-compose.yml by
programming language + platform so that subsequent generations for
the same language can skip the LLM call and reuse a working template.

Templates are stored on disk under ``TEMPLATE_DIR`` as JSON manifests
keyed by a normalised ``<lang>__<platform>`` identifier.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

# ── Template root ─────────────────────────────────────────────────────────────
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


# ── Types ─────────────────────────────────────────────────────────────────────
class TemplateEntry(TypedDict, total=False):
    ci_yaml: str
    dockerfile: str
    docker_compose: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _template_key(language: str | list[str], platform: str) -> str:
    """Return a normalised key for the language(s) + platform combination."""
    if isinstance(language, list):
        langs = sorted({l.lower().strip() for l in language if l})
    else:
        langs = [language.lower().strip()] if language else ["unknown"]
    return "__".join(langs) + f"__{platform}"


def _manifest_path(key: str) -> Path:
    """Return the path to the JSON manifest for *key*."""
    safe = re.sub(r"[^\w]", "_", key)
    return TEMPLATE_DIR / f"{safe}.json"


def _read_manifest(key: str) -> TemplateEntry:
    p = _manifest_path(key)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Corrupt template manifest %s — ignoring.", p)
        return {}


def _write_manifest(key: str, entry: TemplateEntry) -> None:
    p = _manifest_path(key)
    p.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    logger.info("Template saved → %s", p)


# ── Public API ────────────────────────────────────────────────────────────────


def get_template(
    language: str | list[str],
    platform: str,
    *,
    docker_push: bool = False,
) -> TemplateEntry | None:
    """Look up a cached template for the given language + platform.

    Returns ``None`` if no template is cached.  The caller should then
    fall back to LLM generation and call :func:`save_template` with the
    result.

    ``docker_push`` is intentionally **not** part of the cache key — the
    Docker login & push block is always present in the template
    (guarded by a ``$DOCKER_TOKEN`` shell check) so it works regardless
    of whether the user enables push.
    """
    key = _template_key(language, platform)
    entry = _read_manifest(key)
    if not entry or "ci_yaml" not in entry:
        return None
    logger.info("Template cache HIT for %s", key)
    return entry


def save_template(
    language: str | list[str],
    platform: str,
    *,
    ci_yaml: str | None = None,
    dockerfile: str | None = None,
    docker_compose: str | None = None,
) -> None:
    """Persist (or update) a template for the given language + platform.

    Only non-``None`` values are written; existing fields that are not
    supplied are retained so callers can update just the CI YAML (e.g.
    after self-healing) without clobbering the Dockerfile.
    """
    key = _template_key(language, platform)
    entry = _read_manifest(key)
    if ci_yaml is not None:
        entry["ci_yaml"] = ci_yaml
    if dockerfile is not None:
        entry["dockerfile"] = dockerfile
    if docker_compose is not None:
        entry["docker_compose"] = docker_compose
    _write_manifest(key, entry)


def adapt_template(
    template_yaml: str,
    scan: dict,
    repo_name: str | None = None,
) -> str:
    """Lightly adapt a cached CI YAML template to fit a new repository.

    Substitutions applied:
    * Pipeline ``name:`` line → ``<repo_name> Pipeline``
    * Python version → version from scan (if present)

    The goal is to make the cached template fit the new project without
    an LLM call for the common case.  If deeper customisation is needed
    the caller should still invoke the LLM.
    """
    yaml_out = template_yaml

    # ── repo name in the `name:` field ────────────────────────────────────
    if repo_name:
        yaml_out = re.sub(
            r"^name:\s*.+$",
            f"name: {repo_name} Pipeline",
            yaml_out,
            count=1,
            flags=re.MULTILINE,
        )

    # ── Python version ────────────────────────────────────────────────────
    scan_py = scan.get("python_version")
    if scan_py:
        yaml_out = re.sub(
            r"(python-version:\s*['\"]?)\d+\.\d+(['\"]?)",
            rf"\g<1>{scan_py}\g<2>",
            yaml_out,
        )

    return yaml_out


def list_templates() -> list[dict[str, object]]:
    """Return a summary of all cached templates (for debugging / UI)."""
    results: list[dict[str, object]] = []
    if not TEMPLATE_DIR.exists():
        return results
    for p in sorted(TEMPLATE_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append(
                {
                    "key": p.stem,
                    "has_ci": "ci_yaml" in data,
                    "has_dockerfile": "dockerfile" in data,
                    "has_compose": "docker_compose" in data,
                }
            )
        except Exception:
            pass
    return results
