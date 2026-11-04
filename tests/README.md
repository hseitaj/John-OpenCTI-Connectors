# Connector tests

Every connector is checked three ways. None of them needs an OpenCTI
platform: `fake_opencti.py` stands in for pycti's `OpenCTIConnectorHelper`
and records everything a connector would write.

| Check | What it proves | Network | Runs in CI |
|---|---|---|---|
| **Boot** (`test_boot.py`) | The connector starts through its real entrypoint: config loads, the helper is built, graph references resolve, and it reaches its source or registers its listener with no error. | blocked | yes |
| **Deploy rules** (`test_deploy_rules.py`) | Dockerfiles copy only files that exist, ship the shared `microservices` package, use supported base images, pin Playwright to the image's browsers and pycti to the platform (7.261103.0); compose files document only variables the code reads. | none | yes |
| **Image** (`image_probe.py`) | The built image imports its entrypoint, inside the container, with no network. | none | yes, for connectors a PR changes (all on manual dispatch) |
| **Live** (`run_connector.py --mode live`) | One real cycle against the real source: fetch, parse, render, write. Stops after two reports or bundles. | real | no (manual) |

`test_regressions.py` covers specific bug fixes, and `test_connector_suites.py`
runs each connector's own unit tests in its own process.

## Running

```bash
pip install -r tests/requirements.txt
python -m pytest tests -q
```

Boot or live-run one connector and see what it did:

```bash
python tests/run_connector.py dfir_report                 # boot, offline
PLAYWRIGHT_BROWSERS_PATH=... python tests/run_connector.py dfir_report --mode live
python tests/run_connector.py cis_pdf --mode live --env CIS_MAX_INGEST_PER_CYCLE=5
```

The last line of output is `RESULT {json}`: the outcome, reports and bundles
written, errors, and the last log lines.

Check a built image:

```bash
docker build -t check --build-context microservices=connectors/microservices connectors/dfir_report
python tests/image_probe.py dfir_report check
```

## `connectors.json`

One entry per connector directory: the entry file the Dockerfile runs, and
anything the harness needs to run it like the container does.

- `entry` / `module` / `container`: the entrypoint (host path, `python -m` module, container path).
- `env`: test values for settings with no usable default. `{dir}` is the connector directory, `{tmp}` a scratch directory.
- `platform_has`: entity types the fake platform already holds (for example ATT&CK attack patterns), for connectors that refuse to start without them.
- `path_map`: absolute paths a container gets from a volume mount, served from the repo.
- `assemble`: rebuild a container layout from `COPY` steps (`report_enrichment` combines two connectors).
- `skip`: not a runnable connector (`openalex_import` is an empty skeleton).

`test_registry_covers_every_connector` fails when a connector directory is
added without an entry here.

## Adding a connector

1. Add its entry to `connectors.json`.
2. `python tests/run_connector.py <name>` should pass offline; fix what it reports.
3. Run it live once (`--mode live`) and check it writes reports.
4. `python -m pytest tests -q`.
