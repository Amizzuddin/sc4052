"""Template store for caching known-good CI/CD pipeline files.

Caches generated CI YAML, Dockerfile, and docker-compose.yml by
programming language + platform so that subsequent generations for
the same language can skip the LLM call and reuse a working template.

**Storage format** — CI YAML is stored as a *parsed* dict (via
``yaml.safe_load``) inside the JSON manifest.  All adaptations (repo
name, Python version, step injection/removal) happen at the dict /
list level — no regex string manipulation.  The dict is serialised
back to a YAML string only when the caller requests it via
:func:`get_template`.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

import yaml

logger = logging.getLogger(__name__)

# ── Template root ─────────────────────────────────────────────────────────────
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


# ── Types ─────────────────────────────────────────────────────────────────────
class TemplateEntry(TypedDict, total=False):
    """On-disk JSON structure for a cached template."""

    ci_yaml: dict  # parsed YAML dict (not a raw string)
    dockerfile: str
    docker_compose: str


# ── YAML helpers ──────────────────────────────────────────────────────────────


def _yaml_to_dict(yaml_str: str) -> dict | None:
    """Parse a YAML string into a dict.  Returns *None* on failure.

    Handles the PyYAML quirk where ``on:`` (a valid GitHub Actions key)
    is parsed as boolean ``True``.  We rename it back to the string
    ``"on"`` so the dict is JSON-serialisable.
    """
    try:
        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            return None
        # Fix boolean keys produced by safe_load (on→True, off→False)
        fixed: dict = {}
        for k, v in data.items():
            if k is True:
                fixed["on"] = v
            elif k is False:
                fixed["off"] = v
            else:
                fixed[k] = v
        return fixed
    except Exception:
        logger.warning("Failed to parse YAML string — skipping cache.")
        return None


def _dict_to_yaml(data: dict) -> str:
    """Serialise a dict back to a YAML string.

    Uses ``default_flow_style=False`` so the output is human-readable
    multi-line YAML.  Block scalars (multi-line ``run:`` values) are
    preserved via the custom *str representer* below.

    The ``"on"`` key is restored to bare ``on:`` (unquoted) after
    dumping so that GitHub Actions recognises the trigger block.
    """

    class _Dumper(yaml.SafeDumper):
        """Custom dumper that emits multi-line strings as literal blocks."""

    def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        # Quote YAML booleans so 'on'/'off'/'yes'/'no' stay as strings
        if data.lower() in ("on", "off", "yes", "no", "true", "false"):
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _Dumper.add_representer(str, _str_representer)

    out = yaml.dump(data, Dumper=_Dumper, default_flow_style=False, sort_keys=False, width=120)

    # Restore GitHub Actions trigger key: '"on":' → 'on:'
    out = re.sub(r'^"on":', "on:", out, flags=re.MULTILINE)

    return out


# ── Filesystem helpers ────────────────────────────────────────────────────────


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


def _read_manifest(key: str) -> dict[str, Any]:
    p = _manifest_path(key)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Corrupt template manifest %s — ignoring.", p)
        return {}


def _write_manifest(key: str, entry: dict[str, Any]) -> None:
    p = _manifest_path(key)
    p.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Template saved → %s", p)


# ── Dict-level adaptation helpers ─────────────────────────────────────────────


def _set_pipeline_name(ci: dict, repo_name: str) -> None:
    """Update the top-level ``name`` field."""
    if repo_name:
        ci["name"] = f"{repo_name} Pipeline"


def _set_python_version(ci: dict, version: str) -> None:
    """Walk all steps and update ``python-version`` in ``with:`` blocks."""
    for _job_name, job in (ci.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            with_block = step.get("with")
            if isinstance(with_block, dict) and "python-version" in with_block:
                with_block["python-version"] = version


def _set_node_version(ci: dict, version: str) -> None:
    """Walk all steps and update ``node-version`` in ``with:`` blocks."""
    for _job_name, job in (ci.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            with_block = step.get("with")
            if isinstance(with_block, dict) and "node-version" in with_block:
                with_block["node-version"] = version


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
    """
    key = _template_key(language, platform)
    entry = _read_manifest(key)
    if not entry or "ci_yaml" not in entry:
        return None
    # Backwards-compat: if ci_yaml is still a raw string (old format),
    # parse it now.
    if isinstance(entry["ci_yaml"], str):
        parsed = _yaml_to_dict(entry["ci_yaml"])
        if parsed is None:
            return None
        entry["ci_yaml"] = parsed
    logger.info("Template cache HIT for %s", key)
    return entry  # type: ignore[return-value]


def save_template(
    language: str | list[str],
    platform: str,
    *,
    ci_yaml: str | None = None,
    dockerfile: str | None = None,
    docker_compose: str | None = None,
) -> None:
    """Persist (or update) a template for the given language + platform.

    ``ci_yaml`` is accepted as a YAML **string** (the raw output from LLM
    or from disk) and stored as a *parsed dict* so that future reads can
    do key-level manipulation without regex.

    Only non-``None`` values are written; existing fields not supplied are
    retained so callers can update just the CI YAML (e.g. after
    self-healing) without clobbering the Dockerfile.
    """
    key = _template_key(language, platform)
    entry = _read_manifest(key)
    if ci_yaml is not None:
        parsed = _yaml_to_dict(ci_yaml)
        if parsed is not None:
            entry["ci_yaml"] = parsed
        else:
            # Fall back to storing the raw string if parsing fails.
            entry["ci_yaml"] = ci_yaml
    if dockerfile is not None:
        entry["dockerfile"] = dockerfile
    if docker_compose is not None:
        entry["docker_compose"] = docker_compose
    _write_manifest(key, entry)


def adapt_template(
    ci_dict: dict,
    scan: dict,
    repo_name: str | None = None,
) -> str:
    """Adapt a cached CI template dict to fit a new repository.

    All modifications happen on a **deep copy** of the dict — the caller's
    original is never mutated.  The result is serialised back to a YAML
    string ready for post-processing and writing to disk.

    Adaptations applied (all at key/value level):
    * ``name`` → ``<repo_name> Pipeline``
    * ``python-version`` in ``with:`` blocks → scan-detected version
    * ``node-version`` in ``with:`` blocks → scan-detected version
    """
    ci = copy.deepcopy(ci_dict)

    # ── repo name ─────────────────────────────────────────────────────────
    _set_pipeline_name(ci, repo_name or "")

    # ── Python version ────────────────────────────────────────────────────
    scan_py = scan.get("python_version")
    if scan_py:
        _set_python_version(ci, scan_py)

    # ── Node version ──────────────────────────────────────────────────────
    scan_node = scan.get("node_version")
    if scan_node:
        _set_node_version(ci, scan_node)

    return _dict_to_yaml(ci)


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
