"""Explicit maintenance requests consumed by the single deployment worker.

The shared filesystem lock also serializes CLI requests and multiple web workers.
GET observes atomic JSON state; it never starts maintenance or a model call.
"""
import fcntl
import logging
from contextlib import contextmanager

import requests

import rag_corpus
from database import get_connection
from remediation_rag import COLLECTION, QDRANT_URL

LOG = logging.getLogger(__name__)


class SyncConflict(ValueError):
    pass


@contextmanager
def maintenance_lock():
    rag_corpus.ROOT.mkdir(parents=True, exist_ok=True)
    with (rag_corpus.ROOT / 'maintenance.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SyncConflict('Synchronization is already running.') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def active_runs():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM remediation_runs WHERE status IN ('queued','running')")
        return int((cursor.fetchone() or {}).get('total') or 0)
    finally:
        cursor.close()
        conn.close()


def corpus_info():
    collection = rag_corpus.active_collection(COLLECTION)
    response = requests.get(f'{QDRANT_URL}/collections/{collection}', timeout=3)
    if response.status_code == 404:
        return {'reachable':True,'count':0,'official':0,'complementary':0,'synchronized_at':None}
    response.raise_for_status()
    count = int((response.json().get('result') or {}).get('points_count') or 0)
    manifest = rag_corpus.read_json('corpus.json')
    if manifest.get('collection') == collection and manifest.get('points') == count:
        return {'reachable':True,'count':count,'official':manifest['official'],
                'complementary':manifest['complementary'],'synchronized_at':manifest['synchronized_at']}
    # Inspect older installations without changing their collection or inventing dates.
    official = complementary = 0
    offset = None
    offsets = set()
    while count:
        body = {'limit':1000,'with_payload':['source','source_kind'],'with_vector':False}
        if offset is not None:
            body['offset'] = offset
        result = requests.post(f'{QDRANT_URL}/collections/{collection}/points/scroll', json=body, timeout=3)
        result.raise_for_status()
        page = result.json().get('result') or {}
        for point in page.get('points') or []:
            payload = point.get('payload') or {}
            official += payload.get('source') == 'W3C ACT Rules'
            complementary += payload.get('source_kind') == 'curated_guidance'
        offset = page.get('next_page_offset')
        if offset is None:
            break
        if str(offset) in offsets:
            raise ValueError('Repeated ACT corpus pagination cursor')
        offsets.add(str(offset))
    return {'reachable':True,'count':count,'official':official,'complementary':complementary,
            'synchronized_at':None}


def view():
    try:
        corpus = corpus_info()
    except (requests.RequestException, OSError, ValueError, KeyError):
        corpus = {'reachable':False,'count':None,'official':None,'complementary':None,'synchronized_at':None}
    return {'corpus':corpus, 'job':rag_corpus.read_json('job.json'), 'active_runs':active_runs()}


def enqueue(mode, confirmed=False):
    if mode not in {'initialize','update'}:
        raise ValueError('Choose Initialize or Update.')
    if mode == 'update' and not confirmed:
        raise SyncConflict('Confirm the corpus update first.')
    with maintenance_lock():
        job = rag_corpus.read_json('job.json')
        if job.get('status') == 'queued':
            raise SyncConflict('Synchronization is already queued.')
        if active_runs():
            raise SyncConflict('Wait for queued or running remediations to finish before synchronizing.')
        info = corpus_info()
        if mode == 'initialize' and info['count']:
            raise SyncConflict('The corpus already contains examples. Use Update knowledge.')
        job = {'status':'queued','mode':mode,'phase':'queued','percent':0,'error':None}
        rag_corpus.write_json('job.json', job)
        return job


def process_pending():
    try:
        with maintenance_lock():
            job = rag_corpus.read_json('job.json')
            if job.get('status') == 'running':
                # Acquiring this lock proves the previous writer is no longer alive.
                job.update(status='failed',error='Synchronization was interrupted. Start it again explicitly.',phase='failed')
                rag_corpus.write_json('job.json', job)
                return True
            if job.get('status') != 'queued' or active_runs():
                return False
            job.update(status='running',phase='starting')
            rag_corpus.write_json('job.json', job)
            def progress(phase, percent):
                job.update(phase=phase,percent=percent)
                rag_corpus.write_json('job.json', job)
            try:
                from sync_act_rag import main
                metadata = main(initialize_only=job['mode']=='initialize',progress=progress)
                job.update(status='completed',phase='completed',percent=100,completed_at=metadata['synchronized_at'])
                LOG.info('RAG-ACT synchronization completed: %s', metadata)
            except Exception:
                LOG.exception('RAG-ACT synchronization failed; published corpus was not replaced')
                job.update(status='failed',phase='failed',error='Synchronization failed. The previous corpus was preserved. See worker logs.')
            rag_corpus.write_json('job.json', job)
            return True
    except SyncConflict:
        # Another maintenance process owns the lock; do not start research work.
        return True
    except (OSError, ValueError):
        # Corrupt maintenance state must not stop unrelated research jobs or be
        # overwritten with a fabricated success. The status endpoint reports it.
        LOG.exception('Cannot read RAG-ACT maintenance state; maintenance skipped')
        return False
