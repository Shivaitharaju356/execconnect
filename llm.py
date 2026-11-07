"""Optional LLM access. The app works fully without a key (rule-based + TF-IDF fallbacks).

Set ONE of these environment variables to switch AI features on:
  OPENAI_API_KEY      (model via OPENAI_MODEL, default gpt-4o-mini; embeddings via text-embedding-3-small)
  ANTHROPIC_API_KEY   (model via ANTHROPIC_MODEL, default claude-haiku-4-5)
"""
import os

import requests

TIMEOUT = 15


def enabled():
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def complete(prompt, max_tokens=300):
    """Returns the model's text reply, or None if no key / on any error (callers fall back)."""
    try:
        if os.environ.get("OPENAI_API_KEY"):
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                json={"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "max_tokens": max_tokens,
                      "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]},
                timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        if os.environ.get("ANTHROPIC_API_KEY"):
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"), "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()["content"][0]["text"]
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None
    return None


def embed(texts):
    """Dense embeddings via OpenAI if available; otherwise None (matching falls back to TF-IDF)."""
    if not os.environ.get("OPENAI_API_KEY") or not texts:
        return None
    try:
        r = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            json={"model": os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small"), "input": texts},
            timeout=30)
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]
    except (requests.RequestException, KeyError, ValueError):
        return None
