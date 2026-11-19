import hashlib
import mimetypes
import shutil
import subprocess
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma"}


def detect_media_type(path):
    suffix = Path(path).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    guess, _ = mimetypes.guess_type(str(path))
    if guess:
        major = guess.split("/")[0]
        if major in ("video", "image", "audio"):
            return major
    return "unknown"


def sha256_of(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def tool_available(name):
    return shutil.which(name) is not None


def run_command(args, timeout=120):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
