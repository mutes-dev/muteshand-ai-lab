INPUT_SPEC = {
    "url": "string"
}

# Maximum characters to return in a successful result
MAX_RESULT_LENGTH = 5000

# Tags whose content should be stripped from HTML before text extraction.
# These carry no meaningful article text for LLM consumption.
_NOISY_HTML_TAGS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "object",
    "embed",
    "svg",
    "canvas",
    "form",
    "input",
    "textarea",
    "button",
    "select",
    "option",
    "video",
    "audio",
    "source",
    "track",
    "map",
    "area",
    "math",
    "template",
]


def _is_html_content(response, text):
    """Return True if the response should be treated as HTML."""
    content_type = response.headers.get("content-type", "")
    if content_type:
        ct = content_type.lower()
        if "text/html" in ct or "application/xhtml+xml" in ct:
            return True
        # Clearly non-HTML textual types where we should avoid HTML parsing
        if any(ct.startswith(prefix) for prefix in (
            "application/json",
            "text/plain",
            "application/pdf",
            "image/",
            "audio/",
            "video/",
            "application/octet-stream",
        )):
            return False
    # Fallback: sniff for HTML document marker in first 200 chars
    stripped = text[:200].lstrip()
    if stripped.startswith("<html") or stripped.startswith("<!DOCTYPE"):
        return True
    return False


def _normalize_whitespace(text):
    """Collapse consecutive blank lines and trim edges."""
    lines = text.splitlines()
    result_lines = []
    prev_blank = False
    for line in lines:
        stripped = line.rstrip()
        is_blank = stripped == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(stripped)
        prev_blank = is_blank
    # Trim leading blank lines
    while result_lines and result_lines[0] == "":
        result_lines.pop(0)
    # Trim trailing blank lines
    while result_lines and result_lines[-1] == "":
        result_lines.pop()
    return "\n".join(result_lines)


def _extract_clean_text_from_html(html_text):
    """Parse HTML, strip noisy tags, extract title and body text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")

    # Title extraction from <head>
    title = None
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        title = " ".join(str(title_tag.string).split())

    # Strip noisy tags
    for tag_name in _NOISY_HTML_TAGS:
        for tag in soup.find_all(tag_name):
            tag.extract()

    # Extract body text
    body_text = soup.get_text(separator="\n")
    body_text = _normalize_whitespace(body_text)

    if title:
        return f"Title: {title}\n\n{body_text}"

    return body_text


def _build_observation(url, status, result_text="", title=None, final_url=None,
                       content_length=None, extracted_length=None,
                       failure_reason=None, detail=None):
    """Build a bounded read_webpage observation, tolerating import failure."""
    try:
        import sys
        import os
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.tools.webpage.observation import build_read_webpage_observation
        return build_read_webpage_observation(
            requested_url=url,
            status=status,
            result_text=result_text,
            title=title,
            final_url=final_url,
            content_length=content_length,
            extracted_length=extracted_length,
            failure_reason=failure_reason,
            detail=detail,
        )
    except Exception:
        return None


def _extract_title_from_cleaned(text):
    """Extract the embedded title from cleaned HTML output if present."""
    if text.startswith("Title: "):
        head, _, _ = text.partition("\n\n")
        return head[len("Title: "):].strip()
    return None


def run(url):
    import sys
    import os
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from system.security.url_validator import validate_url

    validation = validate_url(url)
    if validation.get("status") == "failure":
        observation = _build_observation(
            url=url,
            status="failure",
            failure_reason=validation.get("reason"),
            detail=validation.get("detail"),
        )
        return {
            "status": "failure",
            "reason": validation.get("reason", "url_safety_blocked"),
            "detail": validation.get("detail", "URL validation failed"),
            "observation": observation,
        }

    try:
        import requests

        # ADOPT-002: SSL verification enabled; redirects blocked to prevent SSRF
        response = requests.get(url, timeout=10, verify=True, allow_redirects=False)

        # Block redirects as SSRF defense-in-depth
        if response.is_redirect or response.is_permanent_redirect:
            observation = _build_observation(
                url=url,
                status="failure",
                failure_reason="url_safety_blocked",
                detail="redirects are blocked for security",
            )
            return {
                "status": "failure",
                "reason": "url_safety_blocked",
                "detail": "redirects are blocked for security",
                "observation": observation,
            }

        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        raw_text = response.text

        # Content-type awareness: only parse as HTML when appropriate
        if _is_html_content(response, raw_text):
            try:
                text = _extract_clean_text_from_html(raw_text)
            except Exception:
                # Malformed HTML fallback: return raw text safely
                text = raw_text
        else:
            text = raw_text

        result_text = text[:MAX_RESULT_LENGTH]
        title = _extract_title_from_cleaned(text)
        observation = _build_observation(
            url=url,
            status="success",
            result_text=result_text,
            title=title,
            final_url=url,
            content_length=len(raw_text),
            extracted_length=len(text),
        )
        return {"status": "success", "result": result_text, "observation": observation}

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        observation = _build_observation(
            url=url,
            status="failure",
            failure_reason="http_error",
            detail=f"HTTP {status_code}",
        )
        return {
            "status": "failure",
            "reason": "http_error",
            "detail": f"HTTP {status_code}",
            "observation": observation,
        }
    except requests.exceptions.Timeout:
        observation = _build_observation(
            url=url,
            status="failure",
            failure_reason="timeout",
        )
        return {
            "status": "failure",
            "reason": "timeout",
            "observation": observation,
        }
    except requests.exceptions.ConnectionError as e:
        observation = _build_observation(
            url=url,
            status="failure",
            failure_reason="connection_error",
            detail=str(e),
        )
        return {
            "status": "failure",
            "reason": "connection_error",
            "detail": str(e),
            "observation": observation,
        }
    except requests.exceptions.RequestException as e:
        observation = _build_observation(
            url=url,
            status="failure",
            failure_reason="network_error",
            detail=str(e),
        )
        return {
            "status": "failure",
            "reason": "network_error",
            "detail": str(e),
            "observation": observation,
        }
    except Exception:
        observation = _build_observation(
            url=url,
            status="failure",
            failure_reason="network_error",
        )
        return {
            "status": "failure",
            "reason": "network_error",
            "observation": observation,
        }