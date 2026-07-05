"""Document Intake Resolver — Deterministic file-type probe and tool routing helper.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V2 Section 10A:
- Pure helper module — no LLM, no system_entry, no execution.
- Consumed by document_local_read capability compiler only.
- Deterministic local file-header probing (max 8KB).
- No cloud, no external API, no staging.
"""

import csv
import os
import zipfile
from typing import Any


# ---------------------------------------------------------------------------
# File-type detection constants
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG"
_JPEG_MAGIC = b"\xff\xd8"
_ZIP_MAGIC = b"PK\x03\x04"

# Minimum bytes needed for reliable magic detection
_MIN_MAGIC_BYTES = 8

# Max bytes to read for probing
_PROBE_MAX_BYTES = 8192

# Max bytes for CSV sniffer sample
_CSV_SNIFFER_MAX_BYTES = 4096

# Text-encode fallback for plain-text detection
_TEXT_ENCODING_FALLBACKS = ["utf-8", "ascii", "latin-1"]


# ---------------------------------------------------------------------------
# Tool -> expected extension mapping
# ---------------------------------------------------------------------------

_TOOL_EXPECTED_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "read_pdf": (".pdf",),
    "read_docx": (".docx",),
    "read_spreadsheet": (".xlsx",),
    "read_csv": (".csv",),
    "read_image_text": (".png", ".jpg", ".jpeg"),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_probe_sample(path: str, max_bytes: int = _PROBE_MAX_BYTES) -> bytes | None:
    """Read bounded leading bytes from an existing file."""
    try:
        with open(path, "rb") as f:
            return f.read(max_bytes)
    except (OSError, IOError):
        return None


def _has_expected_extension(path: str, tool: str) -> bool:
    """Return True if path ends with any extension expected by the tool."""
    lower = path.lower()
    exts = _TOOL_EXPECTED_EXTENSIONS.get(tool, ())
    return any(lower.endswith(ext) for ext in exts)


def _looks_like_printable_text(data: bytes) -> bool:
    """Return True if data appears to be plain printable text."""
    # Try standard encodings
    for encoding in _TEXT_ENCODING_FALLBACKS:
        try:
            text = data.decode(encoding)
            # Reject if contains null bytes (binary marker)
            if "\x00" in text:
                return False
            # Heuristic: mostly printable characters
            printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
            if len(text) > 0 and printable / len(text) > 0.90:
                return True
        except (UnicodeDecodeError, LookupError):
            continue
    return False


def _is_strong_csv(data: bytes) -> bool:
    """
    Return True if data is strongly identified as CSV.
    Requirements:
    - Decodes as text with no null bytes.
    - csv.Sniffer identifies a delimiter.
    - Consistent field count across first 3-5 non-empty lines.
    - More than 1 field per row.
    """
    if not data:
        return False

    text = None
    for encoding in _TEXT_ENCODING_FALLBACKS:
        try:
            text = data[:_CSV_SNIFFER_MAX_BYTES].decode(encoding)
            if "\x00" in text:
                return False
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        return False

    # csv.Sniffer
    sample = text[:_CSV_SNIFFER_MAX_BYTES]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        return False

    # Check consistent field count across first non-empty lines
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    field_counts = []
    for line in lines[:5]:
        # Very rough split — csv.reader would be more accurate but we want speed
        # Use the detected delimiter
        parts = line.split(delimiter)
        field_counts.append(len(parts))

    if not field_counts:
        return False

    # Must have >1 field per row
    if any(fc <= 1 for fc in field_counts):
        return False

    # Consistent across at least the first 3 lines (or all if fewer)
    check_lines = min(3, len(field_counts))
    first_count = field_counts[0]
    for i in range(1, check_lines):
        if field_counts[i] != first_count:
            return False

    return True


def _detect_type_from_probe(data: bytes, path: str) -> dict:
    """
    Inspect leading bytes and return a deterministic type result.
    Does NOT attempt full parsing — header/signature only.
    """
    if not data:
        return {
            "detected_type": "unknown",
            "confidence": "low",
            "source": "unknown",
            "reason": "Could not read file probe sample",
        }

    # PDF
    if data.startswith(_PDF_MAGIC):
        return {
            "detected_type": "pdf",
            "confidence": "high",
            "source": "magic_bytes",
            "reason": "Header starts with %PDF-",
        }

    # PNG
    if data.startswith(_PNG_MAGIC):
        return {
            "detected_type": "png",
            "confidence": "high",
            "source": "magic_bytes",
            "reason": "Header starts with \\x89PNG",
        }

    # JPEG
    if data.startswith(_JPEG_MAGIC):
        return {
            "detected_type": "jpeg",
            "confidence": "high",
            "source": "magic_bytes",
            "reason": "Header starts with \\xff\\xd8",
        }

    # ZIP-based (DOCX / XLSX)
    if data.startswith(_ZIP_MAGIC):
        if len(data) >= _MIN_MAGIC_BYTES:
            return _probe_zip_contents(path)
        return {
            "detected_type": "unknown",
            "confidence": "low",
            "source": "unknown",
            "reason": "ZIP-like header but insufficient data for member inspection",
        }

    # CSV (after printable text check)
    if _looks_like_printable_text(data) and _is_strong_csv(data):
        return {
            "detected_type": "csv",
            "confidence": "medium",
            "source": "csv_sniffer",
            "reason": "Text decodable as printable with consistent delimited fields",
        }

    # Plain text
    if _looks_like_printable_text(data):
        return {
            "detected_type": "text",
            "confidence": "medium",
            "source": "text_heuristic",
            "reason": "Decodes as printable text without null bytes",
        }

    # Unknown binary
    return {
        "detected_type": "unknown",
        "confidence": "low",
        "source": "unknown",
        "reason": "Unrecognized binary content",
    }


def _probe_zip_contents(path: str) -> dict:
    """
    Inspect a ZIP file for DOCX/XLSX signatures without extracting.
    """
    try:
        if not zipfile.is_zipfile(path):
            return {
                "detected_type": "unknown",
                "confidence": "low",
                "source": "unknown",
                "reason": "PK header present but not a valid ZIP",
            }

        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return {
                    "detected_type": "docx",
                    "confidence": "high",
                    "source": "zip_members",
                    "reason": "ZIP archive contains word/document.xml",
                }
            if "xl/workbook.xml" in names:
                return {
                    "detected_type": "xlsx",
                    "confidence": "high",
                    "source": "zip_members",
                    "reason": "ZIP archive contains xl/workbook.xml",
                }
            return {
                "detected_type": "unknown",
                "confidence": "low",
                "source": "unknown",
                "reason": "ZIP archive does not contain DOCX/XLSX member signatures",
            }
    except (zipfile.BadZipFile, OSError, IOError):
        return {
            "detected_type": "unknown",
            "confidence": "low",
            "source": "unknown",
            "reason": "ZIP inspection failed",
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def probe_file_type(path: str) -> dict:
    """
    Read a bounded sample and return a deterministic type result.

    Return shape:
    {
        "detected_type": "pdf" | "docx" | "xlsx" | "png" | "jpeg" | "csv" | "text" | "unknown",
        "confidence": "high" | "medium" | "low",
        "source": "magic_bytes" | "zip_members" | "csv_sniffer" | "text_heuristic" | "unknown",
        "reason": str,
    }
    """
    if not path or not isinstance(path, str):
        return {
            "detected_type": "unknown",
            "confidence": "low",
            "source": "unknown",
            "reason": "Invalid or empty path",
        }

    if not os.path.exists(path):
        return {
            "detected_type": "unknown",
            "confidence": "low",
            "source": "unknown",
            "reason": "File does not exist; cannot probe content",
        }

    data = _read_probe_sample(path)
    return _detect_type_from_probe(data, path)


def is_extensionless_acceptable(expected_tool: str, path: str) -> bool:
    """
    Returns True only when path has no supported extension for the expected tool
    and probe_file_type confirms the file content matches expected_tool.
    """
    if not path or not isinstance(path, str):
        return False

    # If the expected extension IS present, this function is not the authority.
    # The caller should have already accepted the extension.
    if _has_expected_extension(path, expected_tool):
        return True

    # File must exist to probe
    if not os.path.exists(path):
        return False

    probe = probe_file_type(path)
    detected = probe.get("detected_type", "unknown")

    mapping = {
        "read_pdf": {"pdf"},
        "read_docx": {"docx"},
        "read_spreadsheet": {"xlsx"},
        "read_csv": {"csv"},
        "read_image_text": {"png", "jpeg"},
        "read_pdf_ocr": {"pdf"},
    }

    return detected in mapping.get(expected_tool, set())


def resolve_document_tool(file_path: str, user_input: str = "") -> dict:
    """
    Used by document_local_read_capability.py at compile time.

    Return shape:
    {
        "tool": "read_file" | "read_pdf" | "read_pdf_ocr" | "read_docx" | "read_csv" | "read_spreadsheet" | "read_image_text" | None,
        "reason": str,
        "confidence": "high" | "medium" | "low",
        "source": "explicit_ocr_intent" | "extension" | "content_signature" | "zip_members" | "csv_sniffer" | "text_heuristic" | "unsupported",
        "detected_type": str,
    }
    """
    if not file_path or not isinstance(file_path, str):
        return {
            "tool": None,
            "reason": "Empty or invalid file path",
            "confidence": "low",
            "source": "unsupported",
            "detected_type": "unknown",
        }

    lower_path = file_path.lower()

    # --- 1. Explicit OCR/scanned intent + PDF path ---
    _OCR_KEYWORDS = frozenset([
        "ocr", "scanned", "scan", "image-only", "image only",
        "read text from scanned", "extract text from scanned",
    ])
    user_lower = (user_input or "").lower()
    has_ocr_intent = any(kw in user_lower for kw in _OCR_KEYWORDS)

    if has_ocr_intent:
        if lower_path.endswith(".pdf"):
            return {
                "tool": "read_pdf_ocr",
                "reason": "Explicit OCR intent + .pdf extension",
                "confidence": "high",
                "source": "explicit_ocr_intent",
                "detected_type": "pdf",
            }
        # Extensionless PDF with OCR intent — probe if file exists
        if os.path.exists(file_path):
            probe = probe_file_type(file_path)
            if probe.get("detected_type") == "pdf":
                return {
                    "tool": "read_pdf_ocr",
                    "reason": "Explicit OCR intent + extensionless PDF confirmed by content signature",
                    "confidence": "high",
                    "source": "explicit_ocr_intent",
                    "detected_type": "pdf",
                }

    # --- 2. Known extension fast path ---
    if lower_path.endswith(".pdf"):
        return {
            "tool": "read_pdf",
            "reason": "Path ends with .pdf",
            "confidence": "high",
            "source": "extension",
            "detected_type": "pdf",
        }
    if lower_path.endswith(".docx"):
        return {
            "tool": "read_docx",
            "reason": "Path ends with .docx",
            "confidence": "high",
            "source": "extension",
            "detected_type": "docx",
        }
    if lower_path.endswith(".csv"):
        return {
            "tool": "read_csv",
            "reason": "Path ends with .csv",
            "confidence": "high",
            "source": "extension",
            "detected_type": "csv",
        }
    if lower_path.endswith(".xlsx"):
        return {
            "tool": "read_spreadsheet",
            "reason": "Path ends with .xlsx",
            "confidence": "high",
            "source": "extension",
            "detected_type": "xlsx",
        }
    if lower_path.endswith(".png") or lower_path.endswith(".jpg") or lower_path.endswith(".jpeg"):
        ext = ".png" if lower_path.endswith(".png") else (".jpg" if lower_path.endswith(".jpg") else ".jpeg")
        return {
            "tool": "read_image_text",
            "reason": f"Path ends with {ext}",
            "confidence": "high",
            "source": "extension",
            "detected_type": "png" if ext == ".png" else "jpeg",
        }
    # Text-like extensions -> read_file
    text_extensions = (
        ".txt", ".md", ".json", ".py", ".js", ".xml", ".yml", ".yaml",
        ".log", ".ini", ".cfg", ".conf", ".config",
    )
    if any(lower_path.endswith(ext) for ext in text_extensions):
        return {
            "tool": "read_file",
            "reason": f"Path ends with a text-like extension",
            "confidence": "high",
            "source": "extension",
            "detected_type": "text",
        }

    # --- 3. Extensionless path — probe content ---
    if os.path.exists(file_path):
        probe = probe_file_type(file_path)
        detected = probe.get("detected_type", "unknown")

        if detected == "pdf":
            return {
                "tool": "read_pdf",
                "reason": "Extensionless path with PDF content signature",
                "confidence": probe.get("confidence", "high"),
                "source": probe.get("source", "content_signature"),
                "detected_type": "pdf",
            }
        if detected == "docx":
            return {
                "tool": "read_docx",
                "reason": "Extensionless path with DOCX content signature",
                "confidence": probe.get("confidence", "high"),
                "source": probe.get("source", "content_signature"),
                "detected_type": "docx",
            }
        if detected == "xlsx":
            return {
                "tool": "read_spreadsheet",
                "reason": "Extensionless path with XLSX content signature",
                "confidence": probe.get("confidence", "high"),
                "source": probe.get("source", "content_signature"),
                "detected_type": "xlsx",
            }
        if detected == "csv":
            return {
                "tool": "read_csv",
                "reason": "Extensionless path with CSV content signature",
                "confidence": probe.get("confidence", "medium"),
                "source": probe.get("source", "csv_sniffer"),
                "detected_type": "csv",
            }
        if detected in ("png", "jpeg"):
            return {
                "tool": "read_image_text",
                "reason": "Extensionless path with image content signature",
                "confidence": probe.get("confidence", "high"),
                "source": probe.get("source", "content_signature"),
                "detected_type": detected,
            }
        if detected == "text":
            return {
                "tool": "read_file",
                "reason": "Extensionless path with plain text content signature",
                "confidence": probe.get("confidence", "medium"),
                "source": probe.get("source", "text_heuristic"),
                "detected_type": "text",
            }
        # Unknown binary — do NOT route to read_file
        return {
            "tool": None,
            "reason": "Extensionless path with unrecognized or binary content; no safe reader determined",
            "confidence": "low",
            "source": "unsupported",
            "detected_type": "unknown",
        }

    # --- 4. Extensionless and file does not exist ---
    return {
        "tool": None,
        "reason": "Extensionless path and file does not exist; cannot determine safe reader",
        "confidence": "low",
        "source": "unsupported",
        "detected_type": "unknown",
    }
