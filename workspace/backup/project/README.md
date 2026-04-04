# cicd-gen — CICD-as-a-Service

AI-powered CI/CD pipeline generator. Point it at any repo, and it scans your
tech stack, calls Claude to generate a production-ready pipeline config, then
lets you iterate in plain English.

## Architecture

```
your repo
   │
   ▼
scanner.py          ← detects language, framework, tests, Docker, etc.
   │
   ▼
generator.py        ← builds structured prompt → calls Claude API → returns YAML
   │
   ▼
writer.py           ← writes YAML to .github/workflows/ci.yml (or equivalent)
   │
   ▼
cli.py  /  api.py   ← CLI (Click) or web service (FastAPI)
```

## Quickstart

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or create a `.env` file:
```
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. CLI Usage

```bash
# Scan a repo (no generation)
python cli.py scan .
python cli.py scan ~/projects/my-app

# Generate a GitHub Actions pipeline
python cli.py init .
python cli.py init ~/projects/my-app --platform github-actions

# Generate a GitLab CI pipeline
python cli.py init . --platform gitlab-ci

# Generate with extra requirements
python cli.py init . --requirements "deploy to AWS Lambda after tests pass, notify Slack on failure"

# Generate + auto-commit with git
python cli.py init . --commit

# Preview only (don't write to disk)
python cli.py init . --preview

# Interactively refine the generated pipeline
python cli.py refine .
# Then type in plain English:
#   your request > add a step to build and push a Docker image
#   your request > only run tests on pull requests
#   your request > add Slack notification on failure
#   your request > done
```

### 4. Web Service (SaaS mode)

```bash
uvicorn api:app --reload --port 8000
```

Then open **http://localhost:8000/docs** for the interactive Swagger UI.

#### Example API calls

```bash
# Scan a repo
curl -X POST "http://localhost:8000/scan?repo_path=/path/to/repo"

# Generate pipeline
curl -X POST "http://localhost:8000/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_path": "/path/to/repo",
    "platform": "github-actions",
    "extra_requirements": "deploy to Heroku on merge to main",
    "write_to_disk": false
  }'

# Refine pipeline
curl -X POST "http://localhost:8000/refine" \
  -H "Content-Type: application/json" \
  -d '{
    "current_yaml": "name: CI\n...",
    "user_request": "add a Docker build step",
    "platform": "github-actions"
  }'
```

## Supported Platforms

| Platform       | Output file                     |
|--------------- |---------------------------------|
| github-actions | `.github/workflows/ci.yml`      |
| gitlab-ci      | `.gitlab-ci.yml`                |
| jenkins        | `Jenkinsfile`                   |

## Supported Languages (auto-detected)

Python · Node.js · Go · Java · Rust · Ruby · PHP · .NET

## File Structure

```
cicd_gen/
├── scanner.py       # Repo fingerprinting
├── generator.py     # Claude API + prompt engineering
├── writer.py        # File I/O + git integration
├── cli.py           # Click CLI (cicd-gen init / refine / scan)
├── api.py           # FastAPI web service (optional SaaS layer)
├── requirements.txt
└── README.md
```

## Roadmap

- [ ] GitHub URL support (clone → scan → generate → PR)
- [ ] Docker-based local pipeline execution
- [ ] Web frontend (React)
- [ ] Support for more platforms (CircleCI, Travis CI, Azure DevOps)
- [ ] Pipeline template library
- [ ] Cost/time estimation for pipeline runs
