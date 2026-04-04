################################################################################
#  Filename:      project/dashboard.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 2:59:45 am                         #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday April 4th 2026 4:17:59 am                           #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

################################################################################
#  Filename:      project/dashboard.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 12:12:13 am                        #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday April 4th 2026 4:03:47 am                           #
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

  1. User provides a remote repository URL (SSH or HTTPS).
  2. App clones it to a temporary directory and scans the tech stack.
  3. User configures the pipeline (language, docker, platform, branch name).
  4. App generates CI/CD YAML, commits it on a new feature branch, and
     optionally pushes it back — so the default branch stays untouched.

Authentication model (no secrets stored on disk or in browser storage):
  • SSH URL  (git@…)     → uses ~/.ssh keys already on the host; no UI input.
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
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path

# ── Make sure sibling modules are importable when run directly ────────────────
sys.path.insert(0, str(Path(__file__).parent))

import dash
import dash_bootstrap_components as dbc
import git
from dash import Input, Output, State, dcc, html
from generator import SUPPORTED_PLATFORMS, SUPPORTED_PROVIDERS, generate_pipeline
from scanner import scan_repo
from writer import write_config

# ── Auth helpers ─────────────────────────────────────────────────────────────


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


# ── Constants ─────────────────────────────────────────────────────────────────

LANGUAGES = [
    "python",
    "node",
    "go",
    "java",
    "rust",
    "ruby",
    "php",
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
                # ── Auth section ───────────────────────────────────────────────
                dbc.Accordion(
                    dbc.AccordionItem(
                        [
                            dbc.RadioItems(
                                id="auth-type",
                                options=[
                                    {
                                        "label": html.Span(
                                            [
                                                html.Strong("SSH  "),
                                                html.Small(
                                                    "(git@…) — uses your ~/.ssh key, no credentials enter the UI",
                                                    className="text-muted",
                                                ),
                                            ]
                                        ),
                                        "value": "ssh",
                                    },
                                    {
                                        "label": html.Span(
                                            [
                                                html.Strong("HTTPS — public repo  "),
                                                html.Small("No credentials needed", className="text-muted"),
                                            ]
                                        ),
                                        "value": "https-public",
                                    },
                                    {
                                        "label": html.Span(
                                            [
                                                html.Strong("HTTPS — private repo  "),
                                                html.Small(
                                                    "Personal access token (never stored, memory-only)",
                                                    className="text-muted",
                                                ),
                                            ]
                                        ),
                                        "value": "https-token",
                                    },
                                ],
                                value="https-public",
                                className="mb-2",
                                persistence=True,
                                persistence_type="session",
                            ),
                            # Token row — visible only for https-token
                            html.Div(
                                id="token-row",
                                children=[
                                    dbc.Input(
                                        id="token-input",
                                        placeholder="Personal access token",
                                        type="password",
                                        # persistence intentionally omitted (defaults False)
                                        # token is NEVER written to localStorage or sessionStorage
                                        autocomplete="off",
                                    ),
                                    # How-to guidance for creating a GitHub PAT
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
                                style={"display": "none"},
                            ),
                            dbc.Alert(
                                [
                                    html.Strong("Security note: "),
                                    "Your token is used only to authenticate the git clone/push "
                                    "operation and is never written to disk, localStorage, or any "
                                    "server-side store. It exists only in this browser tab's memory "
                                    "for the duration of the operation.",
                                ],
                                color="info",
                                className="mt-2 mb-0 py-2",
                            ),
                        ],
                        title="Authentication",
                    ),
                    start_collapsed=False,
                    className="mb-0",
                ),
            ],
        ),
        # ── LLM provider ──────────────────────────────────────────────────────
        _section(
            "AI Provider",
            [
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                dbc.Label("Provider"),
                                dcc.Dropdown(
                                    id="llm-provider-dropdown",
                                    options=[
                                        {"label": PROVIDER_INFO[p]["label"], "value": p} for p in SUPPORTED_PROVIDERS
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
                                    # No persistence — key lives only in this tab's memory
                                ),
                            ],
                            md=7,
                            className="mb-3",
                        ),
                    ]
                ),
                # Dynamic help row — updated by callback
                html.Div(id="provider-info"),
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
                                    dbc.Label("Programming Language  (optional override)"),
                                    dcc.Dropdown(
                                        id="language-dropdown",
                                        options=[{"label": l.capitalize(), "value": l} for l in LANGUAGES],
                                        placeholder="Use auto-detected language",
                                        clearable=True,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
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
                                        options=[{"label": " Generate a Docker build & push step", "value": "docker"}],
                                        value=[],
                                        switch=True,
                                        persistence=True,
                                        persistence_type="session",
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
                                    value=[],
                                    switch=True,
                                    persistence=True,
                                    persistence_type="session",
                                ),
                                className="d-flex align-items-center",
                            ),
                        ],
                        align="center",
                    ),
                ],
            ),
            style={"display": "none"},
        ),
        # ── Generation result ──────────────────────────────────────────────────
        html.Div(id="generate-status"),
        html.Div(id="yaml-preview"),
        dcc.Download(id="yaml-download"),
        # ── Hidden stores (memory-only — cleared on page refresh) ──────────────
        # Holds: {scan, clone_path, url, is_empty, auth_type}
        dcc.Store(id="scan-state", storage_type="memory"),
    ],
    className="mt-3",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────


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
    Output("token-row", "style"),
    Input("auth-type", "value"),
)
def toggle_token_row(auth_type):
    """Show the token field only when HTTPS + private is selected."""
    return {"display": "block"} if auth_type == "https-token" else {"display": "none"}


@app.callback(
    Output("scan-status", "children"),
    Output("scan-summary", "children"),
    Output("scan-summary", "style"),
    Output("config-panel", "style"),
    Output("scan-state", "data"),
    Input("scan-btn", "n_clicks"),
    State("repo-url-input", "value"),
    State("clone-branch-input", "value"),
    State("auth-type", "value"),
    State("token-input", "value"),
    State("scan-state", "data"),
    prevent_initial_call=True,
)
def scan_repository(n_clicks, repo_url, clone_branch, auth_type, token, prev_state):
    """Clone the remote repo and scan its tech stack."""
    hidden = {"display": "none"}
    visible = {"display": "block"}

    if not repo_url or not repo_url.strip():
        return _alert("Please enter a repository URL.", "warning"), None, hidden, hidden, None

    repo_url = repo_url.strip()
    clone_branch = (clone_branch or "").strip() or None

    if not (_is_ssh_url(repo_url) or repo_url.startswith("http://") or repo_url.startswith("https://")):
        return (
            _alert("URL must start with git@…, https://, or http://", "warning"),
            None,
            hidden,
            hidden,
            None,
        )

    # ── Clean up previous temp clone ─────────────────────────────────────────
    if prev_state and prev_state.get("clone_path"):
        _cleanup(prev_state["clone_path"])

    # ── Build clone URL ───────────────────────────────────────────────────────
    if auth_type == "https-token":
        if not token:
            return (
                _alert("A personal access token is required for private HTTPS repositories.", "warning"),
                None,
                hidden,
                hidden,
                None,
            )
        clone_url = _inject_token(repo_url, token)
    else:
        clone_url = repo_url

    # ── Clone ─────────────────────────────────────────────────────────────────
    clone_path = tempfile.mkdtemp(prefix="cicd-gen-")
    try:
        clone_kwargs = {"env": dict(os.environ)}
        if _is_ssh_url(repo_url):
            clone_kwargs["env"]["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
        if clone_branch:
            clone_kwargs["branch"] = clone_branch

        git.Repo.clone_from(clone_url, clone_path, **clone_kwargs)

    except git.exc.GitCommandError as exc:
        _cleanup(clone_path)
        err = str(exc)
        if auth_type == "https-token" and token:
            err = err.replace(token, "***")
        return (
            dbc.Alert(
                [html.Strong("Clone failed: "), html.Code(err, style={"wordBreak": "break-all"})],
                color="danger",
                dismissable=True,
            ),
            None,
            hidden,
            hidden,
            None,
        )
    except Exception as exc:
        _cleanup(clone_path)
        return _alert(f"Unexpected error during clone: {exc}", "danger"), None, hidden, hidden, None

    # ── Scan ──────────────────────────────────────────────────────────────────
    try:
        scan = scan_repo(clone_path)
    except Exception as exc:
        _cleanup(clone_path)
        return _alert(f"Scan error: {exc}", "danger"), None, hidden, hidden, None

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
        "auth_type": auth_type,
    }

    return None, summary, visible, visible, state


@app.callback(
    Output("generate-status", "children"),
    Output("yaml-preview", "children"),
    Output("yaml-download", "data"),
    Input("generate-btn", "n_clicks"),
    State("scan-state", "data"),
    State("language-dropdown", "value"),
    State("docker-toggle", "value"),
    State("platform-dropdown", "value"),
    State("branch-input", "value"),
    State("extra-requirements", "value"),
    State("push-toggle", "value"),
    State("token-input", "value"),
    State("api-key-input", "value"),
    State("llm-provider-dropdown", "value"),
    prevent_initial_call=True,
)
def generate_pipeline_cb(
    n_clicks,
    scan_state,
    language,
    docker_values,
    platform,
    branch_name,
    extra_requirements,
    push_values,
    token,
    api_key,
    provider,
):
    """Generate CI/CD YAML, commit on feature branch, optionally push."""
    if not scan_state:
        return _alert("Please scan a repository first.", "warning"), None, None

    clone_path = scan_state.get("clone_path")
    scan = scan_state.get("scan", {})
    repo_url = scan_state.get("url", "")
    auth_type = scan_state.get("auth_type", "https-public")

    if not clone_path or not Path(clone_path).is_dir():
        return (
            _alert("Clone directory not found. Please scan the repository again.", "warning"),
            None,
            None,
        )

    branch_name = (branch_name or DEFAULT_BRANCH).strip()
    platform = platform or "github-actions"
    wants_docker = "docker" in (docker_values or [])
    wants_push = "push" in (push_values or [])
    extra_requirements = (extra_requirements or "").strip()

    if language:
        scan = dict(scan)
        scan["language"] = language
    if wants_docker and "docker" not in (scan.get("deploy_targets") or []):
        scan = dict(scan)
        scan["deploy_targets"] = list(scan.get("deploy_targets") or []) + ["docker"]

    extras_parts = []
    if wants_docker:
        extras_parts.append("Include a step to build and push a Docker image.")
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
            None,
        )

    # ── Generate ──────────────────────────────────────────────────────────────
    try:
        yaml_content = generate_pipeline(scan, platform, full_extras, api_key=resolved_api_key, provider=provider)
    except (EnvironmentError, ImportError) as exc:
        return _alert(str(exc), "danger"), None, None
    except Exception as exc:
        return _alert(f"Generation error: {exc}", "danger"), None, None

    # ── Commit on feature branch ──────────────────────────────────────────────
    try:
        repo = git.Repo(clone_path)
        commit_msg = _commit_on_branch(repo, clone_path, branch_name, platform, yaml_content)
    except Exception as exc:
        return _alert(f"Git commit error: {exc}", "danger"), None, None

    # ── Optionally push ───────────────────────────────────────────────────────
    push_msg = ""
    if wants_push:
        try:
            push_url = repo_url
            if auth_type == "https-token":
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

    # ── Build output ──────────────────────────────────────────────────────────
    status = dbc.Alert(
        [html.Strong("Pipeline generated!  "), commit_msg + push_msg],
        color="success",
        dismissable=True,
    )

    filename = Path(clone_path).name + "_pipeline.yml"
    preview = _section(
        f"Generated Pipeline  ·  {PLATFORM_LABELS.get(platform, platform)}",
        [
            html.A(
                dbc.Button("⬇ Download YAML", color="outline-secondary", size="sm", className="mb-2"),
                id="download-btn",
                href="#",
            ),
            dcc.Markdown(
                f"```yaml\n{yaml_content}\n```",
                style={"maxHeight": "500px", "overflowY": "auto"},
            ),
        ],
    )

    return status, preview, dcc.send_string(yaml_content, filename=filename)


# ── Git helpers ───────────────────────────────────────────────────────────────


def _commit_on_branch(repo: git.Repo, clone_path: str, branch_name: str, platform: str, yaml_content: str) -> str:
    """Write the generated config and commit it on *branch_name*."""
    is_empty = len(repo.heads) == 0
    output_path = write_config(yaml_content, clone_path, platform)
    rel = output_path.relative_to(clone_path)

    if is_empty:
        repo.git.symbolic_ref("HEAD", f"refs/heads/{branch_name}")
        repo.index.add([str(rel)])
        repo.index.commit("ci: bootstrap CI/CD pipeline via cicd-gen")
        return f"Initial commit on branch '{branch_name}'. File: {rel}."

    if branch_name in [h.name for h in repo.heads]:
        repo.git.checkout(branch_name)
        created = False
    else:
        repo.git.checkout("-b", branch_name)
        created = True

    repo.index.add([str(rel)])
    repo.index.commit("ci: add CI/CD pipeline via cicd-gen")
    return f"Branch '{branch_name}' {'created' if created else 'updated'}. File: {rel}."


def _push_branch(repo: git.Repo, push_url: str, branch_name: str, auth_type: str) -> None:
    """Push *branch_name* to the remote."""
    env = dict(os.environ)
    if auth_type == "ssh" or _is_ssh_url(push_url):
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
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
