INPUT_SPEC = {
    "url": "string"
}

def run(url):
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

    except requests.exceptions.Timeout:
        return {"status": "failure", "reason": "timeout"}
    except requests.exceptions.RequestException:
        return {"status": "failure", "reason": "network_error"}
    except Exception:
        return {"status": "failure", "reason": "network_error"}