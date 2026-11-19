from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from verifier import __version__
from verifier.detectors import audio, deepware, image, url_check, video
from verifier.utils import detect_media_type, human_size, sha256_of, sha256_of_text

VERIFICATION_RESOURCES = [
    {"name": "Google Fact Check Explorer", "url": "https://toolbox.google.com/factcheck/explorer"},
    {"name": "PIB Fact Check (India)", "url": "https://pib.gov.in/factcheck.aspx"},
    {"name": "BOOM Fact Check", "url": "https://www.boomlive.in/fact-check"},
    {"name": "Alt News", "url": "https://www.altnews.in/"},
    {"name": "Snopes", "url": "https://www.snopes.com/"},
    {"name": "Reuters Fact Check", "url": "https://www.reuters.com/fact-check/"},
    {"name": "Google Lens (reverse image search)", "url": "https://lens.google.com/"},
    {"name": "TinEye (reverse image search)", "url": "https://tineye.com/"},
    {"name": "InVID-WeVerify video verification", "url": "https://www.invid-project.eu/tools-and-services/invid-verification-plugin/"},
    {"name": "Deepware Scanner", "url": "https://scanner.deepware.ai"},
]

LIMITATIONS = [
    "Detection is probabilistic. A clean result does not prove authenticity and a flag does not prove manipulation.",
    "Deepware Scanner targets face-swap manipulation in video. It does not analyze voice or still images.",
    "Image, audio and URL checks are heuristics built on metadata and signal statistics, not trained deepfake classifiers.",
    "Compression, re-uploads and screenshots remove evidence and can cause both false positives and false negatives.",
    "Always combine tool output with source checking and independent reporting before sharing media.",
]


def verdict_for(score):
    if score >= 50:
        return "high", "High risk: treat as unverified"
    if score >= 20:
        return "medium", "Suspicious indicators found"
    return "low", "No strong manipulation indicators"


def combine(results):
    scores = [item.risk() for item in results if item.status == "ok"]
    if not scores:
        return 0
    top = max(scores)
    corroborating = sum(1 for value in scores if value >= 20) - (1 if top >= 20 else 0)
    return min(100, top + 5 * max(0, corroborating))


def recommendations_for(media_type, results):
    steps = []
    if media_type == "video":
        steps.append("Scan the original, highest-quality copy of the video, not a screenshot or re-upload.")
        steps.append("Search the earliest upload of the clip and compare it with the version you received.")
        steps.append("Check whether trusted outlets report the same event.")
    elif media_type == "image":
        steps.append("Run a reverse image search to find the earliest appearance of the picture.")
        steps.append("Open the saved ELA map and look for regions that stand out from their surroundings.")
    elif media_type == "audio":
        steps.append("Find the original recording or broadcast and compare the two.")
        steps.append("Ask whether the speaker's other public statements match what the clip says.")
    else:
        steps.append("Read the article beyond the headline and look for the original source of any media it embeds.")
        steps.append("Check the outlet's other reporting and whether established fact-checkers have covered the claim.")
    if any(item.status == "skipped" for item in results):
        steps.append("Some checks were skipped. Read the notes in the report and install the missing tools.")
    steps.append("Do not share the content until the source and context are confirmed.")
    return steps


def build_report(target, media_type, results, extra_meta):
    score = combine(results)
    level, label = verdict_for(score)
    return {
        "meta": {
            "tool_version": __version__,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "target": target,
            "media_type": media_type,
            **extra_meta,
        },
        "overall": {"risk_score": score, "level": level, "verdict": label},
        "detectors": [item.to_dict() for item in results],
        "recommendations": recommendations_for(media_type, results),
        "resources": VERIFICATION_RESOURCES,
        "limitations": LIMITATIONS,
    }


def run_directory(base_dir, label, digest):
    folder = Path(base_dir) / f"{label}_{digest[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def analyze_file(path, output_dir, deepware_enabled=True, manual_score=None):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    media_type = detect_media_type(path)
    if media_type == "unknown":
        raise ValueError(f"Unsupported file type: {path.suffix or 'no extension'}")

    digest = sha256_of(path)
    run_dir = run_directory(output_dir, path.stem, digest)

    results = []
    if media_type == "video":
        results.append(video.analyze(path, run_dir / "frames"))
        results.append(deepware.run_file(path, enabled=deepware_enabled, manual_score=manual_score))
        results.append(audio.analyze(path))
    elif media_type == "image":
        results.append(image.analyze(path, run_dir))
    else:
        results.append(audio.analyze(path))

    report = build_report(
        path.name,
        media_type,
        results,
        {"sha256": digest, "size": human_size(path.stat().st_size)},
    )
    return report, run_dir


def analyze_url(url, output_dir, scan_with_deepware=False, fetch=True):
    parsed = urlparse(url)
    digest = sha256_of_text(url)
    label = (parsed.hostname or "url").replace(".", "_")
    run_dir = run_directory(output_dir, label, digest)

    results = [url_check.analyze(url, fetch=fetch)]
    if scan_with_deepware:
        results.append(deepware.run_url(url))

    report = build_report(url, "url", results, {"sha256": digest, "size": "n/a"})
    return report, run_dir
