INPUT_SPEC = {
    "query": "string"
}

import requests
import json

def run(query):
    # Handle empty input
    if not query or not query.strip():
        return "No results found"
    
    try:
        url = "https://api.duckduckgo.com/"
        
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Field extraction (strict)
        title = data.get("Heading", "").strip()
        url_result = data.get("AbstractURL", "").strip()
        snippet = data.get("AbstractText", "").strip()
        
        # Empty result check
        if not title or not url_result or not snippet:
            return "No results found"
        
        # JSON string output
        return json.dumps({
            "title": title,
            "url": url_result,
            "snippet": snippet
        })

    except requests.exceptions.RequestException:
        return "No results found"
    except Exception:
        return "No results found"