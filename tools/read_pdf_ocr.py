INPUT_SPEC = {
    "path": "string",
    "max_pages": "number"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

_DEFAULT_MAX_PAGES = 10
_RENDER_DPI = 150


def run(path, max_pages=None):
    """
    Extract text from a scanned/image-only PDF using OCR (Tesseract).

    Renders bounded pages to images and OCRs each page.
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
        if not full_path.lower().endswith(".pdf"):
            return {"status": "failure", "reason": "unsupported_format"}

        # Bound max_pages
        page_limit = max_pages if isinstance(max_pages, int) and max_pages > 0 else _DEFAULT_MAX_PAGES

        # Convert PDF pages to images
        from pdf2image import convert_from_path

        images = convert_from_path(
            full_path,
            first_page=1,
            last_page=page_limit,
            dpi=_RENDER_DPI,
        )

        total_pages = len(images)

        if total_pages == 0:
            return {"status": "failure", "reason": "parse_error"}

        # OCR each page
        import pytesseract

        parts = []
        for i, img in enumerate(images, start=1):
            page_text = pytesseract.image_to_string(img).strip()
            if page_text:
                parts.append(f"\n\n--- Page {i} ---\n\n{page_text}")

        extracted = "".join(parts).strip()

        metadata = {
            "source_path": full_path,
            "format": "pdf",
            "ocr_engine": "tesseract",
            "render_dpi": _RENDER_DPI,
            "pages_processed": total_pages,
            "max_pages": page_limit,
            "page_limit_applied": total_pages >= page_limit,
        }

        if not extracted:
            metadata["note"] = "No text detected in scanned PDF pages."
            return {
                "status": "success",
                "result": "",
                "metadata": metadata,
            }

        notes = []
        if total_pages >= page_limit:
            notes.append("Additional pages omitted due to OCR page limit.")

        result_text = extracted
        if notes:
            result_text += "\n\n" + "\n".join(notes)

        return {
            "status": "success",
            "result": result_text,
            "metadata": metadata,
        }

    except Exception:
        return {"status": "failure", "reason": "read_error"}
