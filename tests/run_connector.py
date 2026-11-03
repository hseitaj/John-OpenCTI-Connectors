"""Boot one connector through its real ``__main__`` with a fake OpenCTI.

    python tests/run_connector.py NAME [--mode boot|live] [--stop-after N] [--env KEY=VALUE ...]

The connector runs exactly as its container would (same entry file, same
``if __name__ == "__main__"`` block) with three substitutions:

* ``pycti.OpenCTIConnectorHelper`` is the recording fake from fake_opencti.py,
  so nothing touches a real platform or RabbitMQ;
* ``connectors/`` is importable, as /opt/shared is in the images, so the shared
  ``microservices`` package resolves;
* ``time.sleep`` cannot stall the run.

Modes:

boot  (offline, used by CI) Network is blocked. The run stops at the first
      outbound connection, or when a listener / scheduler is registered. That
      proves configuration loads, the helper is built, graph references resolve
      and the connector reaches its source or its message loop, all without
      leaving the machine.
live  Real network. Short sleeps are skipped; the first long (poll) sleep ends
      the run, and so does the Nth report or bundle written (--stop-after,
      default 2). That proves source fetch -> parse -> write for real.

The last stdout line is ``RESULT {json}``.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import runpy
import socket
import sys
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONNECTORS = ROOT / "connectors"
sys.path.insert(0, str(HERE))

import fake_opencti  # noqa: E402
from fake_opencti import FakeHelper, StopCycle  # noqa: E402

SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CLIENT_ID", "USERNAME", "EMAIL", "ACCOUNT")
POLL_SLEEP = 60  # seconds; anything this long is a poll interval, not a politeness delay


class NetworkBlocked(OSError):
    pass


def registry() -> dict:
    return json.loads((HERE / "connectors.json").read_text())


def compose_env(cdir: Path) -> dict[str, str]:
    """The environment a connector's docker-compose.yml documents, with test values for blanks."""
    import yaml

    env: dict[str, str] = {}
    path = cdir / "docker-compose.yml"
    if path.exists() and path.read_text().strip():
        doc = yaml.safe_load(path.read_text()) or {}
        for svc in (doc.get("services") or {}).values():
            raw = svc.get("environment") or []
            items = raw.items() if isinstance(raw, dict) else (
                (str(i).split("=", 1) + [""])[:2] for i in raw)
            for key, value in items:
                value = "" if value is None else str(value).strip()
                if value.startswith("${"):
                    value = ""
                env[str(key).strip()] = value
    env.update(OPENCTI_URL="http://opencti.invalid", OPENCTI_BASE_URL="http://opencti.invalid",
               OPENCTI_TOKEN=str(uuid.uuid4()),
               CONNECTOR_ID=str(uuid.uuid4()))
    for key, value in list(env.items()):
        if not value:
            if any(h in key.upper() for h in SECRET_HINTS):
                env[key] = f"test-{key.lower()}"
            else:
                del env[key]  # unset: let the connector's own default apply
    return env


def assemble(spec: dict) -> Path:
    """Rebuild a container's directory layout from COPY steps (sources relative to connectors/)."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="connector-layout-"))
    for src, dst in spec["assemble"]:
        source, target = CONNECTORS / src, root / dst
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
    for rel in spec.get("assemble_touch", []):
        (root / rel).touch()
    for rel in spec.get("assemble_remove", []):
        shutil.rmtree(root / rel, ignore_errors=True)
    return root


def map_paths(mapping: dict[str, str]) -> None:
    """Serve files a container gets from a volume mount (absolute paths) from the repo."""
    import builtins

    real_open, real_exists, real_isfile = builtins.open, os.path.exists, os.path.isfile

    def remap(path):
        return mapping.get(os.fspath(path), path) if isinstance(path, (str, os.PathLike)) else path

    builtins.open = lambda file, *a, **k: real_open(remap(file), *a, **k)  # type: ignore[assignment]
    os.path.exists = lambda path: real_exists(remap(path))  # type: ignore[assignment]
    os.path.isfile = lambda path: real_isfile(remap(path))  # type: ignore[assignment]


def block_network() -> list:
    attempts: list[str] = []

    def refuse(*args, **kwargs):
        target = args[1] if len(args) > 1 else args[0] if args else kwargs
        attempts.append(str(target)[:120])
        raise StopCycle(f"network: {target}")

    # Transports that do not go through Python sockets: a headless browser and libcurl.
    os.environ.update(HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9",
                      https_proxy="http://127.0.0.1:9", http_proxy="http://127.0.0.1:9")
    try:
        import playwright.async_api
        import playwright.sync_api

        playwright.sync_api.sync_playwright = lambda *a, **k: refuse(None, "playwright (browser)")
        playwright.async_api.async_playwright = lambda *a, **k: refuse(None, "playwright (browser)")
    except ImportError:
        pass
    try:
        import curl_cffi.requests as curl

        curl.Session.request = lambda self, method, url, *a, **k: refuse(None, url)
        curl.request = lambda method, url, *a, **k: refuse(None, url)
    except ImportError:
        pass
    socket.socket.connect = refuse  # type: ignore[assignment]
    socket.socket.connect_ex = refuse  # type: ignore[assignment]
    socket.create_connection = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]
    return attempts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--mode", choices=("boot", "live"), default="boot")
    ap.add_argument("--stop-after", type=int, default=2)
    ap.add_argument("--env", action="append", default=[])
    args = ap.parse_args()

    spec = registry()[args.name]
    cdir = CONNECTORS / args.name
    if spec.get("assemble"):
        cdir = assemble(spec)
    entry = cdir / spec["entry"]
    env = compose_env(CONNECTORS / args.name)
    env.update(spec.get("env", {}))
    env.update(dict(e.split("=", 1) for e in args.env))
    if spec.get("path_map"):
        map_paths({k: str(CONNECTORS / args.name / v) for k, v in spec["path_map"].items()})
    os.environ.update(env)

    fake_opencti.install()
    FakeHelper.stop_after = args.stop_after if args.mode == "live" else 0
    FakeHelper.existing = set(spec.get("platform_has", []))

    import time

    slept: list[float] = []

    def fake_sleep(seconds=0):
        slept.append(float(seconds or 0))
        if float(seconds or 0) >= POLL_SLEEP:
            raise StopCycle(f"sleep {seconds}")

    time.sleep = fake_sleep  # type: ignore[assignment]
    attempts = block_network() if args.mode == "boot" else []

    sys.argv = [str(entry)]  # the connector parses its own argv, not ours
    sys.path[:0] = [str(entry.parent), str(cdir), str(CONNECTORS)]
    os.chdir(entry.parent)
    out, err = io.StringIO(), io.StringIO()
    outcome, detail = "returned", ""
    try:
        with redirect_stdout(out), redirect_stderr(err):
            if spec.get("module"):
                os.chdir(cdir)
                runpy.run_module(spec["module"], run_name="__main__", alter_sys=True)
            else:
                runpy.run_path(str(entry), run_name="__main__")
    except StopCycle as stop:
        outcome, detail = ("network" if str(stop).startswith("network") else
                           "sleep" if str(stop).startswith("sleep") else "write-cap"), str(stop)[:200]
    except SystemExit as ex:
        outcome, detail = "exit", f"SystemExit({ex.code})"
    except BaseException:  # noqa: BLE001
        outcome, detail = "exception", traceback.format_exc()[-3000:]

    helper = getattr(FakeHelper, "last", None)
    calls = helper.calls if helper else []
    errors = [m for lvl, m, _ in (helper.logs if helper else []) if lvl == "error"]
    result = {
        "name": args.name, "mode": args.mode, "outcome": outcome, "detail": detail,
        "helper_built": helper is not None,
        "listening": bool(helper and (helper.listen_callback or helper.scheduled)),
        "network_attempts": attempts[:3],
        "reports": sum(1 for c in calls if c[0] == "api.report.create"),
        "bundles": len(helper.bundles) if helper else 0,
        "bundle_objects": sum(len(b.get("objects", [])) for b in (helper.bundles if helper else [])),
        "files": sum(1 for c in calls if c[0].endswith(".add_file")),
        "calls": len(calls),
        "call_names": sorted({c[0] for c in calls}),
        "errors": [e[:300] for e in errors[:5]],
        "stdout": out.getvalue()[-1500:],
        "stderr": err.getvalue()[-1500:],
        "slept": slept[:5],
    }
    sys.__stdout__.write("RESULT " + json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
