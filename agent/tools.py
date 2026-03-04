import os
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

def write_file(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"saved": path, "bytes": len(content.encode("utf-8"))}

def http_get(url):
    r = requests.get(url, timeout=20, headers={"User-Agent": "cloud-manus/1.0"})
    text = r.text[:200000]
    # optional: quick extract title
    title = None
    try:
        soup = BeautifulSoup(text, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
    except Exception:
        pass
    return {"url": url, "status": r.status_code, "title": title, "text": text}

def web_search(query: str, max_results: int = 5):
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title"),
                "url": r.get("href"),
                "snippet": r.get("body"),
            })
    return {"query": query, "results": results}

def read_webpage(url):
    import requests
    from bs4 import BeautifulSoup

    r = requests.get(url, timeout=20)

    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(separator="\n")

    return {
        "url": url,
        "text": text[:20000]
    }

TOOLS = {
    "write_file": write_file,
    "http_get": http_get,
    "web_search": web_search,
    "read_webpage": read_webpage,
}

