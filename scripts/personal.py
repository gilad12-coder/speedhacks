#!/usr/bin/env python3
"""Run the persistent, loopback-only personal app: .venv/bin/python scripts/personal.py."""
from pathlib import Path
import json
import os
import secrets
import signal
import subprocess
import time
from urllib.parse import quote

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'data' / 'personal'


def save_env(path, values):
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(''.join(f'{k}={json.dumps(str(v))}\n' for k, v in values.items() if v is not None))


def setup():
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PRIVATE.chmod(0o700)
    pg_path = PRIVATE / 'postgres.env'
    if not pg_path.exists():
        # Docker env files do not unquote values.
        pg_path.touch(mode=0o600)
        pg_path.write_text('POSTGRES_USER=keyhunt\nPOSTGRES_DB=keyhunt\nPOSTGRES_PASSWORD=' + secrets.token_urlsafe(32) + '\n')
    pg = dotenv_values(pg_path)
    existing = dotenv_values(ROOT / '.env.local')
    shared = {**existing, 'DATABASE_URL': f"postgresql://keyhunt:{quote(pg['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:55432/keyhunt",
        'APP_URL': 'http://127.0.0.1:3000', 'AGENT_WORKER_URL': 'http://127.0.0.1:8788',
        'SESSION_SECRET': existing.get('SESSION_SECRET') or secrets.token_urlsafe(48),
        'AGENT_API_KEY': existing.get('AGENT_API_KEY') or secrets.token_urlsafe(48),
        'PERSONAL_MODE': '1', 'PERSONAL_ACCOUNT_ID': existing.get('PERSONAL_ACCOUNT_ID') or 'local:' + secrets.token_urlsafe(24)}
    save_env(ROOT / '.env.local', shared)
    worker = {**dotenv_values(ROOT / '.env'), **shared, 'DB_PATH': str(PRIVATE / 'agent.db'),
        'RENTER_NAME': 'Reed', 'RUN_PLATFORM_WORKER': '1', 'RUN_OUTREACH_WORKER': '1', 'INBOUND_CALLBACKS': '1',
        'CALL_MODE': 'auto', 'MOCK_SOURCES': '0', 'DIAL_CALL_VERIFIED_CONTACTS': '1', 'VOICE_MODE': 'managed'}
    save_env(PRIVATE / 'worker.env', worker)
    return {**os.environ, **{k: str(v) for k, v in shared.items() if v is not None}}, {**os.environ, **{k: str(v) for k, v in worker.items() if v is not None}}


def main():
    os.chdir(ROOT)
    os.umask(0o077)
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    app_env, worker_env = setup()
    name = 'keyhunt-personal-postgres'
    found = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True)
    if found.returncode:
        subprocess.run(['docker', 'run', '-d', '--name', name, '--label', 'keyhunt.owner=personal',
            '-p', '127.0.0.1:55432:5432', '--env-file', str(PRIVATE / 'postgres.env'),
            '-v', name + ':/var/lib/postgresql/data', 'postgres:17-alpine'], check=True, stdout=subprocess.DEVNULL)
    else:
        container = json.loads(found.stdout)[0]
        if container['Config'].get('Labels', {}).get('keyhunt.owner') != 'personal':
            raise SystemExit('Container name is already in use by another project.')
        subprocess.run(['docker', 'start', name], check=True, stdout=subprocess.DEVNULL)
    for _ in range(30):
        if subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'keyhunt'], capture_output=True).returncode == 0:
            break
        time.sleep(1)
    else:
        raise SystemExit('Personal database did not become ready.')
    subprocess.run(['npm', 'run', 'db:migrate'], env=app_env, check=True)
    children = []
    try:
        for command, env, logname in [
            (['npm', 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', '3000'], app_env, 'app.log'),
            ([str(ROOT / '.venv/bin/python'), '-m', 'uvicorn', 'househunt.web.app:app', '--host', '127.0.0.1', '--port', '8788'], worker_env, 'worker.log')]:
            with (PRIVATE / logname).open('a') as log:
                children.append(subprocess.Popen(command, env=env, stdout=log, stderr=log, start_new_session=True))
        print('Keyhunt personal: http://127.0.0.1:3000 · Ctrl-C stops the app; your searches stay saved.', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise SystemExit('A service stopped. Check data/personal/app.log and worker.log.')
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(child.pid, signal.SIGKILL)


if __name__ == '__main__':
    main()
