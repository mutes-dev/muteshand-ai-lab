INPUT_SPEC = {
    "query": "string"
}

import requests
from bs4 import BeautifulSoup


def run(query):
    """
    Search using DuckDuckGo HTML endpoint.
    
    Returns real search results with:
    - Titles
    - URLs
    - Snippets
    """
    # Handle empty input
    if not query or not query.strip():
        return "no results found"
    
    try:
        url = "https://html.duckduckgo.com/html/"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        params = {"q": query}
        
        response = requests.post(url, data=params, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract search results
        results = []
        result_divs = soup.find_all('div', class_='result')
        
        for div in result_divs[:5]:  # Top 5 results
            # Extract title and URL
            title_link = div.find('a', class_='result__a')
            if not title_link:
                continue
            
            title = title_link.get_text(strip=True)
            href = title_link.get('href', '')
            
            # Extract snippet
            snippet_elem = div.find('a', class_='result__snippet')
            if not snippet_elem:
                snippet_elem = div.find('div', class_='result__snippet')
            
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
            
            if title and href:
                results.append({
                    'title': title,
                    'url': href,
                    'snippet': snippet
                })
        
        # Build output
        if not results:
            return "no results found"
        
        output_lines = ["Top results:"]
        
        for i, result in enumerate(results[:3], 1):  # Top 3 for readability
            output_lines.append(f"\n{i}. {result['title']} — {result['url']}")
            if result['snippet']:
                output_lines.append(f"   {result['snippet']}")
        
        return "\n".join(output_lines)

    except requests.exceptions.RequestException:
        return "no results found"
    except Exception:
        return "no results found"