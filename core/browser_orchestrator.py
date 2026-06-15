import os
import time
import socket
import subprocess
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def find_chrome_path() -> Optional[str]:
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

class ShadowBrowser:
    def __init__(self, user_data_dir: str):
        self.port = find_free_port()
        self.user_data_dir = user_data_dir
        self.process: Optional[subprocess.Popen] = None
        self.chrome_path = find_chrome_path()

    def start(self):
        if not self.chrome_path:
            raise RuntimeError("Cannot find Chrome or Edge installation on this system.")
        
        # Ensure user data dir exists
        os.makedirs(self.user_data_dir, exist_ok=True)

        cmd = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={os.path.abspath(self.user_data_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,720",
        ]
        
        logger.info(f"Starting ShadowBrowser on port {self.port} at {self.user_data_dir}")
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        
        # Wait for port to be available
        start_time = time.time()
        while time.time() - start_time < 10:
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=1):
                    logger.info(f"ShadowBrowser is ready on port {self.port}")
                    return
            except OSError:
                time.sleep(0.5)
                
        raise RuntimeError("Timeout waiting for ShadowBrowser debugging port.")

    def close(self):
        if self.process:
            logger.info("Closing ShadowBrowser...")
            try:
                import subprocess
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                logger.error(f"Failed to kill ShadowBrowser tree: {e}")
                self.process.terminate()
            
            self.process = None
            logger.info("ShadowBrowser closed.")
