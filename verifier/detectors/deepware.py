import time
from pathlib import Path

import requests

from verifier import config
from verifier.models import DetectorResult

NAME = "Deepware Scanner"


class DeepwareError(Exception):
    pass


def _headers():
    if not config.DEEPWARE_API_KEY:
        raise DeepwareError("DEEPWARE_API_KEY is not set")
    return {
        "X-Deepware-Authentication": config.DEEPWARE_API_KEY,
        "Accept": "application/json",
    }


def _endpoint(path):
    return config.DEEPWARE_BASE_URL.rstrip("/") + path


def _parse(response):
    if response.status_code == 429:
        raise DeepwareError("Deepware rate limit reached for this API key")
    if response.status_code >= 400:
        raise DeepwareError(f"Deepware returned HTTP {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError as exc:
        raise DeepwareError("Deepware returned a response that is not JSON") from exc


def _report_id(payload):
    for key in ("report-id", "report_id", "reportId"):
        if payload.get(key):
            return payload[key]
    raise DeepwareError(f"No report id in Deepware response: {payload}")


def start_video_scan(path):
    with open(path, "rb") as handle:
        files = {config.DEEPWARE_FILE_FIELD: (Path(path).name, handle)}
        response = requests.post(_endpoint("/video/scan"), headers=_headers(), files=files, timeout=300)
    return _report_id(_parse(response))


def start_url_scan(video_url):
    files = {"videourl": (None, video_url)}
    response = requests.post(_endpoint("/url/scan"), headers=_headers(), files=files, timeout=60)
    return _report_id(_parse(response))


def fetch_report(report_id):
    response = requests.get(
        _endpoint("/report"),
        headers=_headers(),
        params={"report-id": report_id},
        timeout=60,
    )
    return _parse(response)


def wait_for_report(report_id):
    deadline = time.monotonic() + config.DEEPWARE_TIMEOUT_SECONDS
    report = fetch_report(report_id)
    while not report.get("complete"):
        if time.monotonic() >= deadline:
            return report
        time.sleep(config.DEEPWARE_POLL_SECONDS)
        report = fetch_report(report_id)
    return report


def summarize_report(report):
    models = {}
    for name, value in (report.get("results") or {}).items():
        if isinstance(value, dict):
            models[name] = {"detected": bool(value.get("detected")), "score": value.get("score")}
        else:
            models[name] = {"detected": bool(value), "score": None}
    total = report.get("total")
    positive = report.get("positive")
    if total is None:
        total = len(models)
    if positive is None:
        positive = sum(1 for item in models.values() if item["detected"])
    return {
        "report_id": report.get("report-id"),
        "complete": bool(report.get("complete")),
        "total": int(total),
        "positive": int(positive),
        "models": models,
    }


def apply_summary(result, summary):
    result.data["deepware"] = summary
    if not summary["complete"]:
        result.add(
            "low",
            "Deepware scan did not finish in time",
            "The report was still incomplete when polling stopped. Re-run later or fetch the report id manually.",
        )
        return
    total, positive = summary["total"], summary["positive"]
    if positive > 0 and total > 0:
        ratio = positive / total
        severity = "high" if ratio >= 0.5 else "medium"
        result.add(
            severity,
            f"{positive} of {total} Deepware detection model(s) flagged this video",
            "Deepware reports the likelihood of face manipulation. A flag is a strong signal, not proof.",
            weight=round(30 + 50 * ratio),
        )
    else:
        result.add(
            "info",
            "No Deepware detection model flagged this video",
            "This lowers but does not remove the chance of manipulation. Deepware only looks at face swaps in video.",
        )


def apply_manual_score(result, score):
    result.data["deepware_manual_score"] = score
    if score >= 70:
        result.add(
            "high",
            f"Deepware web scanner reported a {score:.0f}% likelihood of deepfake",
            "Score entered manually from scanner.deepware.ai.",
            weight=80,
        )
    elif score >= 40:
        result.add(
            "medium",
            f"Deepware web scanner reported a {score:.0f}% likelihood of deepfake",
            "Score entered manually from scanner.deepware.ai. Treat as inconclusive and verify the source.",
            weight=35,
        )
    else:
        result.add(
            "info",
            f"Deepware web scanner reported a {score:.0f}% likelihood of deepfake",
            "Score entered manually from scanner.deepware.ai. A low score does not guarantee authenticity.",
        )


def _not_run(result, reason):
    result.status = "skipped"
    result.note = reason


def run_file(path, enabled=True, manual_score=None):
    result = DetectorResult(NAME)
    if manual_score is not None:
        apply_manual_score(result, manual_score)
        return result
    if not enabled:
        _not_run(result, "Deepware scan disabled with --no-deepware")
        return result
    if not config.DEEPWARE_API_KEY:
        _not_run(
            result,
            f"No DEEPWARE_API_KEY set. Upload the video at {config.DEEPWARE_WEB_SCANNER} "
            "and re-run with --deepware-score <percent> to include the result.",
        )
        return result
    try:
        report_id = start_video_scan(path)
        summary = summarize_report(wait_for_report(report_id))
        summary["report_id"] = summary["report_id"] or report_id
        apply_summary(result, summary)
    except (DeepwareError, requests.RequestException, OSError) as exc:
        result.status = "error"
        result.note = f"Deepware scan failed: {exc}"
    return result


def run_url(video_url):
    result = DetectorResult(NAME)
    if not config.DEEPWARE_API_KEY:
        _not_run(result, "No DEEPWARE_API_KEY set, so the URL scan was skipped.")
        return result
    try:
        report_id = start_url_scan(video_url)
        summary = summarize_report(wait_for_report(report_id))
        summary["report_id"] = summary["report_id"] or report_id
        apply_summary(result, summary)
    except (DeepwareError, requests.RequestException) as exc:
        result.status = "error"
        result.note = f"Deepware URL scan failed: {exc}"
    return result
