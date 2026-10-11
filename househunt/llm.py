"""Shared Anthropic client setup."""

from __future__ import annotations

import os

import anthropic


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    return anthropic.Anthropic()
