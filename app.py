"""
PageRank Analyzer — Backend
FastAPI server with real-time crawl progress via SSE
"""

import asyncio
import json
import time
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import networkx as nx
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="PageRank Analyzer")
templates = Jinja2Templates(directory="templates")


# ── Helpers ──────────────────────────────────────────────────────────────────

def normalize_url(url):
    parsed = urlparse(url)
    clean = parsed._replace(fragment="")
    return clean.geturl()


def should_skip(url):
    skip_ext = (
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".pdf", ".zip", ".mp3", ".mp4", ".css", ".js",
        ".ico", ".xml", ".json", ".woff", ".woff2", ".ttf",
        ".eot", ".map", ".gz", ".tar", ".rar",
    )
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in skip_ext)


def shorten_url(url, base_domain):
    parsed = urlparse(url)
    if parsed.netloc == base_domain:
        return parsed.path or "/"
    return url


# ── Crawler + PageRank (generator for SSE) ───────────────────────────────────

def crawl_and_analyze(start_url, max_pages=50, alpha=0.85):
    """
    Generator that yields SSE events as it crawls and analyzes.
    """
    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc

    visited = set()
    to_visit = [start_url]
    graph = nx.DiGraph()
    page_titles = {}
    page_status = {}
    last_ping = time.time()

    headers = {"User-Agent": "PageRank-Analyzer/1.0 (Educational Tool)"}
    session = requests.Session()
    session.headers.update(headers)

    yield _sse("status", {"message": f"Starting crawl of {base_domain}...", "phase": "crawling"})

    while to_visit and len(visited) < max_pages:
        url = normalize_url(to_visit.pop(0))

        if url in visited:
            continue

        # Send keepalive ping every 10 seconds to prevent Railway timeout
        if time.time() - last_ping > 10:
            yield ": keepalive\n\n"
            last_ping = time.time()

        try:
            response = session.get(url, timeout=5, allow_redirects=True)
            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                continue

            visited.add(url)
            page_status[url] = response.status_code
            soup = BeautifulSoup(response.text, "html.parser")

            title_tag = soup.find("title")
            page_titles[url] = title_tag.get_text(strip=True) if title_tag else ""

            links_found = 0
            for link in soup.find_all("a", href=True):
                href = link["href"]
                full_url = normalize_url(urljoin(url, href))
                parsed = urlparse(full_url)

                if parsed.netloc != base_domain:
                    continue
                if should_skip(full_url):
                    continue

                graph.add_edge(url, full_url)
                links_found += 1

                if full_url not in visited:
                    to_visit.append(full_url)

            yield _sse("progress", {
                "crawled": len(visited),
                "max_pages": max_pages,
                "current_url": shorten_url(url, base_domain),
                "title": page_titles.get(url, ""),
                "links_found": links_found,
                "queued": len(to_visit),
            })

            time.sleep(0.15)

        except requests.RequestException:
            yield _sse("error_page", {"url": shorten_url(url, base_domain)})
            continue

    # ── Analysis phase ───────────────────────────────────────────────────
    yield _sse("status", {"message": "Calculating PageRank...", "phase": "analyzing"})

    if graph.number_of_nodes() == 0:
        yield _sse("done", {"error": "No pages found. Check the URL and try again."})
        return

    scores = nx.pagerank(graph, alpha=alpha)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    in_degrees = dict(graph.in_degree())
    out_degrees = dict(graph.out_degree())

    # Build results
    pages = []
    for i, (url, score) in enumerate(ranked, 1):
        pages.append({
            "rank": i,
            "url": url,
            "path": shorten_url(url, base_domain),
            "title": page_titles.get(url, ""),
            "score": round(score, 8),
            "links_in": in_degrees.get(url, 0),
            "links_out": out_degrees.get(url, 0),
            "status": page_status.get(url, 0),
        })

    # Find issues
    orphans = [shorten_url(u, base_domain) for u, d in in_degrees.items() if d == 0]
    dead_ends = [shorten_url(u, base_domain) for u, d in out_degrees.items() if d == 0]
    avg_score = 1.0 / max(graph.number_of_nodes(), 1)
    weak = [p["path"] for p in pages if p["score"] < avg_score * 0.5]

    # Build link data for visualization
    nodes_set = set()
    links_data = []
    for u, v in graph.edges():
        su = shorten_url(u, base_domain)
        sv = shorten_url(v, base_domain)
        nodes_set.add(su)
        nodes_set.add(sv)
        links_data.append({"source": su, "target": sv})

    nodes_data = []
    for path in nodes_set:
        full_url = next((p["url"] for p in pages if p["path"] == path), "")
        score = next((p["score"] for p in pages if p["path"] == path), 0)
        title = next((p["title"] for p in pages if p["path"] == path), "")
        nodes_data.append({
            "id": path,
            "score": score,
            "title": title,
            "links_in": in_degrees.get(full_url, 0),
        })

    yield _sse("done", {
        "pages": pages,
        "stats": {
            "total_pages": graph.number_of_nodes(),
            "total_links": graph.number_of_edges(),
            "avg_links": round(graph.number_of_edges() / max(graph.number_of_nodes(), 1), 1),
            "orphan_count": len(orphans),
            "dead_end_count": len(dead_ends),
            "weak_count": len(weak),
            "alpha": alpha,
            "domain": base_domain,
        },
        "issues": {
            "orphans": orphans[:20],
            "dead_ends": dead_ends[:20],
            "weak": weak[:20],
        },
        "graph": {
            "nodes": nodes_data[:200],
            "links": links_data[:500],
        },
    })


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/analyze")
async def analyze(url: str, max_pages: int = 50, alpha: float = 0.85):
    # Validate
    if not url.startswith("http"):
        url = "https://" + url

    max_pages = min(max(max_pages, 5), 200)
    alpha = min(max(alpha, 0.1), 0.99)

    def generate():
        for event in crawl_and_analyze(url, max_pages=max_pages, alpha=alpha):
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
