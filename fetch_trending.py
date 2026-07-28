#!/usr/bin/env python3
"""
GitHub Trending Fetcher — fetches top 5 daily trending repos,
extracts metadata + README intro, outputs JSON for the GUI.

Usage:
  python3 fetch_trending.py              # fetch + print JSON to stdout
  python3 fetch_trending.py --save       # fetch + save to data/trending.json
  python3 fetch_trending.py --summary    # also generate AI summaries (needs OPENAI_API_KEY or DEEPSEEK_KEY)
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.error
import html as html_mod
import argparse

# Ensure we can import our network module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from network import open_url, get_proxy_status

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TRENDING_JSON = os.path.join(DATA_DIR, "trending.json")
os.makedirs(DATA_DIR, exist_ok=True)

GITHUB_TRENDING_URL = "https://github.com/trending?since=daily"
GITHUB_API_REPOS = "https://api.github.com/repos"
README_HEADERS = {"User-Agent": "gh-trending/1.0", "Accept": "application/vnd.github.v3.raw"}


def _clean_html(text):
    """Strip HTML tags and decode entities."""
    text = re.sub(r'<[^>]+>', '', text)
    text = html_mod.unescape(text)
    return text.strip()


def _parse_number(s):
    """Parse '2,346' → 2346."""
    return int(s.replace(",", "")) if s else 0


def scrape_trending():
    """Scrape GitHub Trending daily page. Returns list of repo dicts."""
    status, body = open_url(GITHUB_TRENDING_URL)
    if status != 200:
        raise Exception(f"GitHub Trending 返回 HTTP {status}")

    html = body.decode("utf-8", errors="replace")
    articles = re.findall(
        r'<article[^>]*class="Box-row"[^>]*>(.*?)</article>', html, re.DOTALL
    )

    repos = []
    for art in articles:
        # Extract full repo path: /owner/repo
        hrefs = re.findall(r'href="(/[^"]+)"', art)
        repo_path = None
        for h in hrefs:
            if (
                h.startswith("/")
                and h.count("/") >= 2
                and not h.startswith("/trending")
                and not h.startswith("/login")
                and not h.startswith("/explore")
            ):
                repo_path = h.strip("/")
                break
        if not repo_path:
            continue

        # Description in <p class="col-9 ...">
        desc_m = re.search(
            r'<p\s+class="col-9[^"]*">\s*(.*?)\s*</p>', art, re.DOTALL
        )
        description = _clean_html(desc_m.group(1)) if desc_m else ""

        # Stars gained today
        stars_today_m = re.findall(r'(\d[\d,]*)\s*stars?\s*today', art)
        stars_today = _parse_number(stars_today_m[0]) if stars_today_m else 0

        # Forks
        forks_m = re.findall(r'(\d[\d,]*)\s*forks', art)
        forks = _parse_number(forks_m[0]) if forks_m else 0

        # Language
        lang_m = re.search(r'itemprop="programmingLanguage"[^>]*>\s*([^<\s]+)', art)
        language = lang_m.group(1).strip() if lang_m else None

        # Contributors
        builders = re.findall(r'alt="@(\w+)"', art)

        repos.append(
            {
                "full_name": repo_path,
                "description": description.strip(),
                "language": language,
                "stars_today": stars_today,
                "forks": forks,
                "contributors": builders[:5],
                "url": f"https://github.com/{repo_path}",
            }
        )

    return repos


def enrich_repo(repo):
    """Fetch extra metadata via GitHub API: total stars, topics, README intro."""
    owner, name = repo["full_name"].split("/")

    # Fetch repo metadata
    api_url = f"{GITHUB_API_REPOS}/{repo['full_name']}"
    try:
        status, body = open_url(api_url)
        if status == 200:
            meta = json.loads(body)
            repo["total_stars"] = meta.get("stargazers_count", 0)
            repo["open_issues"] = meta.get("open_issues_count", 0)
            repo["topics"] = meta.get("topics", [])
            repo["created_at"] = meta.get("created_at", "")
            repo["updated_at"] = meta.get("updated_at", "")
            repo["license"] = (
                meta.get("license", {}).get("spdx_id") if meta.get("license") else None
            )
    except Exception:
        repo["total_stars"] = 0
        repo["topics"] = []

    # Fetch README intro (first 800 chars)
    readme_url = f"{api_url}/readme"
    try:
        status, body = open_url(readme_url)
        if status == 200:
            readme_data = json.loads(body)
            # Use GitHub's raw content
            raw_url = f"https://raw.githubusercontent.com/{repo['full_name']}/master/README.md"
            # Try the download URL from the API response
            if "download_url" in readme_data:
                s, raw_body = open_url(readme_data["download_url"])
                if s == 200:
                    text = raw_body.decode("utf-8", errors="replace")
                    repo["readme_intro"] = text[:800]
    except Exception:
        repo["readme_intro"] = ""

    return repo


def fetch_trending(top_n=5, enrich=True):
    """Main entry: scrape trending + enrich with API data."""
    print(f"[fetch_trending] 检查代理...", file=sys.stderr)
    proxy_status = get_proxy_status()
    print(f"[fetch_trending] {proxy_status['message']}", file=sys.stderr)

    if not proxy_status["ok"]:
        raise Exception(proxy_status["message"])

    print(f"[fetch_trending] 抓取 GitHub Trending ...", file=sys.stderr)
    repos = scrape_trending()
    print(f"[fetch_trending] 获取到 {len(repos)} 个仓库", file=sys.stderr)

    if enrich:
        for i, repo in enumerate(repos[:top_n]):
            print(
                f"[fetch_trending] 补充信息 ({i+1}/{top_n}): {repo['full_name']} ...",
                file=sys.stderr,
            )
            enrich_repo(repo)

    result = {
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fetched_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "date": time.strftime("%Y-%m-%d"),
        "proxy": proxy_status["description"],
        "repos": repos[:top_n],
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="GitHub Trending Fetcher")
    parser.add_argument("--save", action="store_true", help="Save to data/trending.json")
    parser.add_argument("--no-enrich", action="store_true", help="Skip API enrichment")
    parser.add_argument("--top", type=int, default=5, help="Number of repos (default: 5)")
    args = parser.parse_args()

    try:
        data = fetch_trending(top_n=args.top, enrich=not args.no_enrich)

        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        if args.save:
            with open(TRENDING_JSON, "w") as f:
                f.write(json_str)
            print(f"Saved to {TRENDING_JSON}", file=sys.stderr)

        print(json_str)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
