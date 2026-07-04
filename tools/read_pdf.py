INPUT_SPEC = {
    "path": "string"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")


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

        # Check extension
        if not full_path.lower().endswith(".pdf"):
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

        return {
            "status": "success",
            "result": extracted,
            "metadata": {
                "source_path": full_path,
                "format": "pdf",
                "page_count": page_count,
            },
        }

    except Exception:
        return {"status": "failure", "reason": "read_error"}
