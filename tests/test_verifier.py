import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from main import main
from verifier.detectors import audio, deepware, image, url_check
from verifier.models import DetectorResult
from verifier.pipeline import analyze_file, analyze_url, combine, verdict_for
from verifier.report.generator import write_reports
from verifier.utils import detect_media_type

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def titles(result):
    return [item.title for item in result.findings]


def write_wav(path, samples, rate=22050):
    data = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(data.tobytes())


def test_detect_media_type():
    assert detect_media_type("a.MP4") == "video"
    assert detect_media_type("a.jpeg") == "image"
    assert detect_media_type("a.flac") == "audio"
    assert detect_media_type("a.xyz") == "unknown"


def test_image_generator_metadata_is_flagged(tmp_path):
    source = tmp_path / "gen.png"
    meta = PngInfo()
    meta.add_text("parameters", "a cat, Steps: 20, Sampler: Euler")
    Image.new("RGB", (512, 512), (120, 90, 200)).save(source, pnginfo=meta)
    result = image.analyze(source, tmp_path / "out")
    assert result.status == "ok"
    assert "Generator-style metadata fields" in titles(result)
    assert result.risk() >= 40


def test_image_ela_map_is_written_for_jpeg(tmp_path):
    rng = np.random.default_rng(1)
    pixels = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
    source = tmp_path / "photo.jpg"
    Image.fromarray(pixels).save(source, quality=85)
    result = image.analyze(source, tmp_path / "out")
    assert result.status == "ok"
    assert (tmp_path / "out" / "ela_map.png").is_file()
    assert result.data["ela"]["reliable"] is True


def test_image_unreadable_file_reports_error(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    result = image.analyze(broken, tmp_path / "out")
    assert result.status == "error"


def test_audio_detects_digital_silence(tmp_path):
    rate = 22050
    t = np.arange(rate * 4) / rate
    tone = 0.4 * np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 0.5 * t))
    tone[rate * 2 :] = 0.0
    path = tmp_path / "tone.wav"
    write_wav(path, tone, rate)
    result = audio.analyze(path)
    assert result.status == "ok"
    assert "Segments of exact digital silence" in titles(result)
    assert result.data["sample_rate"] == rate


def test_audio_noise_has_wide_bandwidth(tmp_path):
    rng = np.random.default_rng(2)
    path = tmp_path / "noise.wav"
    write_wav(path, 0.3 * rng.standard_normal(44100 * 3), 44100)
    result = audio.analyze(path)
    assert result.data["bandwidth_hz"] > 5000


def test_url_host_checks_without_network():
    result = url_check.analyze("http://192.168.1.10/clip", fetch=False)
    assert "Connection is not encrypted" in titles(result)
    assert "Link points to a raw IP address" in titles(result)
    shortened = url_check.analyze("https://bit.ly/abc123", fetch=False)
    assert "URL shortener" in titles(shortened)
    disguised = url_check.analyze("https://news.example.com@evil.example.net/a", fetch=False)
    assert "Credentials before the hostname" in titles(disguised)


def test_url_rejects_non_http():
    result = url_check.analyze("ftp://example.com/file", fetch=False)
    assert result.status == "error"


def test_deepware_summary_and_findings():
    report = {
        "report-id": "r1",
        "complete": True,
        "total": 3,
        "positive": 2,
        "results": {"a": {"detected": True}, "b": {"detected": True}, "c": {"detected": False}},
    }
    summary = deepware.summarize_report(report)
    assert summary["positive"] == 2
    result = DetectorResult("Deepware Scanner")
    deepware.apply_summary(result, summary)
    assert result.findings[0].severity == "high"
    assert result.risk() >= 50


def test_deepware_manual_score_thresholds():
    high, mid, low = (DetectorResult("d") for _ in range(3))
    deepware.apply_manual_score(high, 85)
    deepware.apply_manual_score(mid, 50)
    deepware.apply_manual_score(low, 10)
    assert high.findings[0].severity == "high"
    assert mid.findings[0].severity == "medium"
    assert low.findings[0].severity == "info"


def test_deepware_without_key_is_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(deepware.config, "DEEPWARE_API_KEY", "")
    result = deepware.run_file(tmp_path / "x.mp4")
    assert result.status == "skipped"
    assert "deepware-score" in result.note


def test_combine_and_verdict():
    quiet = DetectorResult("q")
    loud = DetectorResult("l")
    loud.add("high", "x", "y")
    loud.add("high", "x2", "y2")
    assert combine([quiet]) == 0
    assert combine([quiet, loud]) == 80
    assert verdict_for(80)[0] == "high"
    assert verdict_for(25)[0] == "medium"
    assert verdict_for(5)[0] == "low"


def test_pipeline_and_reports_for_image(tmp_path):
    source = tmp_path / "pic.png"
    Image.new("RGB", (640, 480), (10, 200, 90)).save(source)
    report, run_dir = analyze_file(source, tmp_path / "out")
    written = write_reports(report, run_dir, "both")
    assert {p.name for p in written} == {"report.json", "report.html"}
    payload = json.loads((run_dir / "report.json").read_text())
    assert payload["meta"]["media_type"] == "image"
    assert "Media verification report" in (run_dir / "report.html").read_text()


def test_pipeline_rejects_unknown_type(tmp_path):
    source = tmp_path / "data.bin"
    source.write_bytes(b"1234")
    with pytest.raises(ValueError):
        analyze_file(source, tmp_path / "out")
    with pytest.raises(FileNotFoundError):
        analyze_file(tmp_path / "missing.mp4", tmp_path / "out")


def test_url_pipeline_without_fetch(tmp_path):
    report, run_dir = analyze_url("https://bit.ly/x", tmp_path / "out", fetch=False)
    assert report["meta"]["media_type"] == "url"
    assert run_dir.is_dir()


def test_cli_runs_on_image(tmp_path, capsys):
    source = tmp_path / "cli.png"
    Image.new("RGB", (300, 200), (0, 0, 0)).save(source)
    code = main(["file", str(source), "--output-dir", str(tmp_path / "out"), "--format", "json"])
    assert code == 0
    assert "Verdict" in capsys.readouterr().out
    assert main(["file", str(tmp_path / "nope.mp4")]) == 2


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is required")
def test_video_pipeline_with_manual_deepware_score(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=4:size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=300:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip),
        ],
        check=True,
    )
    report, run_dir = analyze_file(clip, tmp_path / "out", manual_score=88)
    names = {d["name"]: d for d in report["detectors"]}
    assert names["Video forensics"]["status"] == "ok"
    assert names["Video forensics"]["data"]["frames_sampled"] >= 3
    assert names["Deepware Scanner"]["findings"][0]["severity"] == "high"
    assert names["Audio forensics"]["status"] == "ok"
    assert report["overall"]["level"] == "high"
    assert Path(run_dir).is_dir()
