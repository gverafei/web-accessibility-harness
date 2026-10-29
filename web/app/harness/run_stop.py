"""Explicit user stop requests, observed at financially safe run boundaries."""

REASON = 'Stopped by user'


class RunStopped(Exception):
    def __init__(self):
        super().__init__(REASON)


def request_id(run_id):
    return 'sql-run-' + str(int(run_id)) + '-stop-request'


def requested(store, run_id):
    try:
        record = store.get(request_id(run_id))
    except KeyError:
        return False
    return (isinstance(record, dict) and record.get('kind') == 'run_stop_request'
            and record.get('data', {}).get('run_id') == int(run_id))


def request_stop(store, run_id):
    return store.append('run_stop_request', {
        'run_id': int(run_id), 'reason': REASON,
        'boundary': 'Finish the current candidate and preserve recorded results; do not start another generation.'
    }, ident=request_id(run_id))
