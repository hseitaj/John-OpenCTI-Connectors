"""Regression tests for specific connector bugs fixed alongside this suite."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
CONNECTORS = ROOT / "connectors"


def load(path: Path, name: str, extra_path: Path | None = None):
    for p in filter(None, (extra_path, path.parent, CONNECTORS)):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_model_qa_finds_malware_names():
    # The two patterns held a literal backspace character where \b was meant,
    # so they never matched anything.
    src = CONNECTORS / "report_model_qa" / "src"
    sys.path.insert(0, str(src))
    try:
        from rules.pdf_suggestions import _smart_parse_malware_candidates
    finally:
        sys.path.remove(str(src))
    found = _smart_parse_malware_candidates(
        "Analysts found the BEANSTALK Android backdoor and a backdoor called DARKPULSAR.", 0.0, 10, None)
    assert {(c["name"], c["rule"]) for c in found} >= {
        ("BEANSTALK", "MALWARE.TYPE_SUFFIX"), ("DARKPULSAR", "MALWARE.CALLED_CUE")}


def test_malware_bazaar_sends_the_abuse_ch_auth_key_header():
    # abuse.ch answers 401 without the Auth-Key header; the key used to travel
    # only in the POST body.
    client_mod = load(CONNECTORS / "malware_bazaar" / "src" / "client.py", "mb_client")
    response = MagicMock(status_code=200)
    response.json.return_value = {"query_status": "hash_not_found"}
    with patch.object(client_mod.requests, "post", return_value=response) as post:
        client_mod.MalwareBazaarClient(api_key="secret-key").get_file_info("0" * 64)
    assert post.call_args.kwargs["headers"] == {"Auth-Key": "secret-key"}


def test_nsa_tnw_modules_import_without_a_cycle():
    # connector.py and opencti_publish.py imported each other, so the container
    # died with ImportError before doing anything.
    src = CONNECTORS / "nsa_tnw" / "src"
    sys.path[:0] = [str(src), str(CONNECTORS)]
    try:
        for mod in ("connector", "opencti_publish", "tnw_fetch"):
            sys.modules.pop(mod, None)
        import opencti_publish  # noqa: F401  (first, the order that used to fail)
        import connector  # noqa: F401
    finally:
        for p in (str(src), str(CONNECTORS)):
            sys.path.remove(p)
        for mod in ("connector", "opencti_publish", "tnw_fetch"):
            sys.modules.pop(mod, None)


def test_cve_connector_schedules_instead_of_listening(monkeypatch):
    # helper.listen() never fires for an EXTERNAL_IMPORT connector, so the CVE
    # connector ingested once per container start. It must use the scheduler,
    # and a failing cycle must not escape (pycti stops scheduling if it does).
    import fake_opencti

    fake_opencti.install()
    main = load(CONNECTORS / "opencti-cve-connector" / "src" / "main.py", "cve_main")
    connector = MagicMock()
    connector.process.side_effect = RuntimeError("NVD down")
    monkeypatch.setattr(main, "CVEReportedRunsConnector", lambda helper: connector)
    monkeypatch.setenv("CONNECTOR_DURATION_PERIOD", "PT6H")
    main.main()
    helper = fake_opencti.FakeHelper.last
    assert helper.scheduled and helper.scheduled[1] == "PT6H"
    assert helper.listen_callback is None
    assert any("retrying next period" in m for _, m, _ in helper.logs)


def test_cve_connector_reads_the_documented_api_key(monkeypatch):
    import fake_opencti

    fake_opencti.install()
    runs = load(CONNECTORS / "opencti-cve-connector" / "src" / "cve_reported_runs.py", "cve_runs")
    for var in ("CVE_NVD_API_KEY", "NVD_API_KEY", "CVE_REPORT_MARKING_DEFINITION_NAME",
                "CVE_REPORT_MARKING_DEFINITION_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CVE_API_KEY", "nvd-key")
    connector = runs.CVEReportedRunsConnector(fake_opencti.FakeHelper({}))
    assert connector.nvd_api_key == "nvd-key"
    assert connector.report_marking_name == "TLP:CLEAR"
    assert connector.marking_definition_stix_id  # resolved, so reports are never unmarked


def _module(name: str, connector: str):
    import fake_opencti

    fake_opencti.install()
    return load(CONNECTORS / connector / "main.py", name)


def test_defense_one_reads_double_escaped_feed_content():
    # The feed escapes the CDATA wrapper itself; feedparser then returned empty
    # content and every item failed with "No content:encoded".
    import feedparser

    mod = _module("d1_main", "defense_one")
    feed = ('<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>'
            "<title>t</title><link>https://www.defenseone.com/a/1/</link>"
            "<content:encoded>&lt;![CDATA[&lt;p&gt;Full article text&lt;/p&gt;]]&gt;</content:encoded>"
            "</item></channel></rss>")
    entry = feedparser.parse(mod._repair_double_escaped_cdata(feed)).entries[0]
    assert "Full article text" in entry.content[0].value
    good = "<content:encoded><![CDATA[<p>ok</p>]]></content:encoded>"
    assert mod._repair_double_escaped_cdata(good) == good


def test_brookings_reads_topics_from_acf():
    # Topic IDs moved to acf.helper_taxonomies.topics; the filter rejected everything.
    mod = _module("brookings_main", "brookings_institution")
    assert mod._topics({"acf": {"helper_taxonomies": {"topics": [69, 153]}}}) == [69, 153]
    assert mod._topics({"topics": [69]}) == [69]
    assert mod._topics({"acf": False}) == []
    assert "acf.helper_taxonomies.topics" in mod.LISTING_FIELDS


def test_who_does_not_select_the_removed_summary_property():
    source = (CONNECTORS / "world_health_organization" / "main.py").read_text()
    select = [line for line in source.splitlines() if '"$select"' in line]
    assert select and "Summary" not in select[0]


def test_occrp_finds_content_on_redesigned_pages():
    from bs4 import BeautifulSoup

    mod = _module("occrp_main", "organized_crime_corruption_reporting")
    html = ('<html><body><section class="section-base"><div class="content-generator">'
            '<div class="wp-wysiwyg"><p>Body text of a redesigned OCCRP page.</p></div>'
            "</div></section></body></html>")
    content = mod.OccrpConnector._extract_content(BeautifulSoup(html, "lxml"))
    assert content and "Body text" in str(content)


def test_fake_helper_builds_real_bundles():
    # Once installed, the fake must still serialize bundles with pycti's own code
    # (it used to call itself until RecursionError).
    import json as _json

    import fake_opencti
    import stix2

    fake_opencti.install()
    fake_opencti.install()  # idempotent: the real implementation is kept
    bundle = _json.loads(fake_opencti.FakeHelper.stix2_create_bundle(
        [stix2.Identity(name="x", identity_class="organization")]))
    assert bundle["type"] == "bundle" and len(bundle["objects"]) == 1


def test_live_run_that_crashes_after_writing_does_not_pass():
    import run_connector

    base = {"mode": "live", "stdout": "", "stderr": "", "errors": [], "reports": 1, "bundles": 0}
    assert run_connector.passed({**base, "outcome": "write-cap"})
    assert not run_connector.passed({**base, "outcome": "exception"})
    assert not run_connector.passed({**base, "outcome": "exit"})
