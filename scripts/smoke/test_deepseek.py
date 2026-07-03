"""Smoke-test DeepSeek-compatible chat completion configuration.

Requires THUNDER_DEEPSEEK_KEY in the environment. This script intentionally
does not contain API keys.
"""

from __future__ import annotations

import os
import sys

from openai import OpenAI


def main() -> int:
    api_key = os.getenv("THUNDER_DEEPSEEK_KEY", "").strip()
    if not api_key:
        print("SKIP: THUNDER_DEEPSEEK_KEY is not set")
        return 0

    client = OpenAI(base_url="https://api.deepseek.com", api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=os.getenv("THUNDER_DEEPSEEK_MODEL", "deepseek-v4-flash"),
            messages=[{"role": "user", "content": "Reply with OK only."}],
            max_tokens=8,
            temperature=0,
        )
    except Exception as exc:
        print("FAILED:", exc)
        return 1

    content = (response.choices[0].message.content or "").strip()
    print("SUCCESS:", content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
