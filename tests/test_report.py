"""CI report rendering: JSON payload and JUnit XML. Offline only."""

import json
import xml.etree.ElementTree as ET

from jevium import report

STATE = {
    "status": "done",
    "plan": ["t1"],
    "history": [{"usage": {"input_tokens": 10, "output_tokens": 2}}],
    "text_calls": [{"usage": {"prompt_tokens": 5, "completion_tokens": 3}}],
    "elapsed_ms": 1500,
    "page": {"url": "https://x.test/done"},
    "decisions": [{"model": "jev-1.13.0"}, {"model": "jev-1.13.0"}],
}
VERDICT = {"success": False, "reason": "url mismatch",
           "checks": [{"type": "expected_url", "ok": False, "evidence": "e"}]}


def test_report_format_by_suffix(tmp_path):
    assert report.report_format(str(tmp_path / "r.json")) == "json"
    assert report.report_format(str(tmp_path / "r.xml")) == "xml"
    assert report.report_format(str(tmp_path / "r.txt")) is None


def test_payload_normalizes_tokens_and_models():
    payload = report.report_payload(STATE, VERDICT)
    assert payload["tokens"] == {"input": 15, "output": 5}
    assert payload["model_ids"] == ["jev-1.13.0"]
    assert payload["actions"] == 1
    assert payload["final_url"] == "https://x.test/done"
    assert payload["success"] is False


def test_render_json_roundtrip():
    payload = json.loads(report.render_report(STATE, VERDICT, "json"))
    assert payload["reason"] == "url mismatch"
    assert payload["checks"][0]["type"] == "expected_url"


def test_junit_failure_and_skip_and_pass():
    failed = ET.fromstring(report.render_report(STATE, VERDICT, "xml"))
    assert failed.tag == "testsuite" and failed.get("name") == "jevium"
    case = failed.find("testcase")
    assert case.get("name") == "t1"
    assert case.find("failure") is not None
    unknown = ET.fromstring(report.render_report(
        STATE, {"success": None, "reason": "skipped", "checks": []}, "xml"))
    assert unknown.find("testcase").find("skipped") is not None
    passed = ET.fromstring(report.render_report(
        STATE, {"success": True, "reason": "ok", "checks": []}, "xml"))
    assert passed.find("testcase").find("failure") is None
    assert passed.find("testcase").find("skipped") is None
