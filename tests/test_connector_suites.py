"""Run each connector's own unit tests, in its own process and directory.

The suites import ``main`` / ``src`` / ``test_main`` by bare name, so they
cannot share one pytest session.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

CONNECTORS = Path(__file__).resolve().parent.parent / "connectors"
SUITES = sorted(
    {p.parent if p.parent.name == "tests" else p for p in CONNECTORS.rglob("test_*.py")},
    key=str,
)


def workdir(suite: Path) -> Path:
    """Where the suite expects to run: next to a single test file, else the connector root."""
    if suite.is_file():
        return suite.parent
    return CONNECTORS / suite.relative_to(CONNECTORS).parts[0]


@pytest.mark.parametrize("suite", SUITES, ids=lambda s: str(s.relative_to(CONNECTORS)))
def test_connector_suite_passes(suite):
    cwd = workdir(suite)
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(suite)],
                          cwd=cwd, capture_output=True, text=True, timeout=600,
                          env={**__import__("os").environ, "PYTHONPATH": f"{cwd}:{CONNECTORS}"})
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
