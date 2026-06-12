INPUT_SPEC = {
    "url": "string"
}

def run(url):
    import sys
    import os
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from system.security.url_validator import validate_url

    validation = validate_url(url)
    if validation.get("status") == "failure":
        return validation

    try:
        import requests
        from bs4 import BeautifulSoup

        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup.find_all(["script", "style"]):
            tag.extract()

        text = soup.get_text(separator="\n")

        return {"status": "success", "result": text[:5000]}

    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        return {"status": "failure", "reason": "http_error", "detail": f"HTTP {status_code}"}
    except requests.exceptions.Timeout:
        return {"status": "failure", "reason": "timeout"}
    except requests.exceptions.ConnectionError as e:
        return {"status": "failure", "reason": "connection_error", "detail": str(e)}
    except requests.exceptions.RequestException as e:
        return {"status": "failure", "reason": "network_error", "detail": str(e)}
    except Exception:
        return {"status": "failure", "reason": "network_error"}