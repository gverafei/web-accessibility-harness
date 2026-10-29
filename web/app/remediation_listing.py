"""Compact recorded remediation summaries for fast local browsing."""

def hydrate_search(rows, iterations, store):
    """Attach persisted IDs and case labels, without loading evidence or answers."""
    by_run = {row['id']: row for row in rows}
    for row in rows:
        row['search_ids'] = {'run': str(row['id']), 'iterations': []}
        row['search_aliases'] = []
    for item in iterations:
        if item.get('id') is not None and item.get('run_id') in by_run:
            by_run[item['run_id']]['search_ids']['iterations'].append(str(item['id']))
    if not by_run:
        return
    with store.connect() as db:
        aliases = db.execute("SELECT json_extract(payload,'$.run_id') run_id,"
            "json_extract(payload,'$.key') label FROM records WHERE kind='verification_case' "
            "AND json_extract(payload,'$.run_id') IN (" + ','.join('?' for _ in by_run) + ')',
            list(by_run)).fetchall()
    for item in aliases:
        if isinstance(item['label'], str):
            by_run[item['run_id']]['search_aliases'].append(item['label'])
    for row in rows:
        row['search_aliases'] = sorted(set(row['search_aliases']))


class CampaignReader:
    """Verify frozen manifests through one request-scoped catalogue connection."""

    def __init__(self, store, rows):
        import json
        identities = set()
        for row in rows:
            try:
                identity = json.loads(row.get('harness_config_json') or '{}').get('campaign_id')
            except (ValueError, TypeError):
                continue
            if identity:
                identities.add(identity)
        self.records = {}
        if identities:
            with store.connect() as database:
                placeholders = ','.join('?' for _ in identities)
                for record in database.execute('SELECT * FROM records WHERE id IN (' + placeholders + ')', sorted(identities)):
                    verified = store.unpack(record)
                    self.records[verified['id']] = verified

    def get(self, identity):
        return self.records[identity]


def hydrate_taxonomy(rows, connect):
    """Read full recorded taxonomy only for the displayed page or live batch."""
    import json
    if not rows:
        return
    connection = connect()
    cursor = connection.cursor(dictionary=True)
    try:
        identities = [row['id'] for row in rows]
        cursor.execute('SELECT id,harness_outcome_json FROM remediation_runs WHERE id IN ('
                       + ','.join(['%s'] * len(identities)) + ')', identities)
        evidence = {}
        for item in cursor.fetchall():
            try:
                outcome = json.loads(item.get('harness_outcome_json') or '{}') or {}
            except (ValueError, TypeError):
                outcome = {}
            evidence[item['id']] = outcome.get('taxonomy_measurement')
        for row in rows:
            row['taxonomy_measurement'] = evidence.get(row['id'])
    finally:
        cursor.close()
        connection.close()
