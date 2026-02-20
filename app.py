"""
PageRank Analyzer — Backend
FastAPI server with background crawling and polling for progress
"""

import json
import threading
import time
import uuid
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import networkx as nx
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="PageRank Analyzer")
templates = Jinja2Templates(directory="templates")

# Store running/completed jobs
jobs = {}


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


# ── Background Crawl + PageRank ──────────────────────────────────────────────

def run_crawl(job_id, start_url, max_pages, alpha):
    """Runs in a background thread. Updates jobs[job_id] as it progresses."""
    job = jobs[job_id]

    try:
        _do_crawl(job, start_url, max_pages, alpha)
    except Exception as e:
        job["status"] = "error"
        job["message"] = f"Analysis failed: {str(e)}"


def _do_crawl(job, start_url, max_pages, alpha):
    """Actual crawl logic, separated so errors are caught."""
    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc

    visited = set()
    to_visit = [start_url]
    graph = nx.DiGraph()
    page_titles = {}
    page_status = {}

    headers = {"User-Agent": "PageRank-Analyzer/1.0 (Educational Tool)"}
    session = requests.Session()
    session.headers.update(headers)

    job["status"] = "crawling"
    job["message"] = f"Starting crawl of {base_domain}..."

    while to_visit and len(visited) < max_pages:
        url = normalize_url(to_visit.pop(0))

        if url in visited:
            continue

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

            # Update progress
            job["crawled"] = len(visited)
            job["current_url"] = shorten_url(url, base_domain)
            job["current_title"] = page_titles.get(url, "")
            job["links_found"] = links_found
            job["queued"] = len(to_visit)

            time.sleep(0.15)

        except requests.RequestException:
            continue

    # ── Analysis phase ───────────────────────────────────────────────────
    job["status"] = "analyzing"
    job["message"] = "Calculating PageRank..."

    if graph.number_of_nodes() == 0:
        job["status"] = "error"
        job["message"] = "No pages found. Check the URL and try again."
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

    # Build graph data for visualization
    page_lookup = {p["path"]: p for p in pages}
    nodes_set = set()
    links_data = []
    for u, v in list(graph.edges())[:500]:
        su = shorten_url(u, base_domain)
        sv = shorten_url(v, base_domain)
        nodes_set.add(su)
        nodes_set.add(sv)
        links_data.append({"source": su, "target": sv})

    nodes_data = []
    for path in list(nodes_set)[:200]:
        p = page_lookup.get(path, {})
        nodes_data.append({
            "id": path,
            "score": p.get("score", 0),
            "title": p.get("title", ""),
            "links_in": p.get("links_in", 0),
        })

    job["status"] = "done"
    job["result"] = {
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
            "nodes": nodes_data,
            "links": links_data,
        },
    }


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/start")
async def start_analysis(url: str, max_pages: int = 50, alpha: float = 0.85):
    """Start a crawl job in the background, return job_id immediately."""
    if not url.startswith("http"):
        url = "https://" + url

    max_pages = min(max(max_pages, 5), 200)
    alpha = min(max(alpha, 0.1), 0.99)

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "starting",
        "message": "Initializing...",
        "crawled": 0,
        "max_pages": max_pages,
        "current_url": "",
        "current_title": "",
        "links_found": 0,
        "queued": 0,
        "result": None,
    }

    thread = threading.Thread(target=run_crawl, args=(job_id, url, max_pages, alpha), daemon=True)
    thread.start()

    return JSONResponse({"job_id": job_id})


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Poll this endpoint for progress updates."""
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    return JSONResponse({
        "status": job["status"],
        "message": job.get("message", ""),
        "crawled": job["crawled"],
        "max_pages": job["max_pages"],
        "current_url": job["current_url"],
        "current_title": job.get("current_title", ""),
        "links_found": job["links_found"],
        "queued": job["queued"],
    })


@app.get("/api/result/{job_id}")
async def get_result(job_id: str):
    """Get the final results once the job is done."""
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    if job["status"] == "error":
        return JSONResponse({"error": job["message"]})

    if job["status"] != "done":
        return JSONResponse({"error": "Job not finished yet"}, status_code=202)

    return JSONResponse(job["result"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
