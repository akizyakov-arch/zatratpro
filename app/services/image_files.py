"""Image preparation shared by file adapters."""
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageOps
from app.config import TMP_DIR

OCR_MAX_WIDTH = 2000
OCR_JPEG_QUALITY = 88

def prepare_image(source_path: Path, directory=None) -> Path:
    prepared_path = (directory or TMP_DIR) / f"{uuid4()}.jpg"
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            width, height = image.size
            if width > OCR_MAX_WIDTH:
                resized_height = int(height * (OCR_MAX_WIDTH / width))
                image = image.resize((OCR_MAX_WIDTH, resized_height), Image.Resampling.LANCZOS)
            image.save(prepared_path, format="JPEG", quality=OCR_JPEG_QUALITY, optimize=True)
    except BaseException:
        prepared_path.unlink(missing_ok=True)
        raise
    return prepared_path
