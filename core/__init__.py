# 雷霆捕获引擎

"""Thunder Capture Engine — multi-platform social media automation."""

import sys
import io
import os


def setup_windows_unicode():
    """Ensure stdout/stderr use UTF-8 on Windows.

    Call once at startup. Idempotent — safe to call multiple times.
    """
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")  # type: ignore[arg-type]
    if hasattr(sys.stderr, "buffer") and not isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")  # type: ignore[arg-type]
