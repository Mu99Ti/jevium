"""Machine-readable run reports for CI: JSON payload and JUnit XML."""

import json
import xml.etree.ElementTree as ET


def report_format(path):
    text = str(path)
    if text.endswith(".json"):
        return "json"
    if text.endswith(".xml"):
        return "xml"
    return None


def _token_totals(state):
    inp = out = 0
    for entry in list(state.get("history") or []) + list(state.get("text_calls") or []):
        usage = entry.get("usage") or {}
        inp += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return {"input": inp, "output": out}


def report_payload(state, verdict):
    page = state.get("page") or {}
    model_ids = sorted({d.get("model") for d in (state.get("decisions") or []) if d.get("model")})
    return {
        "goals": state.get("plan") or [],
        "status": state.get("status"),
        "success": verdict.get("success"),
        "reason": verdict.get("reason"),
        "checks": verdict.get("checks") or [],
        "actions": len(state.get("history") or []),
        "elapsed_ms": state.get("elapsed_ms", 0),
        "final_url": page.get("url", ""),
        "tokens": _token_totals(state),
        "text_model_calls": len(state.get("text_calls") or []),
        "model_ids": model_ids,
    }


def render_report(state, verdict, fmt):
    payload = report_payload(state, verdict)
    if fmt == "json":
        return json.dumps(payload, indent=2) + "\n"
    elapsed = f"{payload['elapsed_ms'] / 1000:.3f}"
    suite = ET.Element("testsuite", name="jevium", tests="1", time=elapsed)
    goal = str(payload["goals"][0]) if payload["goals"] else "jevium run"
    case = ET.SubElement(suite, "testcase", classname="jevium", name=goal, time=elapsed)
    if payload["success"] is False:
        failure = ET.SubElement(case, "failure", message=str(payload["reason"])[:500])
        failure.text = json.dumps(payload["checks"])
    elif payload["success"] is None:
        ET.SubElement(case, "skipped", message=str(payload["reason"])[:500])
    system_out = ET.SubElement(case, "system-out")
    system_out.text = json.dumps(payload, indent=2)
    ET.indent(suite, space="  ")
    return ET.tostring(suite, encoding="unicode") + "\n"
