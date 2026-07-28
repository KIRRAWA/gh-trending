#!/usr/bin/env python3
"""
GitHub Trending Desktop Server
- Serves the web UI at localhost:19999
- REST API for trending data, README, downloads
- Auto-opens browser on start
"""

import http.server
import json
import os
import sys
import re
import subprocess
import threading
import time
import shutil
import webbrowser
import urllib.parse
from pathlib import Path

# Project root
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
REPOS_DIR = os.path.join(ROOT, "repos")
STATIC_DIR = os.path.join(ROOT, "static")
TRENDING_JSON = os.path.join(DATA_DIR, "trending.json")
DOWNLOADS_JSON = os.path.join(DATA_DIR, "downloads.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPOS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# In-memory download job tracker
# { job_id: { repo, status, progress%, started_at, ... } }
download_jobs = {}
job_lock = threading.Lock()

# Ensure network module is importable
sys.path.insert(0, ROOT)


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_latest_trending():
    """Load the latest trending.json."""
    return load_json(TRENDING_JSON)


def get_downloads():
    """Load download state."""
    return load_json(DOWNLOADS_JSON, {"repos": []})


def save_downloads(data):
    save_json(DOWNLOADS_JSON, data)


# ─── Git Clone with Progress ───────────────────────────────────────────


def _run_clone(job_id, repo_url, repo_name):
    """Background thread: git clone with progress parsing."""
    target_dir = os.path.join(REPOS_DIR, repo_name)

    with job_lock:
        download_jobs[job_id]["status"] = "cloning"

    try:
        # Use git clone with progress on stderr
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"

        proc = subprocess.Popen(
            ["git", "clone", "--progress", repo_url, target_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )

        # Parse stderr for progress
        progress_pattern = re.compile(
            r"Receiving objects:\s+(\d+)%|"
            r"Resolving deltas:\s+(\d+)%|"
            r"Checking out files:\s+(\d+)%"
        )

        last_update = time.time()
        for line in proc.stderr:
            m = progress_pattern.search(line)
            if m:
                pct = int(m.group(1) or m.group(2) or m.group(3))
                # Map git phases to overall progress
                if "Receiving objects" in line:
                    overall = int(pct * 0.7)
                elif "Resolving deltas" in line:
                    overall = int(70 + pct * 0.2)
                elif "Checking out files" in line:
                    overall = int(90 + pct * 0.1)
                else:
                    overall = pct

                now = time.time()
                if now - last_update > 0.5 or overall >= 100:
                    with job_lock:
                        download_jobs[job_id]["progress"] = min(overall, 99)
                    last_update = now

        proc.wait()

        if proc.returncode == 0:
            with job_lock:
                download_jobs[job_id]["status"] = "done"
                download_jobs[job_id]["progress"] = 100
                download_jobs[job_id]["path"] = target_dir

            # Record in downloads registry
            dl = get_downloads()
            dl["repos"].append(
                {
                    "name": repo_name,
                    "url": repo_url,
                    "path": target_dir,
                    "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "size_mb": _get_dir_size_mb(target_dir),
                }
            )
            save_downloads(dl)
        else:
            with job_lock:
                download_jobs[job_id]["status"] = "error"
                download_jobs[job_id]["error"] = f"git clone 返回码 {proc.returncode}"

    except Exception as e:
        with job_lock:
            download_jobs[job_id]["status"] = "error"
            download_jobs[job_id]["error"] = str(e)


def _get_dir_size_mb(path):
    """Get directory size in MB."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return round(total / (1024 * 1024), 2)


# ─── HTTP Request Handler ──────────────────────────────────────────────


class TrendingHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, format, *args):
        # Quieter logging
        sys.stderr.write(f"[server] {args[0]}\n")

    def _json_response(self, data, status=200):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg, status=400):
        self._json_response({"error": msg}, status)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ─── API Routing ────────────────────────────────────────────────

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/trending":
            data = get_latest_trending()
            if data:
                # Compute freshness (minutes since last fetch)
                try:
                    fetched_ts = time.strptime(data["fetched_at"], "%Y-%m-%d %H:%M:%S")
                    fetched_epoch = time.mktime(fetched_ts)
                    age_minutes = (time.time() - fetched_epoch) / 60
                    data["age_minutes"] = round(age_minutes, 1)
                    data["is_stale"] = age_minutes > 60  # stale if >1 hour
                except (KeyError, ValueError):
                    data["age_minutes"] = None
                    data["is_stale"] = True
                self._json_response(data)
            else:
                self._json_response(
                    {
                        "fetched_at": "never",
                        "repos": [],
                        "age_minutes": None,
                        "is_stale": True,
                        "message": "尚未获取数据，请先运行 fetch_trending.py --save",
                    }
                )

        elif path == "/api/proxy-status":
            from network import get_proxy_status

            self._json_response(get_proxy_status())

        elif path == "/api/freshness":
            data = get_latest_trending()
            if data and "fetched_at" in data:
                try:
                    fetched_ts = time.strptime(data["fetched_at"], "%Y-%m-%d %H:%M:%S")
                    fetched_epoch = time.mktime(fetched_ts)
                    age_minutes = (time.time() - fetched_epoch) / 60
                    self._json_response({
                        "fetched_at": data["fetched_at"],
                        "age_minutes": round(age_minutes, 1),
                        "is_stale": age_minutes > 60,
                        "repo_count": len(data.get("repos", [])),
                    })
                except (KeyError, ValueError):
                    self._json_response({"fetched_at": None, "age_minutes": None, "is_stale": True, "repo_count": 0})
            else:
                self._json_response({"fetched_at": None, "age_minutes": None, "is_stale": True, "repo_count": 0})

        elif path == "/api/search":
            # GET /api/search?q=QUERY&sort=stars&page=1&per_page=10
            query = qs.get("q", [""])[0]
            sort = qs.get("sort", ["stars"])[0]
            page = int(qs.get("page", ["1"])[0])
            per_page = min(int(qs.get("per_page", ["10"])[0]), 30)
            if not query:
                self._error("Missing 'q' parameter")
            else:
                self._search_github(query, sort, page, per_page)

        elif path.startswith("/api/readme/"):
            # GET /api/readme/:owner/:repo
            parts = path.split("/")
            if len(parts) >= 5:
                owner, repo = parts[3], parts[4]
                self._serve_readme(owner, repo)
            else:
                self._error("Invalid path: /api/readme/:owner/:repo")

        elif path.startswith("/api/download/"):
            parts = path.split("/")
            if len(parts) >= 4:
                job_id = parts[3]
                if "/status" in path:
                    with job_lock:
                        job = download_jobs.get(job_id)
                    if job:
                        self._json_response(job)
                    else:
                        self._error("Job not found", 404)
                else:
                    self._error("Unknown download endpoint")
            else:
                self._error("Invalid path")

        elif path == "/api/downloads":
            dl = get_downloads()
            self._json_response(dl)

        elif path == "/api/fetch":
            # Trigger a fresh fetch (runs fetch_trending.py --save)
            self._trigger_fetch()

        elif path == "/" or path == "":
            # Serve index.html
            self.path = "/static/index.html"
            super().do_GET()

        elif path.startswith("/static/") or path == "/static":
            # Serve static files
            super().do_GET()

        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/download":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._error("Invalid JSON")
                return

            repo_url = data.get("url", "")
            repo_name = data.get("name", "")

            if not repo_url or not repo_name:
                self._error("Missing 'url' or 'name'")
                return

            job_id = f"{repo_name}-{int(time.time())}"
            with job_lock:
                download_jobs[job_id] = {
                    "id": job_id,
                    "repo": repo_name,
                    "url": repo_url,
                    "status": "starting",
                    "progress": 0,
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

            t = threading.Thread(
                target=_run_clone, args=(job_id, repo_url, repo_name), daemon=True
            )
            t.start()

            self._json_response({"job_id": job_id, "status": "started"}, 202)

        elif path == "/api/open-path":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else b"{}"
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._error("Invalid JSON")
                return
            target = data.get("path", "")
            if target and os.path.exists(target):
                subprocess.Popen(["open", target])
                self._json_response({"opened": target})
            else:
                self._error(f"Path not found: {target}", 404)

        else:
            self._error("Not found", 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/downloads/"):
            parts = path.split("/")
            if len(parts) >= 4:
                repo_name = parts[3]
                target_dir = os.path.join(REPOS_DIR, repo_name)
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)
                dl = get_downloads()
                dl["repos"] = [r for r in dl["repos"] if r.get("name") != repo_name]
                save_downloads(dl)
                self._json_response({"deleted": repo_name})
            else:
                self._error("Invalid path")
        else:
            self._error("Not found", 404)

    # ─── Helpers ────────────────────────────────────────────────────

    # ─── Search ────────────────────────────────────────────────────

    def _search_github(self, query, sort, page, per_page):
        """Call GitHub Search API and return cleaned results."""
        from network import open_url
        from urllib.parse import quote

        api_url = (
            f"https://api.github.com/search/repositories"
            f"?q={quote(query)}&sort={sort}&order=desc"
            f"&page={page}&per_page={per_page}"
        )
        try:
            status, body = open_url(api_url)
            if status == 200:
                raw = json.loads(body)
                repos = []
                for item in raw.get("items", []):
                    repos.append({
                        "full_name": item.get("full_name", ""),
                        "description": (item.get("description") or "")[:200],
                        "language": item.get("language"),
                        "total_stars": item.get("stargazers_count", 0),
                        "forks": item.get("forks_count", 0),
                        "topics": item.get("topics", [])[:5],
                        "license": (item.get("license", {}) or {}).get("spdx_id"),
                        "url": item.get("html_url", ""),
                        "created_at": item.get("created_at", ""),
                        "updated_at": item.get("updated_at", ""),
                    })
                self._json_response({
                    "total_count": raw.get("total_count", 0),
                    "page": page,
                    "per_page": per_page,
                    "query": query,
                    "repos": repos,
                })
            else:
                self._error(f"GitHub API 返回 {status}", 502)
        except Exception as e:
            self._error(str(e), 500)

    # ─── README ────────────────────────────────────────────────────

    def _serve_readme(self, owner, repo):
        """Fetch README from GitHub API and return it."""
        from network import open_url

        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            status, body = open_url(api_url)
            if status == 200:
                data = json.loads(body)
                download_url = data.get("download_url", "")
                if download_url:
                    s, raw_body = open_url(download_url)
                    if s == 200:
                        text = raw_body.decode("utf-8", errors="replace")
                        self._json_response(
                            {
                                "owner": owner,
                                "repo": repo,
                                "readme": text,
                                "encoding": data.get("encoding", "utf-8"),
                            }
                        )
                        return
            self._error("README not found", 404)
        except Exception as e:
            self._error(str(e), 500)

    def _trigger_fetch(self):
        """Run fetch_trending.py --save in background."""
        import subprocess

        script = os.path.join(ROOT, "fetch_trending.py")

        def run():
            try:
                subprocess.run(
                    [sys.executable, script, "--save"],
                    cwd=ROOT,
                    capture_output=True,
                    timeout=60,
                )
            except Exception as e:
                print(f"Fetch error: {e}", file=sys.stderr)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._json_response({"status": "fetching"})


# ─── Main ───────────────────────────────────────────────────────────────


def main():
    port = 19999

    print(f"🦞 GitHub Trending Desktop")
    print(f"   Root: {ROOT}")
    print(f"   Server: http://localhost:{port}")
    print(f"   Press Ctrl+C to stop")

    server = http.server.HTTPServer(("127.0.0.1", port), TrendingHandler)

    # Open browser after a short delay
    def open_browser():
        time.sleep(0.8)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
