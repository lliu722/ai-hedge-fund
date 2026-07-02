"""
Shared LLM factory for the Equity L/S desk.

One place for model choice, timeout, and retry policy — A2 and B5 both use this.
"""
from __future__ import annotations

import os

from langchain_deepseek import ChatDeepSeek


def get_llm(temperature: float = 0.2, timeout: int = 90) -> ChatDeepSeek:
    """DeepSeek chat client with a request timeout and retries, so a single
    slow call can never hang a pipeline run indefinitely."""
    return ChatDeepSeek(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        temperature=temperature,
        timeout=timeout,
        max_retries=2,
    )
