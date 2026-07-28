"""
Proxy-adaptive network layer for GitHub access.
Generic detection — no vendor-specific hardcoding.

Priority order:
1. GH_TRENDING_PROXY env var (user-configured)
2. System env vars (http_proxy, https_proxy, ALL_PROXY)
3. Auto-scan common local proxy ports
4. Direct connection (last resort)

Caches the working config to data/proxy_config.json.
"""
import urllib.request
import urllib.error
import json
import os
import time

# Optional GitHub token for higher API rate limit (5000 req/hr vs 60)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ─── Proxy candidates (auto-scan) ─────────────────────────

# Common local proxy ports — tried in order when no env var is set.
# Each port is probed as both http:// and socks5h://
_COMMON_PROXY_PORTS = [
    10887,   # privoxy (common in trojan chains)
    10886,   # trojan SOCKS5
    7890,    # Clash / ClashX HTTP
    10808,   # v2ray / xray HTTP
    1080,    # generic SOCKS5
    8118,    # privoxy default
    8080,    # generic HTTP proxy
    8001,    # some VPNs
    7891,    # Clash SOCKS5
]

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "proxy_config.json"
)
TEST_URL = "https://api.github.com"
TEST_TIMEOUT = 8


# ─── Build candidate list ──────────────────────────────────

def _build_candidates():
    """Build proxy candidate list dynamically — no hardcoded brands."""
    candidates = []

    # 1. Explicit user config via env var
    custom = os.environ.get("GH_TRENDING_PROXY", "")
    if custom:
        candidates.append({
            "http": custom, "https": custom,
            "description": f"GH_TRENDING_PROXY ({custom})"
        })

    # 2. System env vars
    http_proxy = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or ""
    https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    all_proxy = os.environ.get("all_proxy") or os.environ.get("ALL_PROXY") or ""

    if all_proxy:
        candidates.append({
            "http": all_proxy, "https": all_proxy,
            "description": f"ALL_PROXY ({all_proxy})"
        })
    if http_proxy or https_proxy:
        candidates.append({
            "http": http_proxy, "https": https_proxy or http_proxy,
            "description": f"env http_proxy ({http_proxy or https_proxy})"
        })

    # 3. Auto-scan common ports
    for port in _COMMON_PROXY_PORTS:
        addr = f"127.0.0.1:{port}"
        candidates.append({
            "http": f"http://{addr}", "https": f"http://{addr}",
            "description": f"HTTP Proxy {addr}"
        })
        # Also try SOCKS5 variant for SOCKS-capable ports
        if port in (10886, 1080, 10808, 7891):
            candidates.append({
                "http": f"socks5h://{addr}", "https": f"socks5h://{addr}",
                "description": f"SOCKS5 Proxy {addr}"
            })

    # 4. Direct (last resort)
    candidates.append({"http": "", "https": "", "description": "直连 (Direct)"})

    return candidates


# ─── Proxy testing ─────────────────────────────────────────

def _test_proxy(proxy_dict):
    """Test if a proxy configuration can reach GitHub API. Returns (ok, latency_ms).
    Any HTTP response (even error codes) counts as success — the proxy works.
    Only connection-level errors count as failure."""
    start = time.time()
    try:
        ctx = urllib.request.Request(TEST_URL, headers={"User-Agent": "gh-trending/1.0"})
        if proxy_dict.get("http") and proxy_dict["http"]:
            clean = {k: v for k, v in proxy_dict.items() if k in ("http", "https")}
            proxy_handler = urllib.request.ProxyHandler(clean)
            opener = urllib.request.build_opener(proxy_handler)
            resp = opener.open(ctx, timeout=TEST_TIMEOUT)
        else:
            resp = urllib.request.urlopen(ctx, timeout=TEST_TIMEOUT)
        resp.read()
        latency = (time.time() - start) * 1000
        return True, latency
    except urllib.error.HTTPError:
        # HTTP error (403, 404, 429, etc.) still means proxy works!
        latency = (time.time() - start) * 1000
        return True, latency
    except Exception:
        return False, 0


def detect_proxy():
    """Scan all candidates and return the first working proxy + latency."""
    for candidate in _build_candidates():
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
            ok, _ = _test_proxy(proxy)
            if ok:
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
        desc = result["proxy"].get("description", "unknown")
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
            "message": "❌ 无法连接 GitHub，请检查代理/VPN 是否开启"
        }


if __name__ == "__main__":
    status = get_proxy_status()
    print(status["message"])
