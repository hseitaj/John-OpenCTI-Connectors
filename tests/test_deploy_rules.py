"""Static checks on Dockerfiles, compose files and requirements.

Each rule here is a class of bug that shipped at least once:

* the shared microservices package was not copied into 42 images;
* a Dockerfile copied a file deleted from the repo (report_enrichment);
* a base image reached end of life and stopped building (openphish, bullseye);
* pycti pins drifted from the platform version (6.2.7, 6.3.2, 6.9.5 ...);
* compose files documented variables the code never reads (the CVE connector
  documented upstream's CVE_API_KEY, so the NVD key was silently unused);
* regexes held a literal backspace character instead of \\b (report_model_qa).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONNECTORS = ROOT / "connectors"
REGISTRY = json.loads((ROOT / "tests" / "connectors.json").read_text())
PLATFORM_PYCTI = "6.9.13"
ACTIVE = sorted(n for n, spec in REGISTRY.items() if "skip" not in spec)


def dockerfiles():
    for name in ACTIVE:
        for df in sorted((CONNECTORS / name).glob("Dockerfile*")):
            yield pytest.param(name, df, id=f"{name}/{df.name}")


def build_context(name: str, dockerfile: Path) -> Path:
    """connectors/ for builds that run from there (compose context .., Cloud Build), else the connector dir."""
    compose = CONNECTORS / name / "docker-compose.yml"
    if dockerfile.name == "Dockerfile.cloudbuild":
        return CONNECTORS
    if compose.exists() and re.search(r"^\s+context:\s*\.\.\s*$", compose.read_text(), re.M):
        return CONNECTORS
    return CONNECTORS / name


def uses_microservices(name: str) -> bool:
    return any(re.search(r"^\s*(from|import) microservices", p.read_text(errors="ignore"), re.M)
               for p in (CONNECTORS / name).rglob("*.py"))


@pytest.mark.parametrize("name,dockerfile", list(dockerfiles()))
def test_every_copy_source_exists(name, dockerfile):
    ctx = build_context(name, dockerfile)
    for line in dockerfile.read_text().splitlines():
        m = re.match(r"\s*(?:COPY|ADD)\s+(?!--from)(.+)$", line)
        if not m:
            continue
        parts = [p for p in m.group(1).split() if not p.startswith("--")]
        for src in parts[:-1]:
            assert (ctx / src).exists(), f"{dockerfile}: COPY source {src!r} does not exist in {ctx}"


@pytest.mark.parametrize("name", [n for n in ACTIVE if uses_microservices(n)])
def test_microservices_reach_the_image(name):
    for df in (CONNECTORS / name).glob("Dockerfile*"):
        text = df.read_text()
        assert re.search(r"^COPY (--from=microservices \.|microservices) /opt/shared/microservices", text, re.M), \
            f"{df}: imports microservices but does not copy it into the image"
        assert re.search(r'^ENV PYTHONPATH="?/opt/shared', text, re.M), f"{df}: /opt/shared not on PYTHONPATH"
    compose = CONNECTORS / name / "docker-compose.yml"
    if compose.exists() and "build:" in compose.read_text():
        assert "microservices: ../microservices" in compose.read_text(), \
            f"{compose}: builds the image but does not pass the microservices build context"


@pytest.mark.parametrize("name,dockerfile", list(dockerfiles()))
def test_base_image_is_supported(name, dockerfile):
    for base in re.findall(r"^FROM\s+(\S+)", dockerfile.read_text(), re.M):
        assert "bullseye" not in base and "buster" not in base, f"{dockerfile}: Debian base past end of life: {base}"
        m = re.match(r"python:3\.(\d+)", base)
        assert not m or int(m.group(1)) >= 10, f"{dockerfile}: Python past end of life: {base}"


@pytest.mark.parametrize("name,dockerfile", list(dockerfiles()))
def test_playwright_matches_its_image(name, dockerfile):
    image = re.search(r"playwright/python:v([\d.]+)", dockerfile.read_text())
    if not image:
        return
    reqs = "\n".join(p.read_text() for p in (CONNECTORS / name).rglob("requirements*.txt"))
    pin = re.search(r"^playwright==([\d.]+)", reqs, re.M)
    assert pin and pin.group(1) == image.group(1), (
        f"{name}: base image ships Playwright {image.group(1)} browsers; pip must pin playwright=={image.group(1)} "
        f"(found {pin.group(0) if pin else 'no pin'})")


@pytest.mark.parametrize("name", ACTIVE)
def test_pycti_matches_the_platform(name):
    for req in (CONNECTORS / name).rglob("requirements*.txt"):
        for line in req.read_text().splitlines():
            line = line.strip() if line.startswith("connectors-sdk") else line.split("#")[0].strip()
            if line.lower().startswith("pycti"):
                assert line == f"pycti=={PLATFORM_PYCTI}", f"{req}: {line} (platform is {PLATFORM_PYCTI})"
            if line.startswith("connectors-sdk"):
                assert f"@{PLATFORM_PYCTI}#" in line, f"{req}: connectors-sdk not at {PLATFORM_PYCTI}"


@pytest.mark.parametrize("name", ACTIVE)
def test_weasyprint_is_pinned_below_70(name):
    # microservices/make_pdf.py passes WeasyPrint a function url_fetcher returning
    # dicts and calls weasyprint.default_url_fetcher. WeasyPrint 70 removed both
    # (fetchers must return URLFetcherResponse), so an unpinned install fails
    # every render that loads an image (OCCRP: 474 of 474 articles).
    for req in (CONNECTORS / name).rglob("requirements*.txt"):
        for line in req.read_text().splitlines():
            line = line.split("#")[0].strip()
            if re.match(r"(?i)weasyprint\b", line):
                m = re.match(r"(?i)weasyprint==(\d+)", line)
                assert m and int(m.group(1)) < 70, f"{req}: {line!r} must pin a WeasyPrint release below 70"


@pytest.mark.parametrize("name", [n for n in ACTIVE if (CONNECTORS / n / "docker-compose.yml").exists()])
def test_compose_documents_only_variables_the_code_reads(name):
    sources = list((CONNECTORS / name).rglob("*.py")) + list((CONNECTORS / "microservices").rglob("*.py"))
    if name == "report_enrichment":  # its image also carries report_model_qa modules
        sources += list((CONNECTORS / "report_model_qa").rglob("*.py"))
    code = "\n".join(p.read_text(errors="ignore") for p in sources)
    doc = yaml.safe_load((CONNECTORS / name / "docker-compose.yml").read_text()) or {}
    for service in (doc.get("services") or {}).values():
        env = service.get("environment") or []
        keys = list(env) if isinstance(env, dict) else [str(e).split("=", 1)[0].strip() for e in env]
        unread = [k for k in keys if not k.startswith(("OPENCTI_", "CONNECTOR_")) and k != "PYTHONPATH"
                  and k not in code and not pydantic_field(k, code)]
        assert not unread, f"{name}/docker-compose.yml documents variables nothing reads: {unread}"


def pydantic_field(key: str, code: str) -> bool:
    """pydantic-settings maps PREFIX_FIELD_NAME onto a ``field_name:`` declaration (feedly)."""
    field = key.split("_", 1)[1].lower() if "_" in key else ""
    return bool(field) and re.search(rf"^\s+{re.escape(field)}\s*:", code, re.M) is not None


def test_no_control_characters_in_source():
    bad = [str(p.relative_to(ROOT)) for p in CONNECTORS.rglob("*.py")
           if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", p.read_text(errors="ignore"))]
    assert not bad, f"literal control characters (a \\b typed inside a regex?) in: {bad}"
