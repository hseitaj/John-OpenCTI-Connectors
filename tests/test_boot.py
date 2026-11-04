"""Every connector boots through its real entrypoint, offline.

Each connector runs in its own process (several share module names such as
``main`` or ``src``) via tests/run_connector.py in boot mode: a fake OpenCTI
helper, no network. Passing means configuration loads, the helper is built,
graph references resolve, and the connector reaches its source or registers
its listener without an error. See run_connector.py for the details.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REGISTRY = json.loads((HERE / "connectors.json").read_text())
RUNNABLE = sorted(name for name, spec in REGISTRY.items() if "skip" not in spec)


def boot(name: str) -> dict:
    proc = subprocess.run([sys.executable, str(HERE / "run_connector.py"), name, "--mode", "boot"],
                          capture_output=True, text=True, timeout=300)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, f"{name}: runner produced no result\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return json.loads(lines[-1][len("RESULT "):])


@pytest.mark.parametrize("name", RUNNABLE)
def test_connector_boots(name):
    result = boot(name)
    assert result["helper_built"], f"{name}: never built its OpenCTI helper\n{result['detail']}"
    assert result["ok"], (
        f"{name}: outcome={result['outcome']} errors={result['errors']}\n"
        f"detail: {result['detail']}\nstdout: {result['stdout']}\nstderr: {result['stderr']}")


def test_registry_covers_every_connector():
    connectors = {p.name for p in (HERE.parent / "connectors").iterdir()
                  if p.is_dir() and p.name != "microservices"}
    assert connectors == set(REGISTRY), "tests/connectors.json is out of date with connectors/"
    for name in RUNNABLE:
        assert (HERE.parent / "connectors" / name / REGISTRY[name]["entry"]).is_file(), name
