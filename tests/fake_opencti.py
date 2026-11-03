"""An in-memory stand-in for pycti's OpenCTIConnectorHelper.

Connectors import ``OpenCTIConnectorHelper`` from ``pycti`` at module load, so
``install()`` swaps the class before a connector module is imported. The fake
never talks to an OpenCTI platform or RabbitMQ: every API call is recorded in
``helper.calls`` and answered the way an empty platform would answer it
(reads find nothing, creates return a new object with an id).

Two read paths answer differently on purpose:

* TLP marking definitions always resolve, because every connector refuses to
  write without one (that is correct behaviour on a real platform).
* ``FakeHelper.stop_after`` ends a run early by raising ``StopCycle`` (a
  BaseException, so a connector's ``except Exception`` cannot swallow it) once
  that many reports or bundles have been written. Live checks use it to prove a
  full fetch -> parse -> write path without ingesting a whole backlog.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

TLP_IDS = {
    "TLP:CLEAR": "marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487",
    "TLP:WHITE": "marking-definition--613f2e26-407d-48c7-9eca-b8e91df99dc9",
    "TLP:GREEN": "marking-definition--34098fce-860f-48ae-8e50-ebd3cc5e41da",
    "TLP:AMBER": "marking-definition--f88d31f6-486f-44da-b317-01333bde0b82",
    "TLP:AMBER+STRICT": "marking-definition--826578e1-40ad-459f-bc73-ede076f81f37",
    "TLP:RED": "marking-definition--5e57c739-391a-4eb3-b6be-7d15ca92d5ed",
}


class StopCycle(BaseException):
    """Raised by the fake once a run has written enough to prove its path."""


class AutoDict(dict):
    """A GraphQL-ish answer: any missing key is another empty AutoDict."""

    def __missing__(self, key):
        return AutoDict()


class FakeLogger:
    def __init__(self, sink: list):
        self.sink = sink

    def _log(self, level, message, meta=None):
        self.sink.append((level, str(message), meta))

    def debug(self, message, meta=None):
        self._log("debug", message, meta)

    def info(self, message, meta=None):
        self._log("info", message, meta)

    def warning(self, message, meta=None):
        self._log("warning", message, meta)

    def error(self, message, meta=None):
        self._log("error", message, meta)

    warn = warning
    exception = error


class FakeEntity:
    """helper.api.<entity>: read/list find nothing, create returns an object."""

    def __init__(self, helper: "FakeHelper", name: str):
        self._helper = helper
        self._name = name

    def __getattr__(self, method: str):
        def call(*args, **kwargs):
            return self._helper._api_call(self._name, method, args, kwargs)

        return call


class FakeApi:
    def __init__(self, helper: "FakeHelper"):
        self._helper = helper
        self.api_url = "http://opencti.invalid/graphql"

    def __getattr__(self, name: str):
        return FakeEntity(self._helper, name)

    def query(self, query, variables=None, *args, **kwargs):
        self._helper.calls.append(("api.query", (), {"query": query, "variables": variables}))
        return AutoDict(data=AutoDict())

    def fetch_opencti_file(self, *args, **kwargs):
        self._helper.calls.append(("api.fetch_opencti_file", args, kwargs))
        return b""

    @staticmethod
    def get_attribute_in_extension(key, obj):
        for ext in (obj.get("extensions") or {}).values():
            if key in ext:
                return ext[key]
        return obj.get(key)


class FakeHelper:
    """Records what a connector would do to OpenCTI."""

    stop_after = 0  # >0: raise StopCycle after this many reports/bundles
    existing: set = set()  # entity names the platform already holds (e.g. ATT&CK attack_pattern)

    def __init__(self, config: dict | None = None, *args, **kwargs):
        self.config = config or {}
        self.calls: list[tuple[str, tuple, dict]] = []
        self.logs: list[tuple[str, str, Any]] = []
        self.bundles: list[dict] = []
        self.state: dict | None = None
        self.connector_logger = FakeLogger(self.logs)
        self.api = FakeApi(self)
        self.connect_id = "00000000-0000-4000-8000-000000000000"
        self.connect_name = "test-connector"
        self.connect_scope = ""
        self.connect_confidence_level = 80
        self.connect_run_and_terminate = False
        self.connect_live_stream_id = None
        self.opencti_url = "http://opencti.invalid"
        self.work_id = None
        self.metric = _Anything()
        self.listen_callback = None
        self.scheduled = None
        self._writes = 0
        FakeHelper.last = self

    # -- logging ---------------------------------------------------------
    def log_debug(self, msg, meta=None):
        self.logs.append(("debug", str(msg), meta))

    def log_info(self, msg, meta=None):
        self.logs.append(("info", str(msg), meta))

    def log_warning(self, msg, meta=None):
        self.logs.append(("warning", str(msg), meta))

    def log_error(self, msg, meta=None):
        self.logs.append(("error", str(msg), meta))

    # -- state -----------------------------------------------------------
    def get_state(self):
        return self.state

    def set_state(self, state):
        json.dumps(state)  # a real helper stores JSON; fail the same way
        self.state = state

    # -- scheduling / listening -----------------------------------------
    def listen(self, message_callback, *args, **kwargs):
        self.listen_callback = message_callback

    def listen_stream(self, message_callback, *args, **kwargs):
        self.listen_callback = message_callback

    # pycti's schedulers run the callback at once, then every period. The fake
    # runs it once; the run ends at the first long sleep or the write cap.
    def schedule_period(self, message_callback, duration_period, *args, **kwargs):
        self.scheduled = (message_callback, duration_period)
        message_callback()

    schedule_iso = schedule_period
    schedule_process = schedule_period

    def force_ping(self):
        pass

    # -- bundles ---------------------------------------------------------
    @staticmethod
    def stix2_create_bundle(items):
        from pycti import OpenCTIConnectorHelper

        return OpenCTIConnectorHelper.stix2_create_bundle(items)

    def send_stix2_bundle(self, bundle, *args, **kwargs):
        parsed = json.loads(bundle) if isinstance(bundle, str) else bundle
        if parsed.get("type") != "bundle":
            raise ValueError("send_stix2_bundle got something that is not a STIX bundle")
        self.bundles.append(parsed)
        self.calls.append(("send_stix2_bundle", (), {"objects": len(parsed.get("objects", []))}))
        self._count_write()
        return [bundle]

    # -- api answers -----------------------------------------------------
    def _count_write(self):
        self._writes += 1
        if self.stop_after and self._writes >= self.stop_after:
            raise StopCycle(f"wrote {self._writes}")

    def _api_call(self, entity: str, method: str, args, kwargs):
        self.calls.append((f"api.{entity}.{method}", args, kwargs))
        if entity == "marking_definition" and method in ("read", "list"):
            marking = _marking(kwargs)
            return [marking] if method == "list" else marking
        if entity == "stix2" and method == "get_stix_bundle_or_object_from_entity_id":
            etype = str(kwargs.get("entity_type") or (args[0] if args else "Unknown"))
            eid = str(kwargs.get("entity_id") or (args[1] if len(args) > 1 else uuid.uuid4()))
            stype = "".join("-" + c.lower() if c.isupper() else c for c in etype).lstrip("-")
            obj = {"type": stype, "id": f"{stype}--{uuid.uuid5(uuid.NAMESPACE_URL, eid)}", "spec_version": "2.1",
                   "name": "existing", "created": "2020-01-01T00:00:00.000Z", "modified": "2020-01-01T00:00:00.000Z",
                   "x_opencti_id": eid}
            return {"type": "bundle", "id": f"bundle--{uuid.uuid4()}", "objects": [obj]}
        if entity == "work":
            return f"work-{uuid.uuid4()}" if method == "initiate_work" else None
        if method in ("read", "get"):
            if entity in self.existing:
                oid = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(kwargs, sort_keys=True, default=str)))
                return {"id": oid, "standard_id": f"{entity.replace('_', '-')}--{oid}", "entity_type": entity,
                        "name": "existing"}
            return None
        if method == "list":
            return {"entities": [], "pagination": {}} if kwargs.get("withPagination") else []
        if method in ("create", "import_from_stix2", "upsert"):
            oid = str(uuid.uuid4())
            obj = {"id": oid, "standard_id": f"{entity.replace('_', '-')}--{oid}", "entity_type": entity,
                   **{k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool, list))}}
            if entity in ("report", "grouping", "case_incident", "note"):
                self._count_write()
            return obj
        if method in ("download_file", "download"):
            return b""
        return None


def _marking(kwargs: dict) -> dict:
    wanted = "TLP:CLEAR"
    text = json.dumps(kwargs)
    for name in sorted(TLP_IDS, key=len, reverse=True):
        if name in text:
            wanted = name
            break
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, wanted)), "standard_id": TLP_IDS[wanted],
            "definition": wanted, "definition_type": "TLP", "x_opencti_order": 1}


class _Anything:
    """helper.metric and friends: accept any call chain."""

    def __getattr__(self, name):
        return self

    def __call__(self, *args, **kwargs):
        return self


def install() -> None:
    """Swap pycti's helper for the fake (before importing a connector)."""
    import pycti

    pycti.OpenCTIConnectorHelper = FakeHelper
