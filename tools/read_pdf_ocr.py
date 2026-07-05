INPUT_SPEC = {
    "path": "string",
    "max_pages": "number"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

_DEFAULT_MAX_PAGES = 10
_RENDER_DPI = 150


def _is_extensionless_or_pdf(path: str) -> bool:
    """Return True if path ends with .pdf or resolver confirms PDF content."""
    lower = path.lower()
    if lower.endswith(".pdf"):
        return True
    # Only probe if there is truly no extension
    basename = os.path.basename(path)
    if "." in basename:
        return False
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from system.orchestrator.capabilities.document_intake_resolver import is_extensionless_acceptable
    return is_extensionless_acceptable("read_pdf_ocr", path)


def _extract_pdf_text_via_ocr(path: str, max_pages: int = _DEFAULT_MAX_PAGES, dpi: int = _RENDER_DPI) -> tuple[str, dict]:
    """
    Bounded local OCR extraction for PDF files.

    Returns (text, metadata).
    Caller is responsible for path safety validation.
    """
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(
        path,
        first_page=1,
        last_page=max_pages,
        dpi=dpi,
    )

    total_pages = len(images)

    if total_pages == 0:
        return "", {
            "ocr_engine": "tesseract",
            "render_dpi": dpi,
            "pages_processed": 0,
            "max_pages": max_pages,
            "page_limit_applied": False,
        }

    parts = []
    for i, img in enumerate(images, start=1):
        page_text = pytesseract.image_to_string(img).strip()
        if page_text:
            parts.append(f"\n\n--- Page {i} ---\n\n{page_text}")

    extracted = "".join(parts).strip()

    metadata = {
        "ocr_engine": "tesseract",
        "render_dpi": dpi,
        "pages_processed": total_pages,
        "max_pages": max_pages,
        "page_limit_applied": total_pages >= max_pages,
    }

    return extracted, metadata


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

        # Check extension (allow extensionless if resolver confirms PDF content)
        if not _is_extensionless_or_pdf(full_path):
            return {"status": "failure", "reason": "unsupported_format"}

        # Bound max_pages
        page_limit = max_pages if isinstance(max_pages, int) and max_pages > 0 else _DEFAULT_MAX_PAGES

        extracted, ocr_meta = _extract_pdf_text_via_ocr(full_path, max_pages=page_limit, dpi=_RENDER_DPI)

        total_pages = ocr_meta["pages_processed"]

        if total_pages == 0:
            return {"status": "failure", "reason": "parse_error"}

        metadata = {
            "source_path": full_path,
            "format": "pdf",
            "ocr_engine": ocr_meta["ocr_engine"],
            "render_dpi": ocr_meta["render_dpi"],
            "pages_processed": ocr_meta["pages_processed"],
            "max_pages": ocr_meta["max_pages"],
            "page_limit_applied": ocr_meta["page_limit_applied"],
        }

        if not extracted:
            metadata["note"] = "No text detected in scanned PDF pages."
            return {
                "status": "success",
                "result": "",
                "metadata": metadata,
            }

        notes = []
        if metadata["page_limit_applied"]:
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
