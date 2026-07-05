INPUT_SPEC = {
    "path": "string"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")


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
    return is_extensionless_acceptable("read_pdf", path)


def run(path):
    """
    Extract plain text from a local PDF file.

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

        # Extract text using pypdf
        from pypdf import PdfReader

        reader = PdfReader(full_path)
        page_count = len(reader.pages)

        if page_count == 0:
            return {"status": "failure", "reason": "parse_error"}

        parts = []
        for i, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text()
            if page_text:
                parts.append(f"\n\n--- Page {i} ---\n\n{page_text}")

        extracted = "".join(parts).strip()

        # --- OCR fallback for scanned/image-only PDFs ---
        _MIN_USABLE_TEXT_CHARS = 20
        metadata = {
            "source_path": full_path,
            "format": "pdf",
            "page_count": page_count,
        }

        if len(extracted.strip()) < _MIN_USABLE_TEXT_CHARS and page_count > 0:
            try:
                from tools.read_pdf_ocr import _extract_pdf_text_via_ocr
                ocr_text, ocr_meta = _extract_pdf_text_via_ocr(full_path)
                if ocr_text:
                    extracted = (
                        "[Note: This PDF had little or no extractable text. "
                        "Bounded local OCR was used to extract content.]\n\n"
                        + ocr_text
                    )
                    metadata["ocr_fallback"] = True
                    metadata["ocr_fallback_reason"] = (
                        "Text extraction produced little/no usable text; bounded local OCR was used."
                    )
                    metadata.update(ocr_meta)
                else:
                    metadata["ocr_fallback_attempted"] = True
                    metadata["ocr_fallback"] = False
                    metadata["ocr_fallback_reason"] = (
                        "Text extraction produced little/no usable text; bounded local OCR was attempted but no text was extracted."
                    )
            except Exception as _exc:
                metadata["ocr_fallback_attempted"] = True
                metadata["ocr_fallback"] = False
                metadata["ocr_fallback_error"] = str(_exc)

        return {
            "status": "success",
            "result": extracted,
            "metadata": metadata,
        }

    except Exception:
        return {"status": "failure", "reason": "read_error"}
