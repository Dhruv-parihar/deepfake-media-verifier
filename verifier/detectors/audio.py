import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import welch

from verifier.models import DetectorResult
from verifier.utils import run_command, tool_available

NAME = "Audio forensics"
MAX_ANALYSIS_SECONDS = 120
BLOCK_SECONDS = 0.02


def _to_mono_float(data):
    original_dtype = data.dtype
    samples = np.asarray(data)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if np.issubdtype(original_dtype, np.integer):
        info = np.iinfo(original_dtype)
        return samples.astype(np.float64) / float(max(abs(info.min), info.max))
    return samples.astype(np.float64)


def load_audio(path):
    path = Path(path)
    if path.suffix.lower() == ".wav":
        try:
            rate, data = wavfile.read(str(path))
            return rate, _to_mono_float(data)
        except (ValueError, OSError):
            pass
    if not tool_available("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "audio.wav"
        process = run_command(
            ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
            timeout=300,
        )
        if process.returncode != 0 or not target.exists():
            return None
        rate, data = wavfile.read(str(target))
        return rate, _to_mono_float(data)


def bandwidth_hz(samples, rate):
    freqs, power = welch(samples, fs=rate, nperseg=min(2048, samples.size))
    total = float(power.sum())
    if total <= 0:
        return 0.0
    cumulative = np.cumsum(power) / total
    index = int(np.searchsorted(cumulative, 0.995))
    return float(freqs[min(index, freqs.size - 1)])


def analyze(path):
    result = DetectorResult(NAME)
    loaded = load_audio(path)
    if loaded is None:
        result.status = "skipped"
        result.note = "No readable audio track, or ffmpeg is not installed for this format"
        return result

    rate, samples = loaded
    total_seconds = samples.size / rate if rate else 0
    samples = samples[: int(rate * MAX_ANALYSIS_SECONDS)]
    result.data.update(
        {
            "sample_rate": int(rate),
            "duration_seconds": round(total_seconds, 2),
            "analyzed_seconds": round(samples.size / rate, 2) if rate else 0,
        }
    )

    if samples.size < rate * 0.5:
        result.add("low", "Very short audio", "Less than half a second of audio gives detectors almost nothing to analyze.")
        return result

    peak = float(np.max(np.abs(samples)))
    result.data["peak"] = round(peak, 4)
    if peak < 1e-4:
        result.add("medium", "Audio is effectively silent", "The track has no measurable signal.")
        return result

    block = max(1, int(rate * BLOCK_SECONDS))
    usable = (samples.size // block) * block
    blocks = samples[:usable].reshape(-1, block)
    rms = np.sqrt(np.mean(blocks**2, axis=1))
    silent = rms < 0.02 * peak
    silence_ratio = float(silent.mean())
    exact_zero_ratio = float((np.abs(blocks).max(axis=1) == 0).mean())
    result.data["silence_ratio"] = round(silence_ratio, 3)
    result.data["exact_zero_ratio"] = round(exact_zero_ratio, 3)

    if exact_zero_ratio > 0.05:
        result.add(
            "low",
            "Segments of exact digital silence",
            "Real recordings keep a small noise floor. Perfect zeros often come from gating, splicing, or synthetic generation.",
        )

    speech = rms[~silent]
    if speech.size >= 20 and speech.mean() > 0:
        variation = float(speech.std() / speech.mean())
        result.data["loudness_variation"] = round(variation, 3)
        if variation < 0.25:
            result.add(
                "low",
                "Unusually uniform loudness",
                "Natural speech rises and falls. Very flat loudness can indicate heavy processing or synthetic voice.",
            )

    jumps = np.abs(np.diff(samples))
    abrupt = int(np.sum(jumps > 0.5 * peak))
    result.data["abrupt_jumps"] = abrupt
    if abrupt > 5:
        result.add(
            "low",
            "Abrupt waveform discontinuities",
            f"{abrupt} sudden jumps were found, which can mark splice points or clipping artifacts.",
        )

    cutoff = bandwidth_hz(samples, rate)
    result.data["bandwidth_hz"] = round(cutoff, 1)
    if rate >= 32000 and cutoff < 5000:
        result.add(
            "low",
            "Narrow frequency range",
            f"Almost all energy sits below {cutoff:.0f} Hz despite a {rate} Hz sample rate. This matches phone-quality or low-grade synthetic audio.",
        )
    return result
