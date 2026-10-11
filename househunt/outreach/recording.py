"""Import a recording downloaded from Dial's dashboard into private local storage.

No documented recording-download API is available yet; signed dashboard links expire.
Usage: python -m househunt.outreach.recording CALL_ID /path/to/download.wav
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import sys
if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv('.env')
from househunt import db


def recording_path(call_id: int) -> Path | None:
    from househunt.config import settings
    with db.conn() as c:
        row = c.execute('SELECT dial_call_id FROM calls WHERE id=?', (call_id,)).fetchone()
    if not row or not row['dial_call_id'] or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', row['dial_call_id']):
        return None
    return Path(settings.db_path).resolve().parent / 'recordings' / f"{row['dial_call_id']}.wav"


def import_recording(call_id: int, source: Path) -> Path:
    target = recording_path(call_id)
    if target is None:
        raise ValueError('No saved Dial call with that ID')
    if not 12 <= source.stat().st_size <= 100_000_000:
        raise ValueError('Expected a WAV recording smaller than 100 MB')
    with source.open('rb') as f:
        header = f.read(12)
    if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
        raise ValueError('Expected a WAV recording downloaded from Dial')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix('.tmp')
    with source.open('rb') as src, os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'wb') as dst:
        shutil.copyfileobj(src, dst)
    temporary.chmod(0o600)
    temporary.replace(target)
    with db.conn() as c:
        row = c.execute('SELECT outcome FROM calls WHERE id=?', (call_id,)).fetchone()
    outcome = json.loads(row['outcome']) if row['outcome'] else {}
    outcome['audio_url'] = f'/calls/{call_id}/recording'
    db.update_call(call_id, outcome=outcome)
    return target


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python -m househunt.outreach.recording CALL_ID /path/to/download.wav')
    db.init()
    path = import_recording(int(sys.argv[1]), Path(sys.argv[2]))
    print(f'Recording imported privately: {path}')
