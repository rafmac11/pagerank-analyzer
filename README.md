# ⬡ PageRank Analyzer

A web app that crawls any website, calculates PageRank for every page, and shows you what to fix — with a live network graph visualization.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Live crawling** with real-time progress via Server-Sent Events
- **PageRank calculation** using NetworkX (same algorithm Google invented)
- **Issue detection**: orphan pages, dead-end pages, low-authority pages
- **Interactive network graph** built with D3.js (drag, hover, zoom)
- **Sortable results table** with visual score bars
- **One-click deploy** to Railway

## Run Locally

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/pagerank-analyzer.git
cd pagerank-analyzer

# Install dependencies
pip install -r requirements.txt

# Start the server
python app.py
```

Open **http://localhost:8000** in your browser.

## Deploy to Railway

### Option 1: One-click (fastest)

1. Push this repo to your GitHub account
2. Go to [railway.app](https://railway.app)
3. Click **"New Project"** → **"Deploy from GitHub Repo"**
4. Select your repo
5. Railway auto-detects the config and deploys — done!

Your app will be live at `https://your-app-name.up.railway.app`

### Option 2: Railway CLI

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize and deploy
railway init
railway up
```

## How It Works

1. **You enter a URL** — the app starts crawling from that page
2. **It follows internal links** — building a directed graph of your site's link structure
3. **It runs PageRank** — the same algorithm Google uses to rank pages, computing an importance score for every page
4. **It flags problems** — orphan pages (nothing links to them), dead-ends (they link to nothing), and low-authority pages
5. **It visualizes the network** — an interactive D3.js force graph where node size = PageRank score

## Tech Stack

| Layer     | Tech                          |
|-----------|-------------------------------|
| Backend   | Python, FastAPI, NetworkX     |
| Crawler   | Requests, BeautifulSoup       |
| Frontend  | Vanilla JS, D3.js, CSS        |
| Streaming | Server-Sent Events (SSE)      |
| Deploy    | Railway (Nixpacks)            |

## Configuration

| Parameter   | Default | Description                                   |
|-------------|---------|-----------------------------------------------|
| Max pages   | 50      | Maximum number of pages to crawl (5–200)      |
| α (alpha)   | 0.85    | Damping factor — probability of following a link vs jumping randomly |

## License

MIT
