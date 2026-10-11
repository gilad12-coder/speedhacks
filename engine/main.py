"""Vercel entrypoint for the search engine (the `keyhunt-engine` project, root directory `engine/`)."""
from househunt import db
from househunt.web.app import app

db.init()  # Vercel may skip ASGI lifespan; creating tables is idempotent

__all__ = ["app"]
