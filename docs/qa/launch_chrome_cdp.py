import os
import sys
import time
import socket
import subprocess
from pathlib import Path
from core.browser_orchestrator import find_chrome_path

# Use a dedicated, persistent Chrome profile for the CDP connection.
USER_DATA_DIR = Path("data/chrome_cdp_profile")
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
CDP_PORT = 61850


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    chrome_path = find_chrome_path()
    if not chrome_path:
        print("ERROR: Chrome/Edge not found.")
        sys.exit(1)

    # Check if a CDP browser is already running on the target port.
    if is_port_open(CDP_PORT):
        print(f"CDP browser already running on port {CDP_PORT}")
        sys.exit(0)

    # Launch a headful Chrome with strong anti-detection flags and a stable
    # user-data-dir so that Douyin login state can be persisted.
    cmd = [
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={os.path.abspath(USER_DATA_DIR)}",
        "--no-first-run",
        "--no-default-browser-check",
        # Use a real-looking window size to avoid headless fingerprinting.
        "--window-size=1920,1080",
        "--start-maximized",
        # Anti-detection flags
        "--disable-blink-features=AutomationControlled",
        "--exclude-switches=enable-automation",
        "--disable-infobars",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-features=IsolateOrigins,site-per-process",
        # Use a current, stable Chrome user agent. Update the version if needed.
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        # Optionally set a common locale/timezone to avoid locale leaks.
        "--lang=zh-CN",
        # Do not use headless=new: the goal is a real browser instance that
        # can be logged into manually before unattended crawling.
        "https://www.douyin.com/",
    ]

    print(f"Launching Chrome CDP on port {CDP_PORT} ...")
    print(f"Profile: {os.path.abspath(USER_DATA_DIR)}")
    print("Please log in to Douyin manually if this is the first run.")

    process = subprocess.Popen(cmd)

    # Wait for CDP port to be available.
    deadline = time.time() + 30
    while time.time() < deadline:
        if is_port_open(CDP_PORT):
            print(f"OK: Chrome CDP ready on port {CDP_PORT}")
            try:
                process.wait()
            except KeyboardInterrupt:
                print("\nShutting down Chrome CDP...")
                process.terminate()
            return
        time.sleep(0.5)

    print("ERROR: Chrome CDP did not become ready within 30s.")
    process.terminate()
    sys.exit(1)


if __name__ == "__main__":
    main()
