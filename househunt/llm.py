"""Shared Anthropic client setup."""

from __future__ import annotations

import os

import anthropic

# Server-side fallbacks are Anthropic-direct only; OpenRouter rejects the parameter.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


def has_credentials() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    if key := os.environ.get("OPENROUTER_API_KEY"):
        return anthropic.Anthropic(base_url="https://openrouter.ai/api", auth_token=key, api_key=None)
    return anthropic.Anthropic()
