INPUT_SPEC = {
    "query": "string"
}

import requests
from bs4 import BeautifulSoup
import urllib.parse
import os

def run(*args):
    query = args[0]

    try:
        url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)

        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(response.text, "html.parser")

        results = soup.select(".result__snippet")

        if results:
            return results[0].get_text(strip=True)

        return "No results found"

    except requests.exceptions.RequestException as e:
        return f"Error during request: {e}"
    except Exception as e:
        return f"Error: {e}"