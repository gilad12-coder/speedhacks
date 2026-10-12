import os
import uuid

import pytest


@pytest.fixture(autouse=True)
def database(monkeypatch):
    """SQLite by default; set TEST_DATABASE_URL to run every test against Postgres instead."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        yield
        return
    import psycopg
    schema = f"test_{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("HOUSEHUNT_DB_SCHEMA", schema)
    yield
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
