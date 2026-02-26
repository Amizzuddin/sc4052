"""
api.py
------
Optional FastAPI web service layer.
Exposes the scanner + generator as REST endpoints so cicd-gen can run
as a hosted SaaS rather than just a local CLI tool.

Run with:
    uvicorn api:app --reload --port 8000

Then visit: http://localhost:8000/docs  (auto-generated Swagger UI)
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from generator import SUPPORTED_PLATFORMS, generate_pipeline, refine_pipeline
from pydantic import BaseModel, Field
from scanner import scan_repo
from writer import write_config

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="cicd-gen API",
    description="AI-powered CI/CD pipeline generator as a service.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten this in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    repo_path: str = Field(..., description="Absolute path to repo on the server filesystem")
    platform: str = Field("github-actions", description=f"CI/CD platform. One of: {SUPPORTED_PLATFORMS}")
    extra_requirements: Optional[str] = Field("", description="Extra plain-English requirements")
    write_to_disk: bool = Field(False, description="If True, write the config to the repo on disk")


class GenerateResponse(BaseModel):
    repo_name: str
    platform: str
    yaml_content: str
    output_path: Optional[str] = None
    scan: dict


class RefineRequest(BaseModel):
    current_yaml: str = Field(..., description="The current YAML config as a string")
    user_request: str = Field(..., description="Plain-English change request")
    platform: str = Field("github-actions", description="CI/CD platform")


class RefineResponse(BaseModel):
    platform: str
    yaml_content: str
    lines_added: int
    lines_removed: int


class ScanResponse(BaseModel):
    repo_name: str
    language: Optional[str]
    frameworks: list[str]
    package_manager: Optional[str]
    has_tests: bool
    test_runner: Optional[str]
    deploy_targets: list[str]
    existing_ci: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/health", tags=["Meta"])
def health_check():
    """Simple liveness check."""
    return {"status": "ok", "version": "0.1.0"}


@app.post("/scan", response_model=ScanResponse, tags=["Pipeline"])
def api_scan(repo_path: str):
    """
    Scan a repository and return its detected tech stack.
    The repo must be accessible on the server's filesystem.
    """
    try:
        result = scan_repo(repo_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ScanResponse(
        repo_name=result["repo_name"],
        language=result["language"],
        frameworks=result["frameworks"],
        package_manager=result["package_manager"],
        has_tests=result["tests"]["has_tests"],
        test_runner=result["tests"].get("test_runner"),
        deploy_targets=result["deploy_targets"],
        existing_ci=result["existing_ci"],
    )


@app.post("/generate", response_model=GenerateResponse, tags=["Pipeline"])
def api_generate(req: GenerateRequest):
    """
    Scan a repository and generate a CI/CD pipeline configuration.

    Optionally write the result to disk (write_to_disk=true).
    """
    if req.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported platform '{req.platform}'. Choose from: {SUPPORTED_PLATFORMS}",
        )

    # Scan
    try:
        scan = scan_repo(req.repo_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Generate
    try:
        yaml_content = generate_pipeline(scan, req.platform, req.extra_requirements or "")
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {e}")

    # Optionally write
    output_path = None
    if req.write_to_disk:
        written = write_config(yaml_content, req.repo_path, req.platform)
        output_path = str(written)

    return GenerateResponse(
        repo_name=scan["repo_name"],
        platform=req.platform,
        yaml_content=yaml_content,
        output_path=output_path,
        scan=scan,
    )


@app.post("/refine", response_model=RefineResponse, tags=["Pipeline"])
def api_refine(req: RefineRequest):
    """
    Refine an existing pipeline config using a plain-English request.

    Send the current YAML + your change request and get back updated YAML.
    """
    if req.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported platform '{req.platform}'. Choose from: {SUPPORTED_PLATFORMS}",
        )

    try:
        updated_yaml = refine_pipeline(req.current_yaml, req.user_request, req.platform)
    except EnvironmentError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Refinement error: {e}")

    old_lines = set(req.current_yaml.splitlines())
    new_lines = set(updated_yaml.splitlines())

    return RefineResponse(
        platform=req.platform,
        yaml_content=updated_yaml,
        lines_added=len(new_lines - old_lines),
        lines_removed=len(old_lines - new_lines),
    )


# ── Dev runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
