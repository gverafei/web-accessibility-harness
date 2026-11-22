"""Process-safe private catalogue; immutable evidence and explicit mutable checkpoints."""
import json
import fcntl
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .contracts import SCHEMA, canonical, digest


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('HARNESS_ROOT', '/data/harness'))
        self.read_only = os.getenv('HARNESS_READ_ONLY') == '1'
        self.path = self.root / 'catalogue.sqlite3'
        if self.read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, campaign TEXT NOT NULL,
                    payload TEXT NOT NULL, hash TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS record_scope ON records(kind,campaign,created);
                CREATE INDEX IF NOT EXISTS taxonomy_supplement_lookup
                    ON records(json_extract(payload,'$.supplement_fingerprint'),created,id)
                    WHERE kind='taxonomy_assessment';
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS claims (id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS partitions (
                    study TEXT NOT NULL, domain TEXT NOT NULL, partition TEXT NOT NULL,
                    PRIMARY KEY(study,domain));
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        if self.read_only:
            from urllib.parse import quote
            db = sqlite3.connect('file:' + quote(str(self.path)) + '?mode=ro', uri=True, timeout=30)
        else:
            db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def append(self, kind, payload, campaign='', ident=None):
        ident = ident or uuid.uuid4().hex
        data = {'schema': SCHEMA, **payload}
        with self.connect() as db:
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                       (ident, kind, campaign, canonical(data), digest(data), time.time()))
            record = self.unpack(db.execute('SELECT * FROM records WHERE id=?', (ident,)).fetchone())
            if record['kind'] != kind or record['hash'] != digest(data):
                raise Conflict('Evidence identifier already names different content: ' + ident)
        return record

    @contextmanager
    def named_lock(self, ident):
        directory = self.root / 'evidence-locks'
        directory.mkdir(exist_ok=True)
        with (directory / (digest(ident) + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def get(self, ident):
        with self.connect() as db:
            row = db.execute('SELECT * FROM records WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        return self.unpack(row)

    @staticmethod
    def unpack(row):
        data = json.loads(row['payload'])
        if digest(data) != row['hash']:
            raise Conflict('Evidence checksum mismatch')
        return {'id': row['id'], 'kind': row['kind'], 'campaign': row['campaign'],
                'created': row['created'], 'hash': row['hash'], 'data': data}

    def list(self, kind=None, campaign=None):
        clauses, args = [], []
        for key, value in (('kind', kind), ('campaign', campaign)):
            if value is not None:
                clauses.append(key + '=?'); args.append(value)
        query = 'SELECT * FROM records' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY created,id'
        with self.connect() as db:
            rows = db.execute(query, args).fetchall()
        return [self.unpack(row) for row in rows]

    def checkpoint(self, ident, value=None, revision=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,payload FROM checkpoints WHERE id=?', (ident,)).fetchone()
            if value is None:
                return (json.loads(row['payload']), row['revision']) if row else ({}, 0)
            current = row['revision'] if row else 0
            if revision is not None and revision != current:
                raise Conflict('Checkpoint changed; reload before updating')
            db.execute('INSERT INTO checkpoints VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',
                       (ident, current + 1, canonical(value)))
            return value, current + 1

    def claim(self, ident, owner, seconds=900):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM claims WHERE id=?', (ident,)).fetchone()
            if row and row['expires'] > time.time() and row['owner'] != owner:
                return False
            db.execute('INSERT INTO claims VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires',
                       (ident, owner, time.time() + seconds))
        return True

    def release(self, ident, owner):
        with self.connect() as db:
            db.execute('DELETE FROM claims WHERE id=? AND owner=?', (ident, owner))

    def assign_domain(self, study, domain, partition):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT partition FROM partitions WHERE study=? AND domain=?', (study, domain)).fetchone()
            if row and row['partition'] != partition:
                raise Conflict('Domain already belongs to a different study partition: ' + domain)
            db.execute('INSERT OR IGNORE INTO partitions VALUES (?,?,?)', (study, domain, partition))

    def blob(self, content, role, campaign='', media_type='text/plain', shareable=False):
        import hashlib
        raw = content.encode() if isinstance(content, str) else content
        sha = hashlib.sha256(raw).hexdigest()
        directory = self.root / 'blobs'; directory.mkdir(exist_ok=True)
        path = directory / sha
        if not path.exists():
            temporary = directory / (sha + '.' + uuid.uuid4().hex)
            with temporary.open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, 0o600); os.replace(temporary, path)
        return self.append('artifact', {'sha256': sha, 'size': len(raw), 'role': role,
                                       'media_type': media_type, 'shareable': bool(shareable)}, campaign)

    def read_blob(self, ident):
        import hashlib
        record = self.get(ident)
        if record['kind'] != 'artifact':
            raise ValueError('Not an artifact')
        data = (self.root / 'blobs' / record['data']['sha256']).read_bytes()
        if hashlib.sha256(data).hexdigest() != record['data']['sha256']:
            raise Conflict('Artifact checksum mismatch')
        return data
