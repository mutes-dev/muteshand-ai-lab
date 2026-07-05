INPUT_SPEC = {
    "path": "string"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

# Maximum dimension in pixels before downscaling for OCR
_MAX_IMAGE_DIMENSION = 4096


def _is_extensionless_or_image(path: str) -> bool:
    """Return True if path ends with image extension or resolver confirms image content."""
    lower = path.lower()
    if lower.endswith(".png") or lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return True
    # Only probe if there is truly no extension
    basename = os.path.basename(path)
    if "." in basename:
        return False
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from system.orchestrator.capabilities.document_intake_resolver import is_extensionless_acceptable
    return is_extensionless_acceptable("read_image_text", path)


def run(path):
    """
    Extract text from a local image file using OCR (Tesseract).

    Supports .png, .jpg, .jpeg.
    Returns structured dict for all cases.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        validation = validate_path(path, BASE_PATH)
        if validation.get("status") == "failure":
            return validation

        full_path = validation["resolved_path"]

        # Check if file exists
        if not os.path.exists(full_path):
            return {"status": "failure", "reason": "file_not_found"}

        # Check extension
        lower = full_path.lower()
        if not _is_extensionless_or_image(full_path):
            return {"status": "failure", "reason": "unsupported_format"}

        # Open image with Pillow
        from PIL import Image

        with Image.open(full_path) as img:
            original_width, original_height = img.size
            resized = False

            # Downscale if either dimension exceeds the bound
            max_dim = max(original_width, original_height)
            if max_dim > _MAX_IMAGE_DIMENSION:
                ratio = _MAX_IMAGE_DIMENSION / max_dim
                new_width = int(original_width * ratio)
                new_height = int(original_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                resized = True

            # Ensure image is in RGB mode for OCR
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Perform OCR
            import pytesseract

            ocr_text = pytesseract.image_to_string(img).strip()

        metadata = {
            "source_path": full_path,
            "format": os.path.splitext(full_path)[1].lower().lstrip("."),
            "width": original_width,
            "height": original_height,
            "resized": resized,
            "ocr_engine": "tesseract",
        }

        if not ocr_text:
            metadata["note"] = "No text detected in image."
            return {
                "status": "success",
                "result": "",
                "metadata": metadata,
            }

        return {
            "status": "success",
            "result": ocr_text,
            "metadata": metadata,
        }

    except Exception:
        return {"status": "failure", "reason": "read_error"}
