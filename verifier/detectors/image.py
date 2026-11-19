import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from verifier.models import DetectorResult

NAME = "Image forensics"
EDITING_SOFTWARE = (
    "photoshop",
    "gimp",
    "lightroom",
    "affinity",
    "pixelmator",
    "snapseed",
    "canva",
    "facetune",
    "picsart",
    "paint.net",
)
GENERATOR_NAMES = (
    "stable diffusion",
    "midjourney",
    "dall-e",
    "dall·e",
    "firefly",
    "comfyui",
    "automatic1111",
    "invokeai",
    "novelai",
    "leonardo",
    "sdxl",
)
GENERATOR_KEYS = ("parameters", "prompt", "workflow", "sd-metadata", "invokeai_metadata", "negative_prompt")
RAW_MARKERS = {
    b"c2pa": ("info", "Content Credentials (C2PA) data present", "The file carries provenance metadata. Verify it with a C2PA validator."),
    b"trainedalgorithmicmedia": (
        "high",
        "Marked as AI-generated in metadata",
        "The IPTC digital source type declares this image as created by a trained algorithm.",
    ),
    b"midjourney": ("high", "Midjourney reference in file data", "The raw file contains the string 'Midjourney'."),
    b"stable diffusion": ("high", "Stable Diffusion reference in file data", "The raw file contains the string 'Stable Diffusion'."),
    b"dall-e": ("high", "DALL-E reference in file data", "The raw file contains the string 'DALL-E'."),
}
MAX_RAW_BYTES = 50 * 1024 * 1024
MAX_ELA_PIXELS = 40_000_000
EXIF_SOFTWARE = 305
EXIF_DATETIME = 306
EXIF_MAKE = 271
EXIF_MODEL = 272
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 36867


def error_level_map(image, quality=90):
    rgb = image.convert("RGB")
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as recompressed:
        difference = ImageChops.difference(rgb, recompressed.convert("RGB"))
    return np.asarray(difference, dtype=np.float64).mean(axis=2)


def block_means(values, grid=8):
    height, width = values.shape
    block_h, block_w = height // grid, width // grid
    if block_h == 0 or block_w == 0:
        return np.array([])
    trimmed = values[: block_h * grid, : block_w * grid]
    return trimmed.reshape(grid, block_h, grid, block_w).mean(axis=(1, 3)).flatten()


def save_error_map(values, destination):
    peak = float(values.max())
    scaled = values * (255.0 / peak) if peak > 0 else values
    Image.fromarray(np.clip(scaled, 0, 255).astype("uint8")).save(destination)


def inspect_metadata(result, image, path):
    exif = image.getexif()
    software = str(exif.get(EXIF_SOFTWARE, "")).strip()
    make = str(exif.get(EXIF_MAKE, "")).strip()
    model = str(exif.get(EXIF_MODEL, "")).strip()
    modified = str(exif.get(EXIF_DATETIME, "")).strip()
    try:
        original = str(exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL, "")).strip()
    except (KeyError, ValueError, AttributeError):
        original = ""

    result.data["exif"] = {
        "present": bool(exif),
        "make": make or None,
        "model": model or None,
        "software": software or None,
        "datetime": modified or None,
        "datetime_original": original or None,
    }

    if not exif:
        result.add(
            "low",
            "No EXIF metadata",
            "Camera photos normally carry EXIF data. Social platforms strip it, but generated and edited images often lack it as well.",
        )
    elif not make and not model:
        result.add("low", "No camera make or model", "EXIF exists but does not name a camera.")

    lowered_software = software.lower()
    if any(name in lowered_software for name in GENERATOR_NAMES):
        result.add("high", "AI generator named in EXIF", f"The Software tag reads '{software}'.")
    elif any(name in lowered_software for name in EDITING_SOFTWARE):
        result.add("medium", "Edited with image software", f"The Software tag reads '{software}'.")

    if modified and original and modified != original:
        result.add(
            "medium",
            "Modification time differs from capture time",
            f"Captured {original}, last modified {modified}. The file was saved again after capture.",
        )

    info_keys = {str(key).lower(): value for key, value in (image.info or {}).items()}
    matched = [key for key in GENERATOR_KEYS if key in info_keys]
    if matched:
        result.add(
            "high",
            "Generator-style metadata fields",
            f"The file contains fields typical of AI image tools: {', '.join(matched)}.",
        )
    for key, value in info_keys.items():
        if isinstance(value, str) and any(name in value.lower() for name in GENERATOR_NAMES):
            result.add("high", "AI generator named in file text", f"Field '{key}' mentions an AI image generator.")
            break

    if path.stat().st_size <= MAX_RAW_BYTES:
        raw = path.read_bytes().lower()
        for marker, (severity, title, detail) in RAW_MARKERS.items():
            if marker in raw:
                result.add(severity, title, detail)


def inspect_dimensions(result, width, height):
    if max(width, height) >= 512 and width % 64 == 0 and height % 64 == 0:
        result.add(
            "low",
            "Dimensions typical of AI generators",
            f"{width}x{height} are both multiples of 64, which many generators produce. Cropped or resized photos can match by chance.",
        )


def inspect_ela(result, image, path, output_dir):
    if image.width * image.height > MAX_ELA_PIXELS:
        result.add("info", "ELA skipped", "The image is too large for error level analysis.")
        return
    values = error_level_map(image)
    blocks = block_means(values)
    is_jpeg = (image.format or "").upper() in ("JPEG", "MPO")
    median = float(np.median(blocks)) if blocks.size else 0.0
    peak = float(blocks.max()) if blocks.size else 0.0
    ratio = peak / median if median > 0.05 else 0.0
    result.data["ela"] = {
        "mean": round(float(values.mean()), 3),
        "max": round(float(values.max()), 3),
        "hotspot_ratio": round(ratio, 2),
        "reliable": is_jpeg,
    }
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    map_name = "ela_map.png"
    save_error_map(values, output_dir / map_name)
    result.data["ela_map_file"] = map_name

    if not is_jpeg:
        result.add(
            "info",
            "ELA is less reliable for this format",
            "Error level analysis works best on JPEG files. Treat the map as a rough guide only.",
        )
        return
    if ratio > 4:
        result.add(
            "medium",
            "Localized error level hotspot",
            f"One region compresses {ratio:.1f}x differently from the median block, which can indicate a pasted or retouched area.",
        )
    elif ratio > 2.5:
        result.add(
            "low",
            "Uneven error levels",
            f"One region differs {ratio:.1f}x from the median block. Textured areas can cause this naturally, so check the map visually.",
        )


def analyze(path, output_dir):
    path = Path(path)
    result = DetectorResult(NAME)
    try:
        with Image.open(path) as image:
            image.load()
            result.data.update(
                {
                    "format": image.format,
                    "mode": image.mode,
                    "width": image.width,
                    "height": image.height,
                }
            )
            inspect_metadata(result, image, path)
            inspect_dimensions(result, image.width, image.height)
            inspect_ela(result, image, path, output_dir)
    except (OSError, ValueError) as exc:
        result.status = "error"
        result.note = f"Could not read image: {exc}"
    return result
