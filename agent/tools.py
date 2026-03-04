import os
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

from readability import Document


def write_file(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"saved": path, "bytes": len(content.encode("utf-8"))}


def web_search(query: str, max_results: int = 6):
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(
                {
                    "title": r.get("title"),
                    "url": r.get("href"),
                    "snippet": r.get("body"),
                }
            )
    return {"query": query, "results": results}


def read_webpage(url: str):
    r = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "cloud-manus/2.0"},
    )
    return {
        "url": url,
        "status": r.status_code,
        "final_url": str(r.url),
        "headers": dict(r.headers),
        "html": r.text[:500000],  # cap
    }


def extract_readable(html: str):
    """
    Extract main content using readability-lxml, then return cleaned text.
    """
    doc = Document(html)
    title = (doc.short_title() or "").strip()
    summary_html = doc.summary(html_partial=True)

    soup = BeautifulSoup(summary_html, "html.parser")
    text = soup.get_text(separator="\n")

    # Clean up
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    cleaned = "\n".join(lines)

    return {
        "title": title,
        "text": cleaned[:40000],  # cap
    }


TOOLS = {
    "write_file": write_file,
    "web_search": web_search,
    "read_webpage": read_webpage,
    "extract_readable": extract_readable,
}
