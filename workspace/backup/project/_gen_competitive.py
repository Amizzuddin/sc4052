################################################################################
#  Filename:      docs/_gen_competitive.py                                     #
#  Project:       SC4079 Cloud Computing                                       #
#  Created Date:  Saturday, April 4th 2026, 2:04:52 pm                         #
#  Author:        Amizzuddin Amin Chan                                         #
#  Description:   <<ADD Description>>                                          #
#  --------------------------------------------------------------------------- #
#  Last Modified: Saturday April 4th 2026 2:05:17 pm                           #
#  Modified By:   Amizzuddin Amin Chan                                         #
#  --------------------------------------------------------------------------- #
#  HISTORY:                                                                    #
#  Date         By    Comments                                                 #
#  ----------   ---   -------------------------------------------------------- #
################################################################################

"""Generate cicd_gen_competitive_analysis.docx"""

import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

doc = Document()

section = doc.sections[0]
section.left_margin = Inches(1)
section.right_margin = Inches(1)
section.top_margin = Inches(1)
section.bottom_margin = Inches(1)


def add_heading(text, level=1):
    h = doc.add_heading(text, level=level)
    h.paragraph_format.space_before = Pt(14) if level <= 2 else Pt(8)
    h.paragraph_format.space_after = Pt(4)
    return h


def add_para(text, size=11):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.size = Pt(size)
    p.paragraph_format.space_after = Pt(5)
    return p


def add_bullet(text, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.25 * (level + 1))
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    r.font.size = Pt(10.5)
    return p


def shade_cell(cell, hex_fill, text_color=None):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)
    if text_color and cell.paragraphs[0].runs:
        cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(*bytes.fromhex(text_color))


def add_table(headers, rows, header_color="1a237e", alt_color="E8EAF6"):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr_row = t.rows[0]
    for i, h in enumerate(headers):
        cell = hdr_row.cells[i]
        cell.text = h
        if cell.paragraphs[0].runs:
            cell.paragraphs[0].runs[0].bold = True
            cell.paragraphs[0].runs[0].font.size = Pt(10)
        shade_cell(cell, header_color, "ffffff")
    for ri, row in enumerate(rows):
        tr = t.rows[ri + 1]
        for ci, val in enumerate(row):
            cell = tr.cells[ci]
            cell.text = str(val)
            if cell.paragraphs[0].runs:
                cell.paragraphs[0].runs[0].font.size = Pt(10)
            if ri % 2 == 1:
                shade_cell(cell, alt_color)
    doc.add_paragraph()
    return t


def add_callout(text, fill="FFF8E1"):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.right_indent = Inches(0.3)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(text)
    r.font.size = Pt(10.5)
    r.italic = True
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pPr.append(shd)
    return p


# ═══════════════════════════════════════════════════════════════════════════════
# COVER
# ═══════════════════════════════════════════════════════════════════════════════
cover = doc.add_paragraph()
cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = cover.add_run("\n\n\ncicd-gen\n")
r.bold = True
r.font.size = Pt(36)
r.font.color.rgb = RGBColor(0x1A, 0x23, 0x7E)
r2 = cover.add_run("Competitive Positioning & Differentiation\n")
r2.font.size = Pt(20)
r2.font.color.rgb = RGBColor(0x30, 0x30, 0x80)
r3 = cover.add_run("\nHow cicd-gen differs from Dagger.io, Depot, Harness, GitHub Copilot, and GitLab Duo\n\n")
r3.font.size = Pt(14)
r3.italic = True
r4 = cover.add_run("SC4079 Cloud Computing — NTU Singapore\n")
r4.font.size = Pt(12)
r5 = cover.add_run("Author: Amizzuddin Amin Chan\n")
r5.font.size = Pt(12)
r6 = cover.add_run("Date: April 4, 2026\n\n")
r6.font.size = Pt(12)
doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PURPOSE
# ═══════════════════════════════════════════════════════════════════════════════
add_heading("1. Purpose of This Document")
add_para(
    "This document positions cicd-gen against five widely-used CI/CD tooling "
    "products with overlapping capabilities: Dagger.io, Depot, Harness (AIDA), "
    "GitHub Copilot, and GitLab Duo. For each competitor the document describes "
    "what the tool does, how it approaches CI/CD automation, where cicd-gen "
    "overlaps, and where cicd-gen is fundamentally different. A consolidated "
    "feature-matrix table and a strategic differentiation summary conclude the analysis."
)

# ═══════════════════════════════════════════════════════════════════════════════
# 2. CICD-GEN SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
add_heading("2. cicd-gen in One Paragraph")
add_callout(
    "cicd-gen is a web application that takes a repository URL, scans the "
    "technology stack automatically, and uses an LLM (Gemini, Groq, or Anthropic) "
    "to generate a complete, production-ready CI/CD pipeline YAML for GitHub "
    "Actions, GitLab CI, or Jenkins. It commits the result onto a feature branch, "
    "pushes it, and then runs a self-healing background thread that watches GitHub "
    "Actions runs — automatically requesting LLM-generated fixes and re-pushing "
    "until the pipeline passes, with no manual intervention required.",
    fill="E8EAF6",
)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. COMPETITOR PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
add_heading("3. Competitor Profiles")

# ── 3.1 Dagger.io ────────────────────────────────────────────────────────────
add_heading("3.1  Dagger.io", level=2)
add_para("Website: https://dagger.io  |  Founded: 2022  |  Model: Open-source core + Dagger Cloud (paid)")
add_heading("What it does", level=3)
add_para(
    "Dagger is a programmable CI/CD engine that executes pipelines inside "
    "containers. Instead of writing YAML, developers write pipeline logic in a "
    "real programming language (Go, Python, TypeScript, Java, PHP, Rust, Elixir, "
    "or .NET) using Dagger SDKs. The Dagger runtime serialises this into a Directed "
    "Acyclic Graph (DAG) of containerised steps, caches intermediate layers "
    "automatically, and can run the same pipeline locally, in CI, or in the cloud "
    "without any configuration changes."
)
add_heading("Core capabilities", level=3)
for b in [
    "Code-first pipelines: full programming language instead of YAML — loops, conditionals, typed functions",
    "Local-first: identical execution on laptop and CI server (only dependency: Linux kernel + container runtime)",
    "Automatic fine-grained caching: every function output is cached by input hash; re-runs only changed steps",
    "Daggerverse: a registry of reusable pipeline modules shared by the community",
    "Dagger Cloud: hosted observability (traces, logs, distributed cache) — paid tier",
    "SDKs for 8 languages; interactive REPL for live debugging",
    "Used in production by Adobe, CERN, Grafana Labs, Ubisoft, NVIDIA",
]:
    add_bullet(b)
add_heading("How it differs from cicd-gen", level=3)
add_table(
    ["Dimension", "Dagger.io", "cicd-gen"],
    [
        [
            "Primary abstraction",
            "Code (Go/Python/TS/...) — pipelines as typed functions",
            "YAML (GitHub Actions / GitLab CI / Jenkins) committed to the repo",
        ],
        [
            "User skill required",
            "Must write and maintain pipeline code in a real language",
            "No prior CI/CD knowledge needed — LLM generates everything from a URL",
        ],
        [
            "Execution model",
            "Containerised DAG engine runs the pipeline directly",
            "Standard platform runners (GitHub-hosted ubuntu-latest, GitLab runners)",
        ],
        [
            "AI involvement",
            "None — Dagger is a deterministic execution engine",
            "Core value-add: LLM generates, and self-heals, the entire pipeline",
        ],
        [
            "Self-healing",
            "Not a feature: errors are debugged manually via REPL/logs",
            "Automatic: CI failures trigger LLM fix -> push -> re-run loop",
        ],
        [
            "Setup effort",
            "Install Dagger CLI, write SDK code, integrate with CI",
            "Open browser, paste repo URL, click Generate",
        ],
        [
            "Vendor lock-in",
            "Pipelines are portable across any CI platform (use Dagger as runner)",
            "Generates standard YAML — no runtime dependency on cicd-gen after push",
        ],
        [
            "Target audience",
            "Senior DevOps / platform engineers wanting portable, reusable pipelines",
            "Any developer who wants a working CI pipeline in minutes",
        ],
        ["Open source", "Yes (Apache 2.0)", "Yes (university project, internal)"],
    ],
)
add_callout(
    "Key insight: Dagger replaces YAML with code — cicd-gen generates YAML from "
    "code analysis and LLM reasoning. They solve adjacent but different problems. "
    "A team using Dagger still needs to write and maintain pipeline logic; "
    "cicd-gen removes that authoring step entirely."
)

# ── 3.2 Depot ────────────────────────────────────────────────────────────────
add_heading("3.2  Depot", level=2)
add_para("Website: https://depot.dev  |  Founded: 2022 (YC W22)  |  Model: SaaS, pay-per-second billing")
add_heading("What it does", level=3)
add_para(
    "Depot is a build acceleration platform with two primary products: "
    "(1) Depot CI — a drop-in GitHub Actions / GitLab CI replacement runner with "
    "30% faster CPUs, 10x faster networking, unrestricted concurrency, parallel "
    "steps, built-in distributed caching, SSH debugging, and snapshotting; and "
    "(2) Depot Container Builds — a remote Docker build service with automatic "
    "layer caching and native Intel/Arm cross-platform support (replaces "
    "docker build with depot build). "
    "Depot's headline claim is up to 40x faster Docker builds and up to 10x "
    "faster GitHub Actions runs compared to standard GitHub-hosted runners."
)
add_heading("Core capabilities", level=3)
for b in [
    "Depot CI: parallel steps, built-in caching, SSH debugging, custom images, per-second billing, Switchyard orchestration",
    "Container builds: automatic layer caching, Intel+Arm cross-platform builds — drop-in replacement for docker build",
    "Distributed remote cache: shared across team and CI (Bazel, Go, Gradle, Turborepo, sccache, Pants)",
    "Build API: gRPC/HTTP API to programmatically build container images for platform products",
    "Supports GitHub Actions syntax — existing workflows run on Depot runners without rewriting",
    "No pipeline authoring — Depot accelerates pipelines that already exist",
]:
    add_bullet(b)
add_heading("How it differs from cicd-gen", level=3)
add_table(
    ["Dimension", "Depot", "cicd-gen"],
    [
        [
            "Core problem solved",
            "Speed: makes existing pipelines faster",
            "Authoring: creates the pipeline from scratch when none exists",
        ],
        [
            "AI involvement",
            "None — purely infrastructure and caching optimisation",
            "Core: LLM generates the pipeline and heals failures",
        ],
        [
            "Pipeline creation",
            "Does not generate pipelines — requires existing YAML",
            "Generates complete YAML from repo scan, no prior YAML needed",
        ],
        ["Self-healing", "Not a feature", "Automatic failure detection -> LLM fix -> re-push loop"],
        [
            "On-premise / local",
            "Cloud SaaS only; runners hosted in AWS",
            "Runs fully on-premise (localhost:8050); no cloud account required",
        ],
        [
            "Cost model",
            "Per-second billing; free trial 7 days",
            "Free (open-source); LLM usage within LLM provider free tiers",
        ],
        [
            "Docker",
            "Accelerates docker build (depot build)",
            "Generates the Dockerfile + CI step that calls docker build",
        ],
        [
            "Complementarity",
            "——",
            "Highly complementary: cicd-gen generates the pipeline YAML; Depot can then run it faster",
        ],
    ],
)
add_callout(
    "Key insight: Depot and cicd-gen are complementary, not competing. "
    "cicd-gen creates the pipeline yaml that calls docker build; "
    "Depot makes that same pipeline run up to 40x faster. "
    "A team could use cicd-gen to bootstrap and then switch to Depot runners."
)

# ── 3.3 Harness ──────────────────────────────────────────────────────────────
add_heading("3.3  Harness (AIDA — AI Development Assistant)", level=2)
add_para("Website: https://harness.io  |  Founded: 2017  |  Model: Enterprise SaaS / self-managed")
add_heading("What it does", level=3)
add_para(
    "Harness is a full software delivery platform covering CI, CD, Feature Flags, "
    "Cloud Cost Management, Security Testing, STO, and Error Tracking. Its AI "
    "layer — AIDA (AI Development Assistant) — adds: "
    "(1) auto-remediation of failed pipelines by reading error logs and suggesting "
    "shell command fixes; (2) AI-generated pipeline YAML from a natural language "
    "description; (3) security vulnerability explanation and auto-fix; and "
    "(4) log analysis that surfaces root cause automatically."
)
add_heading("Core capabilities", level=3)
for b in [
    "Full software delivery platform: CI, CD, chaos engineering, feature flags, cost management",
    "AIDA auto-remediation: reads failed step logs, generates a suggested remediation command shown in the UI",
    "AIDA pipeline generation: describe a pipeline in plain English -> Harness generates YAML within its own platform",
    "AIDA log intelligence: correlates failure patterns across pipeline history",
    "Enterprise: RBAC, SSO, audit trails, on-premise deployment, SOC 2 compliance",
    "Hundreds of built-in integrations (Kubernetes, Terraform, AWS, GCP, Azure, Jira, Slack, ...)",
    "Paid product — no meaningful free tier for self-hosted CI",
]:
    add_bullet(b)
add_heading("How it differs from cicd-gen", level=3)
add_table(
    ["Dimension", "Harness + AIDA", "cicd-gen"],
    [
        [
            "Scope",
            "End-to-end software delivery platform (CI + CD + security + cost)",
            "Focused tool: pipeline YAML generation + self-healing only",
        ],
        [
            "AI pipeline generation",
            "Natural language -> Harness-native YAML (runs on Harness runners)",
            "Repo scan -> standard YAML for GitHub Actions / GitLab CI / Jenkins (no vendor lock-in)",
        ],
        [
            "Self-healing",
            "AIDA suggests a fix in UI — engineer still reviews and applies it manually",
            "Fully autonomous: fix is applied, committed, and re-pushed with no human in the loop",
        ],
        [
            "Target platform",
            "Harness CI/CD platform only",
            "GitHub Actions, GitLab CI, Jenkins — standard platforms most teams already use",
        ],
        ["Cost", "Enterprise pricing; free tier very limited", "Free; LLM costs within free tier for typical use"],
        [
            "Setup",
            "Account, org, pipelines, delegates all configured in Harness UI",
            "Docker container or python dashboard.py; no cloud account needed",
        ],
        [
            "Vendor lock-in",
            "High: pipelines in Harness YAML notation, run on Harness",
            "None: output is standard GitHub Actions / GitLab CI / Jenkinsfile",
        ],
        ["University / SOME fit", "Overkill; steep learning curve", "Designed for low-friction onboarding"],
    ],
)
add_callout(
    "Key insight: Harness AIDA is powerful but requires platform buy-in. "
    "cicd-gen is opinionated about zero lock-in — all output is standard YAML "
    "that works on free GitHub Actions runners. Self-healing in cicd-gen is "
    "fully autonomous; in Harness it is advisory."
)

# ── 3.4 GitHub Copilot ──────────────────────────────────────────────────────
add_heading("3.4  GitHub Copilot (Copilot for CI / Workspace)", level=2)
add_para("Website: https://github.com/features/copilot  |  Owner: Microsoft/GitHub  |  Model: $10-19/month")
add_heading("What it does", level=3)
add_para(
    "GitHub Copilot is a general-purpose AI coding assistant embedded in VS Code, "
    "JetBrains, and github.com. It can suggest GitHub Actions workflow YAML inline "
    "as the developer types, explain existing workflow failures in plain English "
    "via Copilot Chat, and (in Copilot Workspace preview) draft multi-file code "
    "changes — including CI configuration — from a natural language issue description. "
    "It does not scan repositories, does not commit autonomously, and does not "
    "self-heal CI runs."
)
add_heading("Core capabilities", level=3)
for b in [
    "Inline YAML completion: suggests CI steps, actions, and syntax as developer types in editor",
    "Copilot Chat: ask 'why did my CI fail?' — returns plain English explanation of the last run log",
    "Copilot Workspace (preview): draft code + CI changes from a GitHub Issue description",
    "Multi-language code generation across the entire codebase",
    "Deep GitHub integration: reads repo context (README, code, issues) to tailor suggestions",
    "No autonomous commits, no push, no self-healing loop",
]:
    add_bullet(b)
add_heading("How it differs from cicd-gen", level=3)
add_table(
    ["Dimension", "GitHub Copilot", "cicd-gen"],
    [
        [
            "Interaction model",
            "Assistive: suggests, developer accepts/rejects in editor",
            "Autonomous: scans repo, generates, commits, pushes, self-heals — no editor open",
        ],
        [
            "CI YAML generation",
            "Inline suggestions while typing; developer still authors the file",
            "Complete file generated from zero-input scan; no manual authoring",
        ],
        [
            "Repository scan",
            "Uses open editor files and repo context implicitly",
            "Explicit, structured scan: languages, frameworks, tests, package managers, deploy targets",
        ],
        [
            "Commit & push",
            "Never: developer must stage, commit, and push manually",
            "Always: commits on feature branch and pushes automatically",
        ],
        [
            "Self-healing",
            "Chat can explain errors; developer must fix and push manually",
            "Fully autonomous fix loop: detects failure, generates fix, commits, pushes, waits for result",
        ],
        ["Multi-platform", "Primarily GitHub Actions (GitHub-native)", "GitHub Actions, GitLab CI, Jenkins"],
        [
            "Docker generation",
            "Can suggest Dockerfile snippets on request",
            "Generates complete multi-language Dockerfile + docker-compose.yml automatically",
        ],
        ["Cost", "$10/month (individual) or $19/month (business)", "Free; LLM provider free tiers used"],
        ["Offline / on-premise", "No — requires GitHub.com connection", "Yes — runs entirely on localhost"],
    ],
)
add_callout(
    "Key insight: Copilot assists a developer who is actively writing CI YAML. "
    "cicd-gen works with no editor open and no CI knowledge — it produces a "
    "complete, committed, pushed, and self-healing pipeline from just a repository URL."
)

# ── 3.5 GitLab Duo ──────────────────────────────────────────────────────────
add_heading("3.5  GitLab Duo (CI/CD AI features)", level=2)
add_para(
    "Website: https://docs.gitlab.com/ee/user/gitlab_duo  |  Owner: GitLab Inc.  |  Model: GitLab Premium/Ultimate"
)
add_heading("What it does", level=3)
add_para(
    "GitLab Duo is GitLab's suite of AI-assisted features embedded in the GitLab "
    "platform. For CI/CD it offers: (1) Duo Chat — answer questions about pipeline "
    "failures and suggest fixes in a chat sidebar; (2) CI/CD component catalogue — "
    "a library of reusable pipeline components; (3) Root Cause Analysis — Duo "
    "automatically analyses a failed pipeline job and proposes a root cause; and "
    "(4) Vulnerability Explanation. GitLab also has the CI Catalog for reusing "
    "pipeline templates. All features require GitLab Premium or Ultimate."
)
add_heading("Core capabilities", level=3)
for b in [
    "Duo Chat: ask questions about CI failures inside the GitLab UI; get plain English root cause",
    "Root Cause Analysis: one-click AI analysis of a failed job log — suggests most likely cause",
    "CI/CD Component Catalogue: reusable pipeline components published to a registry",
    "Auto DevOps: GitLab's template-based auto-pipeline feature (no AI — rule-based detection)",
    "Does not commit or push fixes autonomously — advisory only",
    "GitLab-only: all features work exclusively within the GitLab platform",
]:
    add_bullet(b)
add_heading("How it differs from cicd-gen", level=3)
add_table(
    ["Dimension", "GitLab Duo", "cicd-gen"],
    [
        ["Platform", "GitLab only (SaaS or self-managed)", "GitHub Actions, GitLab CI, Jenkins — any platform"],
        [
            "Generation",
            "Auto DevOps uses rule-based templates (not LLM); Duo Chat advises but does not generate a full file",
            "LLM-generated, tailored YAML based on actual repo scan — not templates",
        ],
        [
            "Self-healing",
            "Root Cause Analysis is advisory: developer reads it and manually fixes",
            "Fully autonomous: fix written, committed, and pushed without human action",
        ],
        [
            "Commit autonomy",
            "None — all Duo suggestions require manual action",
            "Full: scans, generates, commits, pushes, monitors, fixes automatically",
        ],
        ["Multi-platform support", "GitLab CI only", "GitHub Actions, GitLab CI, Jenkins"],
        ["Cost", "GitLab Premium ($29/user/mo) or Ultimate ($99/user/mo)", "Free"],
        ["On-premise", "GitLab self-managed (complex setup)", "Single python dashboard.py process on localhost"],
    ],
)
add_callout(
    "Key insight: GitLab Duo's Root Cause Analysis is the closest feature to "
    "cicd-gen's self-healing loop — but it is advisory and manual. "
    "cicd-gen's loop is fully autonomous and platform-agnostic."
)

# ═══════════════════════════════════════════════════════════════════════════════
# 4. CONSOLIDATED FEATURE MATRIX
# ═══════════════════════════════════════════════════════════════════════════════
add_heading("4. Consolidated Feature Matrix")
add_table(
    ["Feature", "cicd-gen", "Dagger.io", "Depot", "Harness AIDA", "GitHub Copilot", "GitLab Duo"],
    [
        [
            "Generates pipeline YAML from zero",
            "YES Full",
            "NO",
            "NO",
            "PARTIAL In Harness notation",
            "PARTIAL Inline assist",
            "PARTIAL Template only",
        ],
        ["Uses LLM for generation", "YES", "NO", "NO", "YES", "YES", "YES"],
        [
            "Automatic repo scan (language/framework)",
            "YES",
            "NO",
            "NO",
            "NO",
            "PARTIAL Implicit",
            "PARTIAL Auto DevOps",
        ],
        ["Commits & pushes autonomously", "YES", "NO", "NO", "NO", "NO", "NO"],
        ["Autonomous self-healing loop", "YES", "NO", "NO", "PARTIAL Advisory", "PARTIAL Advisory", "PARTIAL Advisory"],
        ["Supports GitHub Actions output", "YES", "YES (runs on)", "YES (runs on)", "NO", "YES", "NO"],
        ["Supports GitLab CI output", "YES", "YES (runs on)", "PARTIAL Beta", "NO", "NO", "YES"],
        ["Supports Jenkins output", "YES", "YES (runs on)", "NO", "YES", "NO", "NO"],
        ["Generates Dockerfile", "YES Multi-lang", "NO", "PARTIAL Accel", "NO", "PARTIAL Snippet", "NO"],
        ["Pre-commit integration", "YES Auto-run", "NO", "NO", "NO", "NO", "NO"],
        ["Runs fully on-premise / localhost", "YES", "YES", "NO SaaS", "PARTIAL Self-mgd", "NO", "PARTIAL Self-mgd"],
        ["No vendor lock-in after push", "YES", "NO runtime", "PARTIAL", "NO", "YES", "NO"],
        ["Free to use", "YES", "YES OSS core", "PARTIAL Trial", "NO", "NO $10/mo", "NO $29+/mo"],
        ["Code-first / programmatic pipelines", "NO", "YES", "NO", "NO", "NO", "NO"],
        ["Build acceleration / caching", "NO", "YES", "YES 40x", "NO", "NO", "NO"],
        ["Enterprise RBAC / audit trails", "NO", "PARTIAL Cloud", "YES", "YES", "YES", "YES"],
    ],
    header_color="1a237e",
    alt_color="E8EAF6",
)
add_para("YES = Full support   PARTIAL = Partial / advisory / requires setup   NO = Not available")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. STRATEGIC DIFFERENTIATION
# ═══════════════════════════════════════════════════════════════════════════════
add_heading("5. Strategic Differentiation Summary")
add_heading("5.1  What makes cicd-gen unique", level=2)

diffs = [
    (
        "Zero-knowledge onboarding",
        "The user does not need to know any CI/CD syntax, which actions or stages to "
        "use, or even which languages are in their repo. cicd-gen discovers all of "
        "this automatically and produces a complete, working pipeline file in under 60 seconds.",
    ),
    (
        "Fully autonomous end-to-end",
        "Every competitor either stops at suggestion (GitHub Copilot, GitLab Duo, "
        "Harness AIDA) or stops at execution (Dagger, Depot). cicd-gen is the only "
        "tool in this comparison that scans, generates, commits, pushes, monitors, "
        "fixes, and re-pushes — the full lifecycle — autonomously.",
    ),
    (
        "Platform-agnostic, zero lock-in",
        "The generated output is vanilla GitHub Actions YAML, standard .gitlab-ci.yml, "
        "or a plain Jenkinsfile. Once pushed, there is no runtime dependency on "
        "cicd-gen. Teams can edit or delete what cicd-gen created using their standard CI platform tools.",
    ),
    (
        "Self-healing loop with autonomous commits",
        "The closest competitor feature is Harness AIDA auto-remediation and "
        "GitLab Duo Root Cause Analysis — but both are advisory. cicd-gen's heal loop "
        "applies the LLM-generated fix, commits it with a traceable message "
        '("ci(fix): auto-fix attempt N via cicd-gen"), and pushes it without any human in the loop.',
    ),
    (
        "Multi-language Dockerfile generation",
        "None of the compared tools automatically generate a production-ready "
        "multi-language Dockerfile that installs all stack runtimes in a single image. "
        "cicd-gen produces this as an optional artefact alongside the pipeline YAML.",
    ),
    (
        "Pre-commit integration baked in",
        "cicd-gen automatically generates a .pre-commit-config.yaml and runs "
        "pre-commit before every commit (locally). This ensures trailing-whitespace, "
        "end-of-file-fixer, check-yaml, and language-specific formatters pass "
        "before code ever reaches the remote — reducing CI noise from trivial formatting failures.",
    ),
    (
        "Output sanitisers prevent known LLM failure modes",
        "_sanitize_expressions() and _sanitize_runner() are hard post-processing "
        "filters applied to every LLM-generated YAML. These address real, recurring "
        "LLM output bugs (bad expression syntax, deprecated runner labels) that "
        "would otherwise silently cause CI to break. No other tool in this comparison "
        "applies deterministic rules on top of LLM output.",
    ),
]
for title, body in diffs:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(f"{title}:  ")
    r.bold = True
    r.font.size = Pt(11)
    r2 = p.add_run(body)
    r2.font.size = Pt(11)

doc.add_paragraph()
add_heading("5.2  Where cicd-gen is weaker", level=2)
weaknesses = [
    (
        "No build acceleration",
        "Depot can make pipelines run up to 40x faster. cicd-gen does not touch runner infrastructure; it only produces the pipeline YAML.",
    ),
    (
        "No code-first / programmatic pipelines",
        "Dagger allows pipelines to be written in a real programming language with full IDE support, type checking, and unit tests. cicd-gen always outputs YAML.",
    ),
    (
        "No enterprise features",
        "Harness and GitLab provide RBAC, SSO, audit logging, compliance controls, and multi-team governance. cicd-gen has none of these.",
    ),
    (
        "LLM token limits",
        "Complex repositories with many languages may produce prompts that exhaust free-tier token quotas (Groq: 100 000 TPD). If the quota is exceeded, self-healing stops mid-attempt.",
    ),
    (
        "GitHub Actions only for self-healing",
        "The CI watch-and-heal loop currently supports GitHub Actions only. GitLab CI and Jenkins self-healing are not yet implemented.",
    ),
]
for title, body in weaknesses:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(f"{title}:  ")
    r.bold = True
    r.font.size = Pt(11)
    r2 = p.add_run(body)
    r2.font.size = Pt(11)

# ═══════════════════════════════════════════════════════════════════════════════
# 6. IDEAL USER PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
doc.add_paragraph()
add_heading("6. Ideal User Profiles — Who Should Use Which Tool")
add_table(
    ["User Profile", "Best Tool", "Why"],
    [
        [
            "Developer with no CI/CD experience who needs a working pipeline fast",
            "cicd-gen",
            "Zero configuration, no YAML knowledge needed, auto-commits and auto-heals",
        ],
        [
            "Platform engineer wanting portable, reusable pipelines in real code",
            "Dagger.io",
            "Code-first SDK, 8 languages, reproducible DAG, Daggerverse reuse",
        ],
        [
            "Team with existing pipelines wanting faster builds",
            "Depot",
            "40x faster Docker builds, 10x faster Actions runners, drop-in replacement",
        ],
        [
            "Large enterprise needing end-to-end delivery with compliance",
            "Harness",
            "Full software delivery platform, RBAC, audit logs, multi-cloud CD",
        ],
        [
            "GitHub user who prefers guided in-editor CI authoring",
            "GitHub Copilot",
            "Inline YAML completions and chat explanations within GitHub/VS Code",
        ],
        [
            "GitLab-native team wanting AI help understanding failures",
            "GitLab Duo",
            "Root Cause Analysis and Duo Chat integrated directly in GitLab UI",
        ],
        [
            "Team wanting quick bootstrap then long-term optimisation",
            "cicd-gen then Depot",
            "cicd-gen generates the pipeline YAML; Depot makes it run faster afterward",
        ],
    ],
)

# ═══════════════════════════════════════════════════════════════════════════════
# 7. REFERENCES
# ═══════════════════════════════════════════════════════════════════════════════
add_heading("7. References")
for ref in [
    "Dagger.io official website — https://dagger.io",
    "Dagger documentation — https://docs.dagger.io",
    "Depot official website — https://depot.dev",
    "Depot CI documentation — https://depot.dev/docs/ci/overview",
    "Harness AIDA — https://www.harness.io/products/ai-development-assistant",
    "GitHub Copilot — https://github.com/features/copilot",
    "GitLab Duo — https://docs.gitlab.com/ee/user/gitlab_duo",
    "GitLab Auto DevOps — https://docs.gitlab.com/ee/topics/autodevops/",
    "cicd-gen source — /root/sc4052/workspace/project/ (this repository)",
]:
    add_bullet(ref)

out = "/root/sc4052/workspace/project/docs/cicd_gen_competitive_analysis.docx"
doc.save(out)
print(f"Saved: {out}  ({os.path.getsize(out) // 1024} KB)")
