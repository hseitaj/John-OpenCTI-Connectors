"""Import a connector's entrypoint inside its built image.

    python tests/image_probe.py CONNECTOR IMAGE

Runs the image's Python with no network and imports the entry module the
Dockerfile starts (without running its ``__main__`` block). Volume-mounted
config files from docker-compose.yml are mounted the same way. This catches
what only shows up in the container: missing COPY steps, packages absent from
requirements.txt, wrong working directories, broken relative imports.

A connector that builds its OpenCTI helper at import time gets as far as
"OpenCTI API is not reachable", which also counts as a pass: everything up to
talking to the platform worked.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = r'''
import importlib, importlib.util, os, sys, traceback
target, module = sys.argv[1], sys.argv[2]
d = os.path.dirname(target)
os.chdir(d); sys.path.insert(0, d)
try:
    if module:
        os.chdir(os.path.dirname(d)); sys.path.insert(0, os.getcwd())
        importlib.import_module(module)
    else:
        spec = importlib.util.spec_from_file_location("connector_entry", target)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    print("IMPORT_OK")
except BaseException:
    traceback.print_exc()
    print("IMPORT_FAIL")
'''


def main() -> int:
    name, image = sys.argv[1], sys.argv[2]
    spec = json.loads((ROOT / "tests" / "connectors.json").read_text())[name]
    if "skip" in spec:
        print(f"{name}: skipped ({spec['skip']})")
        return 0
    cdir = ROOT / "connectors" / name
    mounts: list[str] = []
    compose = cdir / "docker-compose.yml"
    if compose.exists():
        for m in re.finditer(r"^\s+- \./(\S+?):(/\S+?)(?::ro)?\s*$", compose.read_text(), re.M):
            mounts += ["-v", f"{cdir / m.group(1)}:{m.group(2)}:ro"]
    target = spec["container"]
    if spec.get("module"):  # python -m src.main from WORKDIR: target is <workdir>/src/main.py
        target = str(Path(target).parent / "__init__.py")
    cmd = ["docker", "run", "--rm", "--network", "none", *mounts, "--entrypoint", "python", image,
           "-c", PROBE, target, spec.get("module", "")]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    text = out.stdout + out.stderr
    print(text[-4000:])
    ok = "IMPORT_OK" in text or "OpenCTI API is not reachable" in text
    print(f"{name}: {'OK' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
