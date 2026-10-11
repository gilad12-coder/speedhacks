"""Shared Anthropic client setup."""

from __future__ import annotations

import os

import anthropic


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    # Keys that aren't scoped to a workspace must name one on every request.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    return anthropic.Anthropic(default_headers=headers)
