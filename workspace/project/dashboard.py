################################################################################
#  Filename:      project/dashboard.py                                         #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 12:12:13 am                        #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday April 4th 2026 12:12:17 am                          #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""
dashboard.py
------------
Dash web UI for cicd-gen.

Handles the "empty repository" workflow:
  1. User enters path to a local git repository.
  2. App detects whether the repo is empty (no commits).
  3. If empty, user configures:
       - Programming language  (optional)
       - Whether to generate a Docker build step
       - CI/CD platform
       - Feature branch name for the changes
  4. On submit, the generated pipeline is written to the feature branch
     so the user's working branch stays untouched.

Run with:
    python dashboard.py
Then open http://localhost:8050
"""

import os
import sys
from pathlib import Path

# ── Make sure sibling modules are importable when run directly ────────────────
sys.path.insert(0, str(Path(__file__).parent))

import dash
import dash_bootstrap_components as dbc
import git
from dash import Input, Output, State, callback_context, dcc, html
from generator import SUPPORTED_PLATFORMS, generate_pipeline
from writer import write_config

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
                        html.P(
                            "AI-powered CI/CD pipeline generator",
                            className="text-muted",
                        ),
                    ],
                    className="py-4",
                )
            )
        ),
        # ── Repository input ──────────────────────────────────────────────────
        _section(
            "Repository",
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Input(
                            id="repo-path-input",
                            placeholder="Absolute path to your git repository  e.g. /home/user/my-project",
                            type="text",
                            debounce=False,
                            persistence=True,
                            persistence_type="session",
                        ),
                        width=9,
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Scan",
                            id="scan-btn",
                            color="primary",
                            className="w-100",
                            n_clicks=0,
                        ),
                        width=3,
                    ),
                ],
                align="center",
            ),
        ),
        # ── Scan status / feedback ────────────────────────────────────────────
        html.Div(id="scan-status"),
        # ── Empty-repo configuration panel (hidden until needed) ──────────────
        html.Div(
            id="config-panel",
            children=_section(
                "Pipeline Configuration",
                [
                    dbc.Row(
                        [
                            # Language (optional)
                            dbc.Col(
                                [
                                    dbc.Label("Programming Language  (optional)"),
                                    dcc.Dropdown(
                                        id="language-dropdown",
                                        options=[{"label": lang.capitalize(), "value": lang} for lang in LANGUAGES],
                                        placeholder="Auto-detect / leave blank",
                                        clearable=True,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                            # CI/CD platform
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
                            # Docker toggle
                            dbc.Col(
                                [
                                    dbc.Label("Docker"),
                                    dbc.Checklist(
                                        id="docker-toggle",
                                        options=[
                                            {
                                                "label": " Generate a Docker build & push step",
                                                "value": "docker",
                                            }
                                        ],
                                        value=[],
                                        switch=True,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                            # Branch name
                            dbc.Col(
                                [
                                    dbc.Label("Feature Branch Name"),
                                    dbc.Input(
                                        id="branch-input",
                                        value=DEFAULT_BRANCH,
                                        type="text",
                                        placeholder=DEFAULT_BRANCH,
                                        persistence=True,
                                        persistence_type="session",
                                    ),
                                    dbc.FormText(
                                        "Changes will be committed to this new branch, "
                                        "leaving your current branch untouched."
                                    ),
                                ],
                                md=6,
                                className="mb-3",
                            ),
                        ]
                    ),
                    # Extra free-text requirements
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
                    dbc.Button(
                        "Generate & Commit Pipeline",
                        id="generate-btn",
                        color="success",
                        size="lg",
                        n_clicks=0,
                    ),
                ],
            ),
            style={"display": "none"},
        ),
        # ── Generation result ─────────────────────────────────────────────────
        html.Div(id="generate-status"),
        html.Div(id="yaml-preview"),
        # ── Hidden stores ─────────────────────────────────────────────────────
        dcc.Store(id="repo-state"),  # {"path": ..., "empty": bool}
    ],
    className="mt-3",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────


@app.callback(
    Output("scan-status", "children"),
    Output("config-panel", "style"),
    Output("repo-state", "data"),
    Input("scan-btn", "n_clicks"),
    State("repo-path-input", "value"),
    prevent_initial_call=True,
)
def scan_repository(n_clicks, repo_path):
    """Validate the repo path and check whether Î it is empty."""
    hidden = {"display": "none"}
    visible = {"display": "block"}

    if not repo_path or not repo_path.strip():
        return _alert("Please enter a repository path.", "warning"), hidden, None

    repo_path = repo_path.strip()

    # ── Validate it is a directory ────────────────────────────────────────────
    if not Path(repo_path).is_dir():
        return (
            _alert(f"Directory not found: {repo_path}", "danger"),
            hidden,
            None,
        )

    # ── Validate it is a git repository ──────────────────────────────────────
    try:
        repo = git.Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return (
            _alert(
                f"Not a git repository: {repo_path}\n" "Run  git init  inside the directory first.",
                "danger",
            ),
            hidden,
            None,
        )
    except Exception as exc:
        return _alert(f"Error opening repository: {exc}", "danger"), hidden, None

    # ── Check for commits ─────────────────────────────────────────────────────
    is_empty = len(repo.heads) == 0  # no branches → no commits

    if is_empty:
        status = dbc.Alert(
            [
                html.Strong("Empty repository detected. "),
                "No commits found. Configure the pipeline below and click ",
                html.Em("Generate & Commit Pipeline"),
                " to create your first CI/CD setup on a new branch.",
            ],
            color="info",
            dismissable=False,
        )
        return status, visible, {"path": repo_path, "empty": True}

    # Non-empty repo — reserved for a future workflow
    current_branch = repo.active_branch.name
    commit_count = sum(1 for _ in repo.iter_commits())
    status = dbc.Alert(
        [
            html.Strong("Repository is not empty. "),
            f"Branch: {current_branch} · {commit_count} commit(s). ",
            "Support for non-empty repositories is coming soon.",
        ],
        color="warning",
        dismissable=True,
    )
    return status, hidden, {"path": repo_path, "empty": False}


@app.callback(
    Output("generate-status", "children"),
    Output("yaml-preview", "children"),
    Input("generate-btn", "n_clicks"),
    State("repo-state", "data"),
    State("language-dropdown", "value"),
    State("docker-toggle", "value"),
    State("platform-dropdown", "value"),
    State("branch-input", "value"),
    State("extra-requirements", "value"),
    prevent_initial_call=True,
)
def generate_and_commit(
    n_clicks,
    repo_state,
    language,
    docker_values,
    platform,
    branch_name,
    extra_requirements,
):
    """Generate the CI/CD pipeline YAML and commit it on the named branch."""

    if not repo_state:
        return _alert("Please scan a repository first.", "warning"), None

    if not repo_state.get("empty"):
        return _alert("Only empty repositories are supported in this version.", "warning"), None

    repo_path = repo_state["path"]
    branch_name = (branch_name or DEFAULT_BRANCH).strip()
    platform = platform or "github-actions"
    wants_docker = "docker" in (docker_values or [])
    extra_requirements = (extra_requirements or "").strip()

    # ── Build minimal scan context for the empty repo ─────────────────────────
    scan = {
        "repo_name": Path(repo_path).name,
        "language": language or None,
        "frameworks": [],
        "package_manager": None,
        "tests": {"has_tests": False, "test_runner": None},
        "deploy_targets": ["docker"] if wants_docker else [],
        "existing_ci": [],
    }

    # ── Compose extra requirements ────────────────────────────────────────────
    extras_parts = []
    if wants_docker:
        extras_parts.append("Include a step to build and push a Docker image.")
    if extra_requirements:
        extras_parts.append(extra_requirements)
    full_extras = "  ".join(extras_parts)

    # ── Call the generator ────────────────────────────────────────────────────
    try:
        yaml_content = generate_pipeline(scan, platform, full_extras)
    except EnvironmentError:
        return (
            _alert(
                "ANTHROPIC_API_KEY is not set.  " "Export it as an environment variable or add it to a .env file.",
                "danger",
            ),
            None,
        )
    except Exception as exc:
        return _alert(f"Generation error: {exc}", "danger"), None

    # ── Git operations ────────────────────────────────────────────────────────
    try:
        repo = git.Repo(repo_path)
        git_msg = _commit_on_branch(repo, repo_path, branch_name, platform, yaml_content)
    except Exception as exc:
        return _alert(f"Git error: {exc}", "danger"), None

    # ── Success ───────────────────────────────────────────────────────────────
    status = dbc.Alert(
        [html.Strong("Pipeline generated! "), git_msg],
        color="success",
        dismissable=True,
    )

    preview = _section(
        f"Generated Pipeline  ·  {PLATFORM_LABELS.get(platform, platform)}",
        dcc.Markdown(
            f"```yaml\n{yaml_content}\n```",
            style={"maxHeight": "500px", "overflowY": "auto"},
        ),
    )

    return status, preview


# ── Git helpers ───────────────────────────────────────────────────────────────


def _commit_on_branch(
    repo: "git.Repo",
    repo_path: str,
    branch_name: str,
    platform: str,
    yaml_content: str,
) -> str:
    """
    Write the generated config and commit it on *branch_name*.

    Empty-repo strategy
    -------------------
    An empty git repo has no HEAD commit, so we cannot use
    `repo.create_head(...)`.  Instead we:
      1. Point HEAD symbolically at the desired branch name (before any commit).
      2. Write the file and stage it.
      3. Create the initial commit — git records it on the branch automatically.

    Non-empty repo (future)
    -----------------------
    Simply create / checkout the branch, write the file, stage, commit.

    Returns a human-readable status string.
    """
    is_empty = len(repo.heads) == 0

    if is_empty:
        # Redirect HEAD to the desired branch BEFORE the first commit
        repo.git.symbolic_ref("HEAD", f"refs/heads/{branch_name}")

        output_path = write_config(yaml_content, repo_path, platform)
        repo.index.add([str(output_path.relative_to(repo_path))])
        repo.index.commit(
            "ci: bootstrap CI/CD pipeline via cicd-gen",
            author_date="now",
            commit_date="now",
        )
        return (
            f"Initial commit created on branch  '{branch_name}'.  "
            f"File written to  {output_path.relative_to(repo_path)}."
        )

    # ── Non-empty repo path (reserved for future use) ─────────────────────────
    current = repo.active_branch.name
    if branch_name in [h.name for h in repo.heads]:
        repo.git.checkout(branch_name)
        created = False
    else:
        repo.git.checkout("-b", branch_name)
        created = True

    output_path = write_config(yaml_content, repo_path, platform)
    repo.index.add([str(output_path.relative_to(repo_path))])
    repo.index.commit("ci: add CI/CD pipeline via cicd-gen")

    action = "created" if created else "updated"
    return (
        f"Branch  '{branch_name}'  {action}  (was on '{current}').  "
        f"File written to  {output_path.relative_to(repo_path)}."
    )


# ── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASH_PORT", 8050))
    app.run(debug=True, host="0.0.0.0", port=port)
