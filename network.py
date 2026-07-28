"""
Proxy-adaptive network layer for GitHub access behind GFW.
Auto-detects available proxies: WestWorld VPN (trojan + privoxy),
legacy Clash, or direct connection. Caches the working config.
"""
import urllib.request
import urllib.error
import subprocess
import json
import os
import time
import socket

# Optional GitHub token for higher API rate limit (5000 req/hr vs 60)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

PROXY_CANDIDATES = [
    # WestWorld VPN chain: privoxy (HTTP) → trojan (SOCKS5)
    {"http": "http://127.0.0.1:10887", "https": "http://127.0.0.1:10887",
     "description": "西部世界 Privoxy → Trojan"},
    # WestWorld SOCKS5 direct
    {"http": "socks5h://127.0.0.1:10886", "https": "socks5h://127.0.0.1:10886",
     "description": "西部世界 Trojan SOCKS5"},
    # Legacy Clash
    {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890",
     "description": "Clash HTTP"},
    # No proxy (last resort)
    {"http": "", "https": "", "description": "直连"},
]

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "proxy_config.json")
TEST_URL = "https://api.github.com"
TEST_TIMEOUT = 8


def _test_proxy(proxy_dict):
    """Test if a proxy configuration can reach GitHub API. Returns (ok, latency_ms).
    Any HTTP response (even error codes) counts as success — the proxy works.
    Only connection-level errors count as failure."""
    start = time.time()
    try:
        ctx = urllib.request.Request(TEST_URL, headers={"User-Agent": "gh-trending/1.0"})
        if proxy_dict.get("http") and proxy_dict["http"]:
            # Use proxy (strip description key before passing to ProxyHandler)
            clean = {k: v for k, v in proxy_dict.items() if k in ("http", "https")}
            proxy_handler = urllib.request.ProxyHandler(clean)
            opener = urllib.request.build_opener(proxy_handler)
            resp = opener.open(ctx, timeout=TEST_TIMEOUT)
        else:
            resp = urllib.request.urlopen(ctx, timeout=TEST_TIMEOUT)
        # Read response — any HTTP response means GitHub is reachable
        resp.read()
        latency = (time.time() - start) * 1000
        return True, latency
    except urllib.error.HTTPError as e:
        # HTTP error (403, 404, 429, etc.) still means proxy works!
        latency = (time.time() - start) * 1000
        return True, latency
    except Exception:
        return False, 0


def detect_proxy():
    """Scan all candidates and return the first working proxy + latency."""
    for candidate in PROXY_CANDIDATES:
        ok, latency = _test_proxy(candidate)
        if ok:
            return {
                "proxy": candidate,
                "latency_ms": round(latency, 1),
                "detected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
    return None


def get_proxy():
    """
    Get a working proxy. Uses cached config if still valid, otherwise re-detects.
    Returns a dict suitable for urllib.request.ProxyHandler, or None for direct.
    """
    # Try cached config first
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cached = json.load(f)
            proxy = cached.get("proxy", {})
            # Quick test: is this proxy still alive?
            ok, _ = _test_proxy(proxy)
            if ok:
                # Only return the proxy dict, strip metadata
                return {k: v for k, v in proxy.items()
                        if k in ("http", "https") and v}
        except (json.JSONDecodeError, KeyError):
            pass

    # Re-detect
    result = detect_proxy()
    if result:
        with open(CONFIG_PATH, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        proxy = result["proxy"]
        return {k: v for k, v in proxy.items()
                if k in ("http", "https") and v}
    return None


def open_url(url, timeout=15):
    """
    Open a URL using the detected proxy. Returns (status, body_bytes).
    Auto-retries once if proxy fails. Uses GITHUB_TOKEN env var if set.
    """
    proxy = get_proxy()
    headers = {
        "User-Agent": "gh-trending/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            if proxy:
                handler = urllib.request.ProxyHandler(proxy)
                opener = urllib.request.build_opener(handler)
                resp = opener.open(req, timeout=timeout)
            else:
                resp = urllib.request.urlopen(req, timeout=timeout)
            body = resp.read()
            return resp.status, body
        except Exception as e:
            if attempt == 0:
                # Clear cache and re-detect
                if os.path.exists(CONFIG_PATH):
                    os.remove(CONFIG_PATH)
                proxy = get_proxy()
            else:
                raise e
    return None, None


def get_proxy_status():
    """Return a human-readable proxy status for the GUI."""
    result = detect_proxy()
    if result:
        desc = result["proxy"].get("description", "未知")
        latency = result["latency_ms"]
        return {
            "ok": True,
            "description": desc,
            "latency_ms": latency,
            "message": f"✅ {desc} ({latency}ms)"
        }
    else:
        return {
            "ok": False,
            "description": None,
            "latency_ms": None,
            "message": "❌ 无法连接 GitHub，请检查 VPN 是否开启"
        }


if __name__ == "__main__":
    status = get_proxy_status()
    print(status["message"])
