"""Shared atomic corpus pointer; published collections are immutable snapshots."""
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(os.getenv('RAG_STATE_ROOT', '/data/act-rag'))


def read_json(name):
    try:
        value = json.loads((ROOT / name).read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Invalid RAG-ACT maintenance state')
        return value
    except FileNotFoundError:
        return {}


def write_json(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=ROOT)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, ROOT / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def active_collection(default):
    collection = read_json('corpus.json').get('collection', default)
    if not isinstance(collection, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', collection):
        raise ValueError('Invalid RAG-ACT corpus pointer')
    return collection
