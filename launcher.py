#!/usr/bin/env python3
"""
GitHub Trending — Cross-Platform Launcher
Starts the server + opens the browser.

Usage:
  python3 launcher.py          # start server + open browser
  python3 launcher.py --server # server only (no browser)
"""

import subprocess
import sys
import os
import time
import webbrowser
import platform

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 19999
SERVER_SCRIPT = os.path.join(PROJECT_DIR, "server.py")


def kill_existing():
    """Kill any process on our port (cross-platform)."""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{PORT}\') do taskkill /F /PID %a',
                shell=True, capture_output=True,
            )
        elif system == "Darwin":  # macOS
            subprocess.run(
                f"lsof -ti :{PORT} | xargs kill 2>/dev/null",
                shell=True, capture_output=True,
            )
        else:  # Linux
            subprocess.run(
                f"fuser -k {PORT}/tcp 2>/dev/null",
                shell=True, capture_output=True,
            )
    except Exception:
        pass
    time.sleep(0.5)


def main():
    system = platform.system()
    print(f"🦞 GitHub Trending Desktop Launcher")
    print(f"   系统: {system} {platform.release()}")
    print(f"   项目: {PROJECT_DIR}")
    print(f"   端口: {PORT}")

    kill_existing()

    # Start server
    print(f"   启动服务器...")
    server_proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    time.sleep(1.5)

    # Open browser
    url = f"http://localhost:{PORT}"
    print(f"   打开浏览器: {url}")
    webbrowser.open(url)

    print(f"   ✅ 已启动！按 Ctrl+C 停止服务器")
    print(f"   🌐 浏览器访问: {url}")

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        print("\n   停止服务器...")
        server_proc.terminate()
        server_proc.wait()
        print("   👋 再见！")


if __name__ == "__main__":
    main()
