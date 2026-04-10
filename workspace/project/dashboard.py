################################################################################
#  Filename:      project/dashboard.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 12:12:13 am                        #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Friday April 10th 2026 6:14:18 am                            #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
dashboard.py
------------
Dash web UI for cicd-gen — URL-based workflow.

  1. User provides a remote repository URL (HTTPS).
  2. App clones it to a temporary directory and scans the tech stack.
  3. User configures the pipeline (language, docker, platform, branch name).
  4. App generates CI/CD YAML, commits it on a new feature branch, and
     optionally pushes it back — so the default branch stays untouched.

Authentication model (no secrets stored on disk or in browser storage):
  • HTTPS public         → anonymous clone; no credentials needed.
  • HTTPS private        → masked token field (type="password", persistence=False);
                           token is passed as a callback State value and embedded
                           only in the git URL for the duration of the operation.

Run with:
    python dashboard.py
Then open http://localhost:8050
"""

import os
import re
import sys
import tempfile
import threading
import uuid
from pathlib import Path, PurePosixPath

# ── Make sure sibling modules are importable when run directly ────────────────
sys.path.insert(0, str(Path(__file__).parent))

import dash
import dash_bootstrap_components as dbc
import git
from ai_handler import (
    _ci_cancel_flags,
    _ci_watch_lock,
    _ci_watch_results,
    _parse_github_repo,
    _sanitize_expressions,
    _sanitize_runner,
    _watch_ci_and_heal,
    check_repo_secrets,
    snapshot_run_ids,
    validate_github_pat,
)
from dash import Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from docker_handler import DEFAULT_DOCKER_BASE_IMAGE
from dockerfile_templates import build_compose, build_dockerfile
from generator import SUPPORTED_PLATFORMS, SUPPORTED_PROVIDERS, generate_pipeline
from git_handler import (
    _cleanup,
    _commit_on_branch,
    _inject_token,
    _push_branch,
    _safe_url,
)
from scanner import scan_repo
from writer import PLATFORM_OUTPUT_PATHS, write_config

# ── Handler imports ────────────────────────────────────────────────────────────────


LANGUAGES = [
    "python",
    "typescript",
    "node",
    "go",
    "java",
    "rust",
    "ruby",
    "php",
    "bash",
    "kotlin",
    "dotnet",
]

# ── Provider metadata (used in the UI) ───────────────────────────────────────

PROVIDER_INFO = {
    "gemini": {
        "label": "Google Gemini Flash  — FREE (1 500 req/day)",
        "placeholder": "Gemini API key  (AIza…)",
        "get_key_url": "https://aistudio.google.com/app/apikey",
        "get_key_label": "Google AI Studio → aistudio.google.com",
        "color": "success",
        "steps": [
            ("Open ", "Google AI Studio", "https://aistudio.google.com/app/apikey"),
            ("Sign in with your Google account.",),
            ('Click "Get API key" then "Create API key in new project".',),
            ("Copy the key (starts with ", "AIza…", None, ") and paste it in the field above."),
        ],
    },
    "groq": {
        "label": "Groq  (Llama 3.3)  — FREE (14 400 req/day)",
        "placeholder": "Groq API key  (gsk_…)",
        "get_key_url": "https://console.groq.com",
        "get_key_label": "Groq Console → console.groq.com",
        "color": "success",
        "steps": [
            ("Open ", "Groq Console", "https://console.groq.com"),
            ("Create a free account or sign in.",),
            ('Navigate to "API Keys" in the left sidebar and click "Create API Key".',),
            ("Copy the key (starts with ", "gsk_…", None, ") and paste it in the field above."),
        ],
    },
    "anthropic": {
        "label": "Anthropic Claude  — paid plan required",
        "placeholder": "Anthropic API key  (sk-ant-…)",
        "get_key_url": "https://console.anthropic.com/settings/keys",
        "get_key_label": "Anthropic Console → console.anthropic.com",
        "color": "warning",
        "steps": [
            ("Open ", "Anthropic Console", "https://console.anthropic.com/settings/keys"),
            ("Sign in and ensure your account has an active paid plan.",),
            ('Click "Create Key", give it a name, and set an expiry if desired.',),
            ("Copy the key (starts with ", "sk-ant-…", None, ") and paste it in the field above."),
        ],
    },
}

# Step-by-step instructions shown in the auth accordion when a PAT is selected
GITHUB_PAT_STEPS = [
    ("Open ", "GitHub → Settings → Developer settings → Personal access tokens", "https://github.com/settings/tokens"),
    ('Click "Generate new token" → choose "Fine-grained token" for scoped access.',),
    ('Set the expiration, select the target repository under "Repository access".',),
    ('Under "Repository permissions", set "Contents" to "Read and write".',),
    ('Click "Generate token" and copy it — GitHub shows it only once.',),
]

DEFAULT_PROVIDER = "gemini"
DEFAULT_BRANCH = "cicd-gen/setup"

PLATFORM_LABELS = {
    "github-actions": "GitHub Actions",
    "gitlab-ci": "GitLab CI",
    "jenkins": "Jenkins",
}

# ── App setup ─────────────────────────────────────────────────────────────────


app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    title="cicd-gen",
)
app.config.suppress_callback_exceptions = True

# ── Layout helpers ────────────────────────────────────────────────────────────


def _section(title: str, children, **kwargs) -> dbc.Card:
    return dbc.Card(
        [
            dbc.CardHeader(html.H5(title, className="mb-0")),
            dbc.CardBody(children),
        ],
        className="mb-3 shadow-sm",
        **kwargs,
    )


def _alert(message: str, color: str = "info") -> dbc.Alert:
    return dbc.Alert(message, color=color, dismissable=True, className="mb-0")


# ── File-browser helpers ─────────────────────────────────────────────────────────

_EXT_LANG: dict[str, str] = {
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
    ".txt": "text",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".json": "json",
    ".sh": "bash",
    ".toml": "toml",
    ".xml": "xml",
}
_NAME_LANG: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Jenkinsfile": "groovy",
    ".env": "bash",
}


def _render_file_content(rel_path: str, content: str):
    """Return a Markdown code block with appropriate syntax highlighting."""
    name = PurePosixPath(rel_path).name
    ext = PurePosixPath(rel_path).suffix.lower()
    lang = _NAME_LANG.get(name) or _EXT_LANG.get(ext, "text")
    return dcc.Markdown(
        f"```{lang}\n{content}\n```",
        style={"margin": 0, "fontSize": "0.82rem"},
    )


def _files_to_tree_options(files: dict) -> list[dict]:
    """Convert a {rel_path: content} mapping to dcc.RadioItems options styled as a file tree."""
    paths = sorted(files.keys())
    options: list[dict] = []
    seen_dirs: set[str] = set()
    for path_str in paths:
        parts = path_str.replace("\\", "/").split("/")
        for depth in range(len(parts) - 1):
            dir_key = "/".join(parts[: depth + 1]) + "/"
            if dir_key not in seen_dirs:
                seen_dirs.add(dir_key)
                prefix = "\u00a0" * (depth * 4)
                options.append(
                    {
                        "label": f"{prefix}\U0001f4c2 {parts[depth]}/",
                        "value": f"__dir__{dir_key}",
                        "disabled": True,
                    }
                )
        depth = len(parts) - 1
        prefix = "\u00a0" * (depth * 4)
        options.append({"label": f"{prefix}\U0001f4c4 {parts[-1]}", "value": path_str})
    return options


def _build_files_state(
    clone_path: str,
    platform: str,
    yaml_content: str,
    dockerfile_content: str | None,
    compose_content: str | None,
    extra_generated: dict[str, str] | None = None,
) -> dict:
    """Collect all generated file paths + contents into a single dict for the file browser."""
    files: dict[str, str] = {}
    ci_rel = PLATFORM_OUTPUT_PATHS.get(platform, ".github/workflows/ci.yml")
    files[ci_rel] = yaml_content
    readme_path = Path(clone_path) / ".github" / "README.md"
    if readme_path.exists():
        try:
            files[".github/README.md"] = readme_path.read_text(encoding="utf-8")
        except Exception:
            pass
    if dockerfile_content:
        files["Dockerfile"] = dockerfile_content
    if compose_content:
        files["docker-compose.yml"] = compose_content
    if extra_generated:
        files.update(extra_generated)
    return {"files": files, "clone_path": clone_path, "default_file": ci_rel}


# ── Layout ────────────────────────────────────────────────────────────────────

app.layout = dbc.Container(
    fluid=False,
    children=[
        # ── Header ────────────────────────────────────────────────────────────
        dbc.Row(
            dbc.Col(
                html.Div(
                    [
                        html.H2("cicd-gen", className="mb-1"),
                        html.P("AI-powered CI/CD pipeline generator", className="text-muted"),
                    ],
                    className="py-4",
                )
            )
        ),
        # ── Repository & auth ─────────────────────────────────────────────────
        _section(
            "Repository",
            [
                # URL
                dbc.Row(
                    dbc.Col(
                        dbc.Input(
                            id="repo-url-input",
                            placeholder=(
                                "Repository URL  e.g.  git@github.com:org/repo.git" "  or  https://github.com/org/repo"
                            ),
                            type="text",
                            debounce=False,
                            persistence=True,
                            persistence_type="session",
                        ),
                        className="mb-3",
                    )
                ),
                # Branch (optional) + Scan button
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Input(
                                    id="clone-branch-input",
                                    placeholder="Branch to scan  (leave blank for default)",
                                    type="text",
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                dbc.FormText("Leave blank to use the repository's default branch."),
                            ],
                            md=9,
                        ),
                        dbc.Col(
                            dbc.Button("Scan", id="scan-btn", color="primary", className="w-100", n_clicks=0),
                            md=3,
                            className="d-flex align-items-start",
                        ),
                    ],
                    className="mb-3",
                ),
                # ── GitHub PAT (always visible) ──────────────────────────
                html.Hr(className="my-2"),
                html.H6("🔑 GitHub Authentication", className="fw-semibold mb-2"),
                dbc.Row(
                    dbc.Col(
                        [
                            dbc.Label("Personal Access Token (PAT)"),
                            dbc.Input(
                                id="token-input",
                                placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                                type="password",
                                autocomplete="off",
                            ),
                            dbc.FormText(
                                "Required for clone, push, and CI watch. "
                                "Never stored — exists only in this tab's memory."
                            ),
                            dbc.Accordion(
                                dbc.AccordionItem(
                                    [
                                        html.Ol(
                                            [
                                                html.Li(
                                                    (
                                                        [
                                                            html.Span(step[0]),
                                                            (
                                                                html.A(step[1], href=step[2], target="_blank")
                                                                if len(step) >= 3 and step[2]
                                                                else html.Span(step[1] if len(step) > 1 else "")
                                                            ),
                                                        ]
                                                        if len(step) >= 2
                                                        else [html.Span(step[0])]
                                                    ),
                                                )
                                                for step in GITHUB_PAT_STEPS
                                            ],
                                            className="mb-0 ps-3",
                                        ),
                                        dbc.Alert(
                                            [
                                                html.Strong("Scopes needed: "),
                                                "repo  (for classic tokens)  or  ",
                                                html.Strong("Contents: Read & Write"),
                                                "  (for fine-grained tokens).",
                                            ],
                                            color="warning",
                                            className="mt-2 mb-0 py-2",
                                        ),
                                    ],
                                    title="How to create a GitHub Personal Access Token (PAT)",
                                ),
                                start_collapsed=True,
                                className="mt-2",
                            ),
                        ],
                        md=12,
                        className="mb-3",
                    )
                ),
                # Hidden elements to keep Dash happy (callbacks reference these IDs)
                html.Div(id="auth-type", style={"display": "none"}, children="https-token"),
                html.Div(id="token-row", style={"display": "none"}),
            ],
        ),
        # ── Scan feedback ──────────────────────────────────────────────────────
        html.Div(id="scan-status"),
        # ── Scan result summary (hidden until scan succeeds) ───────────────────
        html.Div(id="scan-summary", style={"display": "none"}),
        # ── Pipeline configuration (hidden until scan succeeds) ────────────────
        html.Div(
            id="config-panel",
            children=_section(
                "Pipeline Configuration",
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Programming Language(s)"),
                                    dbc.ButtonGroup(
                                        [
                                            dbc.Button(
                                                "Select All",
                                                id="lang-select-all",
                                                size="sm",
                                                color="outline-secondary",
                                                n_clicks=0,
                                            ),
                                            dbc.Button(
                                                "Deselect All",
                                                id="lang-deselect-all",
                                                size="sm",
                                                color="outline-secondary",
                                                n_clicks=0,
                                            ),
                                        ],
                                        className="mb-2",
                                    ),
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                dbc.Checklist(
                                                    id="language-checklist",
                                                    options=[
                                                        {"label": l.capitalize(), "value": l}
                                                        for l in LANGUAGES[: len(LANGUAGES) // 2 + len(LANGUAGES) % 2]
                                                    ],
                                                    value=[],
                                                    persistence=True,
                                                    persistence_type="session",
                                                ),
                                                width=6,
                                            ),
                                            dbc.Col(
                                                dbc.Checklist(
                                                    id="language-checklist-2",
                                                    options=[
                                                        {"label": l.capitalize(), "value": l}
                                                        for l in LANGUAGES[len(LANGUAGES) // 2 + len(LANGUAGES) % 2 :]
                                                    ],
                                                    value=[],
                                                    persistence=True,
                                                    persistence_type="session",
                                                ),
                                                width=6,
                                            ),
                                        ],
                                        className="mb-2",
                                    ),
                                    dbc.Input(
                                        id="language-custom",
                                        placeholder="Other languages, comma-separated  e.g. bash, kotlin",
                                        type="text",
                                        size="sm",
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                    dbc.FormText("Tick auto-detected language(s) above, " "or type custom ones below."),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("CI/CD Platform"),
                                    dcc.Dropdown(
                                        id="platform-dropdown",
                                        options=[
                                            {"label": PLATFORM_LABELS[p], "value": p} for p in SUPPORTED_PLATFORMS
                                        ],
                                        value="github-actions",
                                        clearable=False,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                        ]
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Docker"),
                                    dbc.Checklist(
                                        id="docker-toggle",
                                        options=[
                                            {
                                                "label": " Generate a Dockerfile + CI build step",
                                                "value": "docker",
                                            }
                                        ],
                                        value=[],
                                        switch=True,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                    # Docker options — shown only when Docker is enabled
                                    html.Div(
                                        id="docker-options-row",
                                        style={"display": "none"},
                                        children=[
                                            dbc.Label("Base Image", className="mt-2 small fw-semibold"),
                                            dbc.Input(
                                                id="docker-base-image",
                                                placeholder=f"e.g. {DEFAULT_DOCKER_BASE_IMAGE}",
                                                value=DEFAULT_DOCKER_BASE_IMAGE,
                                                type="text",
                                                size="sm",
                                                className="mb-1",
                                                persistence=True,
                                                persistence_type="session",
                                            ),
                                            dbc.FormText(
                                                "A single multi-language image is generated from this base. "
                                                "Use a pinned tag (e.g. ubuntu:22.04) for reproducibility.",
                                                className="mb-2",
                                            ),
                                            dbc.Checklist(
                                                id="docker-compose-toggle",
                                                options=[
                                                    {"label": " Also generate docker-compose.yml", "value": "compose"}
                                                ],
                                                value=[],
                                                switch=True,
                                                persistence=True,
                                                persistence_type="session",
                                            ),
                                            # ── Push toggle ─────────────────────────────────
                                            dbc.Checklist(
                                                id="docker-push-toggle",
                                                options=[
                                                    {
                                                        "label": " Push image to Docker Hub",
                                                        "value": "push",
                                                    }
                                                ],
                                                value=[],
                                                switch=True,
                                                className="mt-2",
                                                persistence=True,
                                                persistence_type="session",
                                            ),
                                            # Secrets notice — only visible when push toggle is on
                                            html.Div(
                                                id="docker-push-notice-row",
                                                style={"display": "none"},
                                                children=[
                                                    dbc.Alert(
                                                        [
                                                            html.Strong("🔐 GitHub Secrets required for Docker push"),
                                                            html.Hr(className="my-2"),
                                                            html.P(
                                                                "The push step runs only when both secrets exist on your "
                                                                "repository — they are never written to the YAML file.",
                                                                className="mb-2 small",
                                                            ),
                                                            html.Strong(
                                                                "Add two secrets to your repo:", className="small"
                                                            ),
                                                            html.Ol(
                                                                [
                                                                    html.Li(
                                                                        [
                                                                            "Repo → ",
                                                                            html.Strong("Settings"),
                                                                            " → ",
                                                                            html.Strong("Secrets and variables"),
                                                                            " → ",
                                                                            html.Strong("Actions"),
                                                                            " → ",
                                                                            html.Strong("New repository secret"),
                                                                        ]
                                                                    ),
                                                                    html.Li(
                                                                        [
                                                                            html.Code("DOCKER_USERNAME"),
                                                                            " — your Docker Hub username",
                                                                        ]
                                                                    ),
                                                                    html.Li(
                                                                        [
                                                                            html.Code("DOCKER_TOKEN"),
                                                                            " — a Docker Hub ",
                                                                            html.A(
                                                                                "Access Token",
                                                                                href="https://hub.docker.com/settings/security",
                                                                                target="_blank",
                                                                            ),
                                                                            " (not your password)",
                                                                        ]
                                                                    ),
                                                                ],
                                                                className="mb-0 ps-3 small",
                                                            ),
                                                            html.Hr(className="my-2"),
                                                            # ── Live secret status ───────────────────────
                                                            html.Div(
                                                                id="secrets-check-result",
                                                                children=[
                                                                    html.Span(
                                                                        [
                                                                            html.Code("DOCKER_USERNAME"),
                                                                            html.Span(
                                                                                " ⏳ checking…",
                                                                                className="text-muted ms-1 small",
                                                                            ),
                                                                        ],
                                                                        className="me-4",
                                                                    ),
                                                                    html.Span(
                                                                        [
                                                                            html.Code("DOCKER_TOKEN"),
                                                                            html.Span(
                                                                                " ⏳ checking…",
                                                                                className="text-muted ms-1 small",
                                                                            ),
                                                                        ],
                                                                    ),
                                                                ],
                                                                className="mt-2",
                                                            ),
                                                        ],
                                                        color="info",
                                                        className="mt-2 mb-0",
                                                    )
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Feature Branch Name"),
                                    dbc.Input(
                                        id="branch-input",
                                        value=DEFAULT_BRANCH,
                                        type="text",
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                    dbc.FormText(
                                        "Pipeline is committed to this new branch — "
                                        "your default branch is never modified."
                                    ),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                        ]
                    ),
                    # ── AI Provider (inside config panel) ─────────────────────
                    html.Hr(className="my-3"),
                    html.H6("AI Provider", className="fw-semibold mb-2"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Provider"),
                                    dcc.Dropdown(
                                        id="llm-provider-dropdown",
                                        options=[
                                            {"label": PROVIDER_INFO[p]["label"], "value": p}
                                            for p in SUPPORTED_PROVIDERS
                                        ],
                                        value=DEFAULT_PROVIDER,
                                        clearable=False,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                md=5,
                                className="mb-3",
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("API Key"),
                                    dbc.Input(
                                        id="api-key-input",
                                        placeholder=PROVIDER_INFO[DEFAULT_PROVIDER]["placeholder"],
                                        type="password",
                                        autocomplete="off",
                                    ),
                                ],
                                md=7,
                                className="mb-3",
                            ),
                        ]
                    ),
                    html.Div(id="provider-info"),
                    html.Hr(className="my-3"),
                    dbc.Row(
                        dbc.Col(
                            [
                                dbc.Label("Additional Requirements  (optional)"),
                                dbc.Textarea(
                                    id="extra-requirements",
                                    placeholder="e.g. deploy to AWS Lambda after tests pass, notify Slack on failure",
                                    rows=3,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                            ],
                            className="mb-3",
                        )
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Button(
                                    "Generate Pipeline",
                                    id="generate-btn",
                                    color="success",
                                    size="lg",
                                    n_clicks=0,
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                dbc.Checklist(
                                    id="push-toggle",
                                    options=[
                                        {
                                            "label": " Push feature branch to remote after generating",
                                            "value": "push",
                                        }
                                    ],
                                    value=["push"],
                                    switch=True,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                className="d-flex align-items-center",
                            ),
                            dbc.Col(
                                [
                                    dbc.Checklist(
                                        id="watch-ci-toggle",
                                        options=[
                                            {
                                                "label": " Watch CI & auto-fix failures",
                                                "value": "watch",
                                            }
                                        ],
                                        value=["watch"],
                                        switch=True,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                    dbc.FormText(
                                        "GitHub Actions only. Requires a token. "
                                        "Monitors the run and pushes fixes (up to 10 attempts)."
                                    ),
                                ],
                                className="d-flex flex-column justify-content-center",
                            ),
                        ],
                        align="center",
                    ),
                ],
            ),
            style={"display": "none"},
        ),
        # ── Generation result ──────────────────────────────────────────────────
        dcc.Loading(
            id="gen-loading",
            type="circle",
            color="#2c7a2c",
            style={"marginTop": "8px"},
            children=[
                html.Div(id="generate-status"),
                html.Div(id="yaml-preview"),
            ],
        ),
        # CI watch progress card (polled every 8 s)
        html.Div(id="ci-watch-status"),
        # Cancel button — statically in DOM, shown/hidden by callbacks
        html.Div(
            dbc.Button(
                "🚫 Cancel Watch",
                id="cancel-watch-btn",
                size="sm",
                color="secondary",
                outline=True,
                n_clicks=0,
            ),
            id="cancel-btn-row",
            style={"display": "none"},
        ),
        # ── File browser (shown after generation) ─────────────────────────────
        html.Div(
            id="file-browser",
            style={"display": "none"},
            children=[
                html.Hr(className="my-3"),
                html.H6("📂 Generated Files", className="fw-semibold mb-2"),
                dbc.Row(
                    [
                        dbc.Col(
                            html.Div(
                                dcc.RadioItems(
                                    id="file-tree-radio",
                                    options=[],
                                    value=None,
                                    inputStyle={"display": "none"},
                                    labelStyle={
                                        "display": "block",
                                        "padding": "3px 8px",
                                        "cursor": "pointer",
                                        "fontSize": "0.84rem",
                                        "fontFamily": "monospace",
                                        "borderRadius": "4px",
                                    },
                                ),
                                className="border rounded p-2 bg-light",
                                style={"minHeight": "200px"},
                            ),
                            md=4,
                        ),
                        dbc.Col(
                            html.Div(
                                id="file-viewer-content",
                                style={"maxHeight": "520px", "overflowY": "auto"},
                            ),
                            md=8,
                        ),
                    ],
                    className="g-2",
                ),
            ],
        ),
        # ── Hidden stores (memory-only — cleared on page refresh) ──────────────
        # Holds: generated files {files: {rel_path: content}, clone_path, default_file}
        dcc.Store(id="generated-files-state", storage_type="memory"),
        # Holds: {scan, clone_path, url, is_empty, auth_type}
        dcc.Store(id="scan-state", storage_type="memory"),
        # Holds: {watch_id} for CI polling
        dcc.Store(id="ci-watch-state", storage_type="memory"),
        # Holds full CI log messages for download
        dcc.Store(id="ci-log-store", storage_type="memory"),
        # Download component for CI logs
        dcc.Download(id="download-log"),
        # Polls every 8 s while CI watch is active
        dcc.Interval(id="ci-watch-interval", interval=8_000, n_intervals=0, disabled=True),
        # Polls every 10 s while Docker push toggle is on to check GitHub secrets
        dcc.Interval(id="secrets-poll-interval", interval=10_000, n_intervals=0, disabled=True),
    ],
    className="mt-3",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────


@app.callback(
    Output("language-checklist", "value"),
    Output("language-checklist-2", "value"),
    Input("lang-select-all", "n_clicks"),
    Input("lang-deselect-all", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_all_languages(_select, _deselect):
    """Select or deselect all language checkboxes."""
    from dash import ctx

    half = len(LANGUAGES) // 2 + len(LANGUAGES) % 2
    if ctx.triggered_id == "lang-select-all":
        return LANGUAGES[:half], LANGUAGES[half:]
    return [], []


@app.callback(
    Output("provider-info", "children"),
    Output("api-key-input", "placeholder"),
    Input("llm-provider-dropdown", "value"),
)
def update_provider_info(provider):
    """Update the help text and key placeholder when the provider changes."""
    info = PROVIDER_INFO.get(provider or DEFAULT_PROVIDER, PROVIDER_INFO[DEFAULT_PROVIDER])
    badge_color = info["color"]
    badge_text = "Free" if badge_color == "success" else "Paid"

    # Build ordered list of steps, supporting (text,) / (prefix, link_text, url) / (prefix, bold, None, suffix)
    def _render_step(step):
        if len(step) == 1:
            return html.Li(step[0])
        if len(step) == 3:
            prefix, link_text, url = step
            return html.Li([html.Span(prefix), html.A(link_text, href=url, target="_blank")])
        if len(step) == 4:
            prefix, bold_text, _unused, suffix = step
            return html.Li([html.Span(prefix), html.Strong(bold_text), html.Span(suffix)])
        return html.Li(str(step))

    steps_list = html.Ol(
        [_render_step(s) for s in info.get("steps", [])],
        className="mb-0 ps-3",
    )

    children = [
        dbc.Alert(
            [
                dbc.Badge(badge_text, color=badge_color, className="me-2"),
                html.A(info["get_key_label"], href=info["get_key_url"], target="_blank"),
                html.Span("  —  key is ", className="text-muted"),
                html.Strong("never"),
                html.Span(" stored on disk or in the browser.", className="text-muted"),
            ],
            color="light",
            className="py-2 mb-1",
        ),
        dbc.Accordion(
            dbc.AccordionItem(
                steps_list,
                title=f"How to get a {info['get_key_label'].split('→')[0].strip()} API key",
            ),
            start_collapsed=True,
            className="mb-0",
        ),
    ]
    return children, info["placeholder"]


@app.callback(
    Output("docker-options-row", "style"),
    Input("docker-toggle", "value"),
)
def toggle_docker_options(docker_values):
    """Show Docker base-image and compose options only when Docker is enabled."""
    return {"display": "block"} if "docker" in (docker_values or []) else {"display": "none"}


@app.callback(
    Output("docker-push-notice-row", "style"),
    Output("secrets-poll-interval", "disabled"),
    Input("docker-push-toggle", "value"),
)
def toggle_docker_push_notice(push_values):
    """Show secrets panel and start/stop polling when the Docker push toggle changes."""
    enabled = "push" in (push_values or [])
    style = {"display": "block"} if enabled else {"display": "none"}
    return style, not enabled


@app.callback(
    Output("generate-btn", "disabled"),
    Output("generate-btn", "title"),
    Input("scan-state", "data"),
    Input("api-key-input", "value"),
    Input("token-input", "value"),
    Input("docker-push-toggle", "value"),
    Input("secrets-check-result", "children"),
)
def toggle_generate_button(scan_state, api_key, token, push_values, secrets_children):
    """Disable the Generate button until the minimum requirements are met."""
    reasons: list[str] = []
    if not scan_state:
        reasons.append("scan the repository first")
    if not (api_key or "").strip():
        # Check env fallback
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY") or ""
        if not env_key:
            reasons.append("enter an AI provider API key")
    if not (token or "").strip():
        reasons.append("enter a GitHub personal access token")
    # When Docker push is enabled, ensure both secrets are present (look for ❌ in badges)
    if "push" in (push_values or []) and secrets_children:
        try:
            rendered = str(secrets_children)
            if "❌" in rendered:
                reasons.append("add missing Docker Hub secrets (DOCKER_USERNAME / DOCKER_TOKEN)")
        except Exception:
            pass
    if reasons:
        return True, "To generate: " + ", ".join(reasons)
    return False, ""


@app.callback(
    Output("secrets-check-result", "children"),
    Input("secrets-poll-interval", "n_intervals"),
    State("docker-push-toggle", "value"),
    State("scan-state", "data"),
    State("token-input", "value"),
    prevent_initial_call=True,
)
def check_docker_secrets(n_intervals, push_values, scan_state, token):
    """Poll GitHub Secrets API and update per-secret live status badges."""
    REQUIRED = ["DOCKER_USERNAME", "DOCKER_TOKEN"]

    # Guard: only run when the push toggle is active
    if "push" not in (push_values or []):
        raise PreventUpdate

    def _status_row(name: str, status: str, note: str = "") -> html.Span:
        """Return a per-secret inline badge."""
        icons = {"ok": " ✅", "missing": " ❌", "checking": " ⏳ checking…", "error": " ⚠️"}
        colours = {"ok": "text-success", "missing": "text-danger", "checking": "text-muted", "error": "text-warning"}
        icon_text = icons.get(status, "")
        colour = colours.get(status, "text-muted")
        return html.Span(
            [
                html.Code(name),
                html.Span(icon_text + (f" {note}" if note else ""), className=f"{colour} ms-1 small"),
            ],
            className="me-4",
        )

    repo_url = (scan_state or {}).get("url", "")
    ghr = _parse_github_repo(repo_url) if repo_url else None

    if not ghr:
        return [_status_row(n, "error", "(GitHub repo required)") for n in REQUIRED]

    if not (token or "").strip():
        return [_status_row(n, "error", "(token required)") for n in REQUIRED]

    owner, repo_name = ghr
    result = check_repo_secrets(owner, repo_name, token.strip(), REQUIRED)

    if not result["can_check"] or result["error"]:
        note = result.get("error") or "token / permission error"
        # Truncate long error messages for the badge
        note = note[:60] + "…" if len(note) > 60 else note
        return [_status_row(n, "error", f"({note})") for n in REQUIRED]

    return [_status_row(n, "ok" if n in result["found"] else "missing") for n in REQUIRED]


@app.callback(
    Output("scan-status", "children"),
    Output("scan-summary", "children"),
    Output("scan-summary", "style"),
    Output("config-panel", "style"),
    Output("scan-state", "data"),
    Output("language-checklist", "value", allow_duplicate=True),
    Output("language-checklist-2", "value", allow_duplicate=True),
    Output("api-key-input", "value"),
    Output("generate-status", "children", allow_duplicate=True),
    Output("yaml-preview", "children", allow_duplicate=True),
    Output("file-browser", "style", allow_duplicate=True),
    Input("scan-btn", "n_clicks"),
    State("repo-url-input", "value"),
    State("clone-branch-input", "value"),
    State("token-input", "value"),
    State("scan-state", "data"),
    prevent_initial_call=True,
)
def scan_repository(n_clicks, repo_url, clone_branch, token, prev_state):
    """Clone the remote repo and scan its tech stack."""
    hidden = {"display": "none"}
    visible = {"display": "block"}

    # Values to clear on every scan attempt
    _clear = ("",)  # api-key-input
    _reset_gen = (None, None, hidden)  # generate-status, yaml-preview, file-browser

    def _err(msg_or_component):
        """Return an error tuple (11 values)."""
        alert = msg_or_component if not isinstance(msg_or_component, str) else _alert(msg_or_component, "danger")
        return (alert, None, hidden, hidden, None, no_update, no_update, *_clear, *_reset_gen)

    if not repo_url or not repo_url.strip():
        return _err(_alert("Please enter a repository URL.", "warning"))

    repo_url = repo_url.strip()
    clone_branch = (clone_branch or "").strip() or None

    if not (repo_url.startswith("http://") or repo_url.startswith("https://")):
        return _err(_alert("URL must start with https:// or http://", "warning"))

    # ── Clean up previous temp clone ─────────────────────────────────────────
    if prev_state and prev_state.get("clone_path"):
        _cleanup(prev_state["clone_path"])

    # ── Validate PAT ──────────────────────────────────────────────────────────
    if not token:
        return _err(
            _alert(
                "A personal access token (PAT) is required. Enter it in the Pipeline Configuration panel.", "warning"
            )
        )
    pat_result = validate_github_pat(token)
    if not pat_result["valid"]:
        return _err(
            dbc.Alert(
                [
                    html.Strong("Invalid GitHub PAT: "),
                    html.Span(pat_result["error"]),
                    html.Br(),
                    html.Small(
                        "Please check that the token is correct and has not expired.",
                        className="text-muted",
                    ),
                ],
                color="danger",
                dismissable=True,
            )
        )
    clone_url = _inject_token(repo_url, token)

    # ── Clone ─────────────────────────────────────────────────────────────────
    clone_path = tempfile.mkdtemp(prefix="cicd-gen-")
    try:
        clone_kwargs = {"env": dict(os.environ)}
        if clone_branch:
            clone_kwargs["branch"] = clone_branch

        git.Repo.clone_from(clone_url, clone_path, **clone_kwargs)

    except git.exc.GitCommandError as exc:
        _cleanup(clone_path)
        err = str(exc)
        if token:
            err = err.replace(token, "***")
        return _err(
            dbc.Alert(
                [html.Strong("Clone failed: "), html.Code(err, style={"wordBreak": "break-all"})],
                color="danger",
                dismissable=True,
            )
        )
    except Exception as exc:
        _cleanup(clone_path)
        return _err(f"Unexpected error during clone: {exc}")

    # ── Scan ──────────────────────────────────────────────────────────────────
    try:
        scan = scan_repo(clone_path)
    except Exception as exc:
        _cleanup(clone_path)
        return _err(f"Scan error: {exc}")

    # Override repo_name with the actual name from the URL (not the temp dir)
    _url_tail = repo_url.rstrip("/").rsplit("/", 1)[-1]
    scan["repo_name"] = re.sub(r"\.git$", "", _url_tail) or scan.get("repo_name", "app")

    is_empty = len(git.Repo(clone_path).heads) == 0

    # ── Build summary table ───────────────────────────────────────────────────
    def _row(label, value):
        return html.Tr([html.Td(html.Strong(label)), html.Td(value or "—")])

    summary = _section(
        "Scan Results",
        [
            dbc.Alert(
                [
                    html.Strong("Repository cloned successfully.  "),
                    html.Small(_safe_url(repo_url), className="text-muted"),
                ],
                color="success",
                className="mb-3",
                dismissable=False,
            ),
            dbc.Table(
                html.Tbody(
                    [
                        _row("Repository", scan.get("repo_name")),
                        _row("Language", scan.get("language") or "not detected"),
                        _row("Frameworks", ", ".join(scan.get("frameworks") or []) or "none"),
                        _row("Package manager", scan.get("package_manager")),
                        _row("Has tests", "Yes" if scan.get("tests", {}).get("has_tests") else "No"),
                        _row("Test runner", scan.get("tests", {}).get("test_runner")),
                        _row("Deploy targets", ", ".join(scan.get("deploy_targets") or []) or "none"),
                        _row("Existing CI", ", ".join(scan.get("existing_ci") or []) or "none"),
                        _row("Status", "Empty repository" if is_empty else "Has commits"),
                    ]
                ),
                bordered=True,
                size="sm",
                className="mb-0",
            ),
        ],
    )

    state = {
        "scan": scan,
        "clone_path": clone_path,
        "url": repo_url,
        "is_empty": is_empty,
        "auth_type": "https-token",
    }

    # Pre-select detected language(s) in the checklist
    _half = len(LANGUAGES) // 2 + len(LANGUAGES) % 2
    _set1 = set(LANGUAGES[:_half])
    _set2 = set(LANGUAGES[_half:])
    detected_langs = scan.get("languages") or ([scan.get("language")] if scan.get("language") else [])
    lang1_values = [l for l in detected_langs if l in _set1]
    lang2_values = [l for l in detected_langs if l in _set2]

    return (None, summary, visible, visible, state, lang1_values, lang2_values, *_clear, *_reset_gen)


@app.callback(
    Output("generate-status", "children"),
    Output("yaml-preview", "children"),
    Output("generated-files-state", "data"),
    Output("file-browser", "style"),
    Output("file-tree-radio", "options"),
    Output("file-tree-radio", "value"),
    Output("ci-watch-state", "data", allow_duplicate=True),
    Output("ci-watch-interval", "disabled", allow_duplicate=True),
    Input("generate-btn", "n_clicks"),
    State("scan-state", "data"),
    State("language-checklist", "value"),
    State("language-checklist-2", "value"),
    State("language-custom", "value"),
    State("docker-toggle", "value"),
    State("docker-base-image", "value"),
    State("docker-compose-toggle", "value"),
    State("docker-push-toggle", "value"),
    State("platform-dropdown", "value"),
    State("branch-input", "value"),
    State("extra-requirements", "value"),
    State("push-toggle", "value"),
    State("watch-ci-toggle", "value"),
    State("token-input", "value"),
    State("api-key-input", "value"),
    State("llm-provider-dropdown", "value"),
    prevent_initial_call=True,
)
def generate_pipeline_cb(
    n_clicks,
    scan_state,
    language,
    language2,
    language_custom,
    docker_values,
    docker_base_image,
    docker_compose_values,
    docker_push_values,
    platform,
    branch_name,
    extra_requirements,
    push_values,
    watch_ci_values,
    token,
    api_key,
    provider,
):
    """Generate CI/CD YAML, commit on feature branch, optionally push."""
    _no_watch = (None, True)  # (ci-watch-state data, interval disabled)
    _no_files = (no_update, {"display": "none"}, no_update, no_update)  # new 4 outputs on error
    if not scan_state:
        return _alert("Please scan a repository first.", "warning"), None, *_no_files, *_no_watch

    clone_path = scan_state.get("clone_path")
    scan = scan_state.get("scan", {})
    repo_url = scan_state.get("url", "")
    auth_type = "https-token"

    if not clone_path or not Path(clone_path).is_dir():
        return (
            _alert("Clone directory not found. Please scan the repository again.", "warning"),
            None,
            *_no_files,
            *_no_watch,
        )

    branch_name = (branch_name or DEFAULT_BRANCH).strip()
    platform = platform or "github-actions"
    wants_docker = "docker" in (docker_values or [])
    wants_compose = "compose" in (docker_compose_values or [])
    wants_push = "push" in (push_values or [])  # push branch to remote
    wants_docker_push = "push" in (docker_push_values or [])  # push Docker image to Hub
    extra_requirements = (extra_requirements or "").strip()

    if language or language2 or language_custom:
        # Merge both checklist columns + freeform custom input
        langs = list(language or []) + [l for l in (language2 or []) if l not in (language or [])]
        if language_custom:
            for tok in language_custom.split(","):
                tok = tok.strip().lower()
                if tok and tok not in langs:
                    langs.append(tok)
        if langs:
            scan = dict(scan)
            scan["language"] = langs[0]  # primary language for defaults
            scan["languages"] = langs  # full list passed to prompt
    elif scan.get("language") and not scan.get("languages"):
        scan = dict(scan)
        scan["languages"] = [scan["language"]]
    if wants_docker and "docker" not in (scan.get("deploy_targets") or []):
        scan = dict(scan)
        scan["deploy_targets"] = list(scan.get("deploy_targets") or []) + ["docker"]
    if wants_compose and "docker-compose" not in (scan.get("deploy_targets") or []):
        scan = dict(scan)
        scan["deploy_targets"] = list(scan.get("deploy_targets") or []) + ["docker-compose"]

    # Strip Docker targets when the user disabled Docker in the UI
    if not wants_docker:
        current = scan.get("deploy_targets") or []
        stripped = [t for t in current if t not in ("docker", "docker-compose")]
        if stripped != list(current):
            scan = dict(scan)
            scan["deploy_targets"] = stripped

    # ── Generate Dockerfile / compose content ────────────────────────────────────────
    dockerfile_content: str | None = None
    compose_content: str | None = None
    extra_files: dict[str, str] = {}
    if wants_docker:
        raw_lang = scan.get("languages") or ([scan.get("language")] if scan.get("language") else [])
        docker_langs = raw_lang if isinstance(raw_lang, list) else ([raw_lang] if raw_lang else [])
        base_image = (docker_base_image or DEFAULT_DOCKER_BASE_IMAGE).strip()
        dockerfile_content = build_dockerfile(docker_langs, scan, base_image=base_image)
        extra_files["Dockerfile"] = dockerfile_content
        if wants_compose:
            # Derive repo name from URL (not temp dir) so compose image matches CI push target
            _url_path = repo_url.rstrip("/").rsplit("/", 1)[-1]
            image_name = re.sub(r"\.git$", "", _url_path) or scan.get("repo_name") or "app"
            compose_content = build_compose(image_name, docker_langs, docker_push=wants_docker_push)
            extra_files["docker-compose.yml"] = compose_content
            if wants_docker_push:
                extra_files[".env"] = (
                    "# Docker Hub username — used by docker-compose.yml for image naming.\n"
                    "# Set this to your Docker Hub username so that:\n"
                    "#   docker compose pull   → pulls from the registry\n"
                    "#   docker compose up     → runs the pulled image\n"
                    "DOCKER_USERNAME=your-dockerhub-username\n"
                )
        # Docker-file templates are handled by dockerfile_templates.py
        # (no need to save to CI template cache)

    extras_parts = []
    if wants_docker:
        base_image = (docker_base_image or DEFAULT_DOCKER_BASE_IMAGE).strip()
        if wants_compose:
            extras_parts.append(
                f"A Dockerfile and a docker-compose.yml are committed in the repo root "
                f"(base image: {base_image}, single image covering all selected languages). "
                "In the CI Docker build/push steps you MUST use docker compose commands — "
                "use 'docker compose build' and 'docker compose push', never plain 'docker build' or 'docker push'."
            )
        else:
            extras_parts.append(
                f"A Dockerfile is committed in the repo root (base image: {base_image}, single image "
                "covering all selected languages). In the CI Docker build step use: "
                "docker build -t <image>:$TAG . — do NOT reference per-language runtimes as base images."
            )
    if extra_requirements:
        extras_parts.append(extra_requirements)
    full_extras = "  ".join(extras_parts)

    # ── Resolve provider + API key ─────────────────────────────────────────────
    provider = (provider or DEFAULT_PROVIDER).strip()
    env_vars = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    resolved_api_key = (api_key or "").strip() or os.environ.get(env_vars.get(provider, ""), "") or None
    if not resolved_api_key:
        info = PROVIDER_INFO.get(provider, {})
        return (
            dbc.Alert(
                [
                    html.Strong("API key missing. "),
                    "Enter your ",
                    html.Strong(provider.capitalize()),
                    " key in the AI Provider field above.  ",
                    html.A(
                        info.get("get_key_label", "Get a key →"),
                        href=info.get("get_key_url", "#"),
                        target="_blank",
                    ),
                ],
                color="danger",
            ),
            None,
            *_no_files,
            *_no_watch,
        )

    # ── Generate ──────────────────────────────────────────────────────────────
    try:
        yaml_content = generate_pipeline(
            scan,
            platform,
            full_extras,
            docker_enabled=wants_docker,
            docker_push_enabled=wants_docker_push,
            api_key=resolved_api_key,
            provider=provider,
            user_extra_requirements=extra_requirements or "",
        )
        yaml_content = _sanitize_expressions(yaml_content, platform)
        yaml_content = _sanitize_runner(yaml_content, platform)
    except (EnvironmentError, ImportError) as exc:
        msg = str(exc)
        # Billing / credit errors (Anthropic insufficient credits, etc.)
        if "credit" in msg.lower() or "billing" in msg.lower() or "insufficient" in msg.lower():
            lines = [s.strip() for s in msg.splitlines() if s.strip()]
            bullets = [html.Li(l.lstrip("\u2022").strip()) for l in lines if l.startswith("\u2022")]
            summary = next((l for l in lines if not l.startswith("\u2022")), msg)
            return (
                dbc.Alert(
                    [
                        html.Strong(f"💳 {provider.capitalize()} billing error — insufficient credits. "),
                        html.Span(summary),
                        html.Ul(bullets, className="mt-2 mb-1") if bullets else None,
                        html.Hr(className="my-2"),
                        html.Span("Tip: switch to "),
                        html.Strong("Groq (Llama 3.3)"),
                        html.Span(" or "),
                        html.Strong("Gemini"),
                        html.Span(" — both have a free tier. Select in the AI Provider section above."),
                    ],
                    color="warning",
                ),
                None,
                *_no_files,
                *_no_watch,
            )
        # Render quota/rate-limit errors with structured guidance
        if "quota" in msg.lower() or "rate limit" in msg.lower() or "429" in msg:
            lines = [s.strip() for s in msg.splitlines() if s.strip()]
            bullets = [html.Li(l.lstrip("•").strip()) for l in lines if l.startswith("•")]
            summary = next((l for l in lines if not l.startswith("•")), msg)
            # Suggest the *other* provider
            alt_provider = "Gemini" if provider == "groq" else "Groq (Llama 3.3)"
            alt_note = (
                "free tier, 14 400 req/day — get a key at https://console.groq.com"
                if provider != "groq"
                else "free tier — get a key at https://aistudio.google.com/app/apikey"
            )
            return (
                dbc.Alert(
                    [
                        html.Strong(f"{provider.capitalize()} quota / rate-limit error. "),
                        html.Span(summary),
                        html.Ul(bullets, className="mt-2 mb-1") if bullets else None,
                        html.Hr(className="my-2"),
                        html.Span("Tip: switch to "),
                        html.Strong(alt_provider),
                        html.Span(f" — {alt_note}. Select it in the AI Provider section above."),
                    ],
                    color="warning",
                ),
                None,
                *_no_files,
                *_no_watch,
            )
        return _alert(msg, "danger"), None, *_no_files, *_no_watch
    except Exception as exc:
        return _alert(f"Generation error: {exc}", "danger"), None, *_no_files, *_no_watch

    # ── Commit on feature branch ──────────────────────────────────────────────
    try:
        repo = git.Repo(clone_path)
        commit_msg = _commit_on_branch(
            repo, clone_path, branch_name, platform, yaml_content, scan, extra_files=extra_files
        )
    except Exception as exc:
        return _alert(f"Git commit error: {exc}", "danger"), None, *_no_files, *_no_watch

    # ── Snapshot existing Actions runs *before* pushing ───────────────────────
    pre_push_ids: set[int] | None = None
    wants_watch = "watch" in (watch_ci_values or [])
    ghr = _parse_github_repo(repo_url)
    if wants_push and wants_watch and platform == "github-actions" and ghr and token:
        _ghr_owner, _ghr_repo = ghr
        pre_push_ids = snapshot_run_ids(_ghr_owner, _ghr_repo, branch_name, token)

    # ── Push ──────────────────────────────────────────────────────────────────
    push_msg = ""
    if wants_push:
        try:
            push_url = repo_url
            if not token:
                push_msg = "  ⚠ Push skipped: no token provided."
            else:
                push_url = _inject_token(repo_url, token)
            if not push_msg:
                _push_branch(repo, push_url, branch_name, auth_type)
                push_msg = f"  Branch '{branch_name}' pushed to remote."
        except Exception as exc:
            err = str(exc)
            if token:
                err = err.replace(token, "***")
            push_msg = f"  ⚠ Push failed: {err}"

    # ── Start CI watcher if conditions are met ─────────────────────────────────
    watch_state = None
    interval_disabled = True
    push_succeeded = "pushed to remote" in push_msg
    can_watch = wants_watch and push_succeeded and platform == "github-actions" and "github.com" in repo_url and token
    if can_watch and ghr:
        owner, repo_name = ghr
        watch_id = str(uuid.uuid4())
        cancel_ev = threading.Event()
        with _ci_watch_lock:
            _ci_watch_results[watch_id] = {
                "messages": ["CI watcher started — waiting for GitHub Actions run…"],
                "steps": [
                    {"label": "Waiting for Actions run to appear", "status": "running"},
                    {"label": "CI run in progress", "status": "pending"},
                ],
                "status": "watching",
                "done": False,
                "attempt": 1,
            }
        _ci_cancel_flags[watch_id] = cancel_ev
        threading.Thread(
            target=_watch_ci_and_heal,
            kwargs=dict(
                watch_id=watch_id,
                owner=owner,
                repo_name=repo_name,
                branch_name=branch_name,
                token=token,
                clone_path=clone_path,
                platform=platform,
                scan=scan,
                provider=provider,
                api_key=resolved_api_key,
                cancel_event=cancel_ev,
                pre_push_run_ids=pre_push_ids,
            ),
            daemon=True,
        ).start()
        watch_state = {"watch_id": watch_id}
        interval_disabled = False

    # ── Build output ──────────────────────────────────────────────────────────
    # Construct a GitHub compare / PR link when possible
    github_link = None
    if "github.com" in repo_url and "pushed" in push_msg:
        clean_url = repo_url.rstrip("/").removesuffix(".git")
        # Strip any embedded token from the display URL
        clean_url = re.sub(r"https://[^@]+@", "https://", clean_url)
        pr_url = f"{clean_url}/compare/{branch_name}?expand=1"
        github_link = html.Span(["  ", html.A("Open Pull Request on GitHub →", href=pr_url, target="_blank")])

    status = dbc.Alert(
        [html.Strong("Pipeline generated!  "), commit_msg + push_msg, github_link],
        color="success",
        dismissable=True,
    )

    # ── Build generated-files state and file-browser tree ────────────────────
    files_state = _build_files_state(
        clone_path,
        platform,
        yaml_content,
        dockerfile_content,
        compose_content,
        extra_generated={k: v for k, v in extra_files.items() if k not in ("Dockerfile", "docker-compose.yml")},
    )
    tree_options = _files_to_tree_options(files_state["files"])
    default_file = files_state.get("default_file") or (tree_options[0]["value"] if tree_options else None)

    return (
        status,
        None,
        files_state,
        {"display": "block"},
        tree_options,
        default_file,
        watch_state,
        interval_disabled,
    )


@app.callback(
    Output("ci-watch-status", "children"),
    Output("ci-watch-interval", "disabled"),
    Output("ci-watch-state", "data"),
    Output("cancel-btn-row", "style"),
    Output("generated-files-state", "data", allow_duplicate=True),
    Output("ci-log-store", "data"),
    Input("ci-watch-interval", "n_intervals"),
    State("ci-watch-state", "data"),
    State("generated-files-state", "data"),
    prevent_initial_call=True,
)
def poll_ci_watch_status(n_intervals, watch_state, files_state):
    """Read background CI-watch progress and update the status card."""
    _hidden = {"display": "none"}
    _visible = {"display": "inline-block", "marginTop": "8px"}
    if not watch_state or not watch_state.get("watch_id"):
        return None, True, watch_state, _hidden, no_update, no_update

    watch_id = watch_state["watch_id"]
    with _ci_watch_lock:
        entry = dict(_ci_watch_results.get(watch_id, {}))
    if not entry:
        return None, True, watch_state, _hidden, no_update, no_update

    messages = entry.get("messages", [])
    steps = entry.get("steps", [])
    done = entry.get("done", False)
    status = entry.get("status", "watching")
    attempt = entry.get("attempt", 1)
    last_failure = entry.get("last_failure", [])
    color_map = {
        "passed": "success",
        "error": "danger",
        "watching": "info",
        "cancelled": "secondary",
    }
    color = color_map.get(status, "info")

    title_map = {
        "passed": "✅ CI passed!",
        "error": "❌ CI watch stopped — see log",
        "watching": f"⏳ Watching CI…  (attempt {attempt})",
        "cancelled": "🚫 Watch cancelled",
    }
    title = title_map.get(status, "CI watch")

    # ── Steps timeline ──────────────────────────────────────────────────────────
    step_icons = {"pending": "○", "running": "▶", "passed": "✅", "failed": "❌", "skipped": "−"}
    step_colors = {
        "pending": "text-muted",
        "running": "text-primary fw-semibold",
        "passed": "text-success",
        "failed": "text-danger",
        "skipped": "text-muted",
    }
    step_items = [
        html.Div(
            [
                html.Span(step_icons.get(s["status"], "○"), className="me-2"),
                html.Span(s["label"], className=step_colors.get(s["status"], "")),
            ],
            style={"fontSize": "0.83rem", "marginBottom": "2px"},
        )
        for s in steps
    ]

    # ── Failed steps (shown prominently when present) ────────────────────────────
    failure_section = (
        html.Div(
            [
                html.Span("Failed at: ", className="fw-semibold text-danger me-1", style={"fontSize": "0.82rem"}),
                *[
                    html.Code(
                        lbl,
                        className="me-1",
                        style={
                            "fontSize": "0.78rem",
                            "background": "#fde8e8",
                            "padding": "1px 5px",
                            "borderRadius": "3px",
                            "color": "#b91c1c",
                        },
                    )
                    for lbl in last_failure
                ],
            ],
            className="mb-1",
        )
        if last_failure
        else None
    )

    # ── Log tail ─────────────────────────────────────────────────────────────────────
    log_tail = html.Details(
        [
            html.Summary(
                html.Span(
                    [
                        html.Span("Show log", className="me-3"),
                        html.A(
                            "⬇ Download full log",
                            id="download-log-btn",
                            href="#",
                            style={"fontSize": "0.78rem"},
                        ),
                    ]
                ),
                style={"cursor": "pointer", "fontSize": "0.8rem"},
            ),
            html.Pre(
                "\n".join(messages[-50:]),
                id="ci-log-pre",
                style={
                    "maxHeight": "260px",
                    "overflowY": "auto",
                    "fontSize": "0.73rem",
                    "marginTop": "4px",
                    "background": "#f8f9fa",
                    "padding": "6px",
                    "borderRadius": "4px",
                },
            ),
        ],
        open=True,
        style={"marginTop": "4px"},
    )

    card = dbc.Card(
        dbc.CardBody(
            [html.Strong(title), html.Div(step_items, className="mt-1 mb-1"), failure_section, log_tail],
            className="py-2 px-3",
        ),
        className="mt-2",
        style={"borderLeft": f"4px solid var(--bs-{color})"},
    )

    cancel_style = _hidden if done else _visible

    # When CI passes, refresh the CI YAML in the file-browser store
    updated_files_state = no_update
    if done and status == "passed" and files_state and watch_state:
        try:
            clone_path = watch_state.get("clone_path") or (files_state or {}).get("clone_path", "")
            platform = (files_state or {}).get("platform", "")
            if clone_path and platform:
                from writer import PLATFORM_OUTPUT_PATHS

                ci_rel = PLATFORM_OUTPUT_PATHS.get(platform, PLATFORM_OUTPUT_PATHS["github"])
                ci_path = Path(clone_path) / ci_rel
                if ci_path.exists():
                    new_yaml = ci_path.read_text(encoding="utf-8")
                    updated_files_state = dict(files_state)
                    updated_files_state["files"] = dict(files_state.get("files", {}))
                    updated_files_state["files"][str(PurePosixPath(ci_rel))] = new_yaml
        except Exception:
            pass

    return card, done, (None if done else watch_state), cancel_style, updated_files_state, messages


@app.callback(
    Output("file-viewer-content", "children"),
    Input("file-tree-radio", "value"),
    State("generated-files-state", "data"),
    prevent_initial_call=True,
)
def view_generated_file(selected, files_state):
    """Render a selected file from the generated-files tree."""
    if not selected or not files_state or selected.startswith("__dir__"):
        raise PreventUpdate
    files = (files_state or {}).get("files", {})
    content = files.get(selected)
    if content is None:
        clone_path = (files_state or {}).get("clone_path", "")
        if clone_path:
            disk_path = Path(clone_path) / selected
            if disk_path.exists():
                try:
                    content = disk_path.read_text(encoding="utf-8")
                except Exception:
                    pass
    if content is None:
        return dbc.Alert(f"Content not available: {selected}", color="warning", className="mt-2")
    return _render_file_content(selected, content)


@app.callback(
    Output("ci-watch-status", "children", allow_duplicate=True),
    Output("ci-watch-interval", "disabled", allow_duplicate=True),
    Output("ci-watch-state", "data", allow_duplicate=True),
    Output("cancel-btn-row", "style", allow_duplicate=True),
    Input("cancel-watch-btn", "n_clicks"),
    State("ci-watch-state", "data"),
    prevent_initial_call=True,
)
def cancel_ci_watch(n_clicks, watch_state):
    """Signal the background watcher to stop."""
    if not n_clicks or not watch_state or not watch_state.get("watch_id"):
        raise PreventUpdate
    watch_id = watch_state["watch_id"]
    cancel_ev = _ci_cancel_flags.get(watch_id)
    if cancel_ev:
        cancel_ev.set()
    with _ci_watch_lock:
        entry = _ci_watch_results.get(watch_id, {})
        entry["status"] = "cancelled"
        entry["done"] = True
        entry.get("messages", []).append("🚫 Cancelled by user.")
        entry["progress"] = 100
    return (
        dbc.Alert("🚫 CI watch cancelled by user.", color="secondary", dismissable=True, className="mt-2"),
        True,
        None,
        {"display": "none"},
    )


# ── Auto-scroll log to bottom when content updates ───────────────────────────

app.clientside_callback(
    """
    function(children) {
        var el = document.getElementById('ci-log-pre');
        if (el) { el.scrollTop = el.scrollHeight; }
        return window.dash_clientside.no_update;
    }
    """,
    Output("ci-log-pre", "id"),
    Input("ci-watch-status", "children"),
    prevent_initial_call=True,
)


@app.callback(
    Output("download-log", "data"),
    Input("download-log-btn", "n_clicks"),
    State("ci-log-store", "data"),
    prevent_initial_call=True,
)
def download_full_log(n_clicks, log_messages):
    """Serve the full CI watch log as a text file download."""
    if not n_clicks or not log_messages:
        raise PreventUpdate
    content = "\n".join(log_messages)
    return dict(content=content, filename="cicd-gen-ci-watch.log", type="text/plain")


# ── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket

    preferred = int(os.environ.get("DASH_PORT", 8050))

    def _find_free_port(start: int) -> int:
        for p in range(start, start + 20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", p))
                    return p
                except OSError:
                    continue
        raise RuntimeError(f"No free port found in range {start}–{start + 19}")

    port = _find_free_port(preferred)
    if port != preferred:
        print(f"Port {preferred} is in use — starting on http://0.0.0.0:{port} instead")

    app.run(debug=True, host="0.0.0.0", port=port)
