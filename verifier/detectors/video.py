import json
from pathlib import Path

import numpy as np
from PIL import Image

from verifier.models import DetectorResult
from verifier.utils import run_command, tool_available

NAME = "Video forensics"
STANDARD_FPS = (23.976, 24.0, 25.0, 29.97, 30.0, 48.0, 50.0, 59.94, 60.0)
EDITOR_TAGS = (
    "premiere",
    "after effects",
    "capcut",
    "davinci",
    "final cut",
    "handbrake",
    "lavf",
    "lavc",
    "filmora",
    "kdenlive",
    "shotcut",
    "inshot",
)


def probe(path):
    if not tool_available("ffprobe"):
        return None
    process = run_command(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    )
    if process.returncode != 0:
        return None
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        return None


def _rate(value):
    try:
        numerator, denominator = str(value).split("/")
        denominator = float(denominator)
        return float(numerator) / denominator if denominator else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def extract_frames(path, frames_dir, max_frames):
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.jpg"):
        old.unlink()
    if not tool_available("ffmpeg"):
        return []
    run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "fps=1",
            "-frames:v",
            str(max_frames),
            str(frames_dir / "frame_%04d.jpg"),
        ],
        timeout=300,
    )
    return sorted(frames_dir.glob("frame_*.jpg"))


def frame_statistics(frames):
    sharpness = []
    brightness = []
    for frame in frames:
        with Image.open(frame) as handle:
            gray = np.asarray(handle.convert("L"), dtype=np.float64)
        if gray.shape[0] < 3 or gray.shape[1] < 3:
            continue
        laplacian = (
            4 * gray[1:-1, 1:-1]
            - gray[:-2, 1:-1]
            - gray[2:, 1:-1]
            - gray[1:-1, :-2]
            - gray[1:-1, 2:]
        )
        sharpness.append(float(laplacian.var()))
        brightness.append(float(gray.mean()))
    return sharpness, brightness


def analyze(path, frames_dir, max_frames=30):
    result = DetectorResult(NAME)
    info = probe(path)
    if info is None:
        result.status = "skipped"
        result.note = "ffprobe is not installed or the file could not be read"
        return result

    streams = info.get("streams", [])
    container = info.get("format", {})
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None:
        result.add("medium", "No video stream found", "The file does not contain a decodable video track.")
        return result

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    duration = float(container.get("duration") or video_stream.get("duration") or 0)
    average_fps = _rate(video_stream.get("avg_frame_rate"))
    nominal_fps = _rate(video_stream.get("r_frame_rate"))
    tags = {str(k).lower(): str(v) for k, v in (container.get("tags") or {}).items()}
    encoder = tags.get("encoder", "")

    result.data.update(
        {
            "codec": video_stream.get("codec_name"),
            "width": width,
            "height": height,
            "duration_seconds": round(duration, 2),
            "average_fps": round(average_fps, 3),
            "bit_rate": container.get("bit_rate"),
            "format": container.get("format_name"),
            "has_audio": audio_stream is not None,
            "creation_time": tags.get("creation_time"),
            "encoder": encoder or None,
        }
    )

    if 0 < height < 720:
        result.add(
            "low",
            "Low resolution",
            f"{width}x{height} is well below the 1920x1080 that Deepware recommends. "
            "Heavy compression can hide manipulation artifacts and weaken detection.",
        )
    elif 0 < height < 1080:
        result.add("info", "Below recommended resolution", f"{width}x{height} is under 1920x1080, the best size for Deepware.")

    if duration > 600:
        result.add("low", "Longer than Deepware's limit", "Deepware can analyze videos of up to about 10 minutes. Trim the clip first.")
    elif 0 < duration < 3:
        result.add("low", "Very short clip", "Clips under three seconds give detectors little evidence to work with.")

    if "creation_time" not in tags:
        result.add(
            "low",
            "No creation timestamp",
            "The container has no creation_time tag. Social platforms strip it, but edited or generated files often lack it too.",
        )

    lowered_encoder = encoder.lower()
    if any(marker in lowered_encoder for marker in EDITOR_TAGS):
        result.add("info", "Re-encoded or edited", f"Encoder tag reads '{encoder}', so the file passed through editing or transcoding software.")

    if audio_stream is None:
        result.add("info", "No audio track", "The video has no audio stream, so voice analysis is not possible.")

    if average_fps and not any(abs(average_fps - known) < 0.2 for known in STANDARD_FPS):
        result.add("low", "Unusual frame rate", f"Average frame rate is {average_fps:.2f} fps, which is not a standard camera rate.")

    if average_fps and nominal_fps and abs(average_fps - nominal_fps) / max(nominal_fps, 1) > 0.05:
        result.add(
            "low",
            "Variable frame rate",
            "Average and nominal frame rates differ, which is common in screen recordings and edited clips.",
        )

    frames = extract_frames(path, frames_dir, max_frames)
    result.data["frames_sampled"] = len(frames)
    if len(frames) >= 3:
        sharpness, brightness = frame_statistics(frames)
        if sharpness and np.mean(sharpness) > 0:
            variation = float(np.std(sharpness) / np.mean(sharpness))
            result.data["sharpness_variation"] = round(variation, 3)
            if variation > 1.0:
                result.add(
                    "low",
                    "Large sharpness swings between frames",
                    "Sampled frames differ a lot in detail. This can come from scene cuts, but also from blended or re-rendered regions.",
                )
        if brightness:
            result.data["brightness_range"] = [round(min(brightness), 1), round(max(brightness), 1)]
    return result
