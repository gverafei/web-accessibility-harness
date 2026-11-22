"""Evidence-bound, metadata-only resolution of historical consistency stops."""
import copy

from harness.contracts import ContractError, digest
from .consistency import compare

VERSION = 'context-review-resolution-v1'


def resolve(store, review_id, reference):
    parent = store.get(review_id)
    data = parent['data']
    before = store.get(data['before_assessment_id'])
    after = store.get(data['after_assessment_id'])
    if (parent['kind'] != 'taxonomy_consistency_review' or not data.get('review_required') or not reference.strip()
            or before['hash'] != data['before_assessment_hash']
            or after['hash'] != data['after_assessment_hash']):
        raise ContractError('Resolution requires the immutable original review and assessments')
    review = compare(before['data'], after['data'])
    identity = lambda row: (row['type'], row['before_opportunity_id'], row['after_opportunity_id'])
    if (review['review_required'] or not review['changes']
            or {identity(row) for row in review['changes']} != {identity(row) for row in data['changes']}
            or any(row['classification'] != 'context_changed_reassessment' for row in review['changes'])):
        raise ContractError('Every historical conflict must be explained by changed supplied context')
    payload = dict(version=VERSION, parent_review_id=parent['id'], parent_review_hash=parent['hash'],
                   before_assessment_id=before['id'], before_assessment_hash=before['hash'],
                   after_assessment_id=after['id'], after_assessment_hash=after['hash'],
                   review=review, reference=reference, raw_measurements_modified=False)
    return store.append('taxonomy_consistency_resolution', payload, parent['campaign'],
                        'taxonomy-context-resolution-' + digest(payload))


def revised_review(resolution):
    data = resolution['data']
    return dict(data['review'], before_assessment_id=data['before_assessment_id'],
                before_assessment_hash=data['before_assessment_hash'],
                after_assessment_id=data['after_assessment_id'],
                after_assessment_hash=data['after_assessment_hash'],
                record_id=resolution['id'], resolution_id=resolution['id'],
                original_review_id=data['parent_review_id'],
                resolution_note='The supplied context changed; both verdicts are retained. The historical stop is resolved without changing scores, resuming the run or proving judge repeatability.')


def validate_revision(store, revision, incumbent):
    data = revision['data']
    resolution = store.get(data['resolution_id'])
    rd = resolution['data']
    if (resolution['kind'] != 'taxonomy_consistency_resolution'
            or resolution['campaign'] != revision['campaign']
            or data.get('raw_measurements_modified') is not False
            or digest(incumbent) != data.get('parent_outcome_hash')
            or (incumbent.get('measurement_consistency') or {}).get('record_id') != rd['parent_review_id']
            or incumbent.get('taxonomy_measurement', {}).get('retained_assessment_id') != rd['after_assessment_id']):
        raise ContractError('Consistency revision must bind the owned outcome and its original review')
    # Recompute the classification from immutable evidence, never trust a caller's flag.
    before, after = store.get(rd['before_assessment_id']), store.get(rd['after_assessment_id'])
    parent = store.get(rd['parent_review_id'])
    fields = ('before_assessment_id', 'before_assessment_hash', 'after_assessment_id', 'after_assessment_hash')
    if (rd.get('version') != VERSION or data.get('version') != VERSION
            or parent['kind'] != 'taxonomy_consistency_review' or parent['campaign'] != resolution['campaign']
            or any(parent['data'].get(key) != rd.get(key) for key in fields)
            or parent['hash'] != rd['parent_review_hash'] or before['hash'] != rd['before_assessment_hash']
            or after['hash'] != rd['after_assessment_hash'] or rd['review']['review_required']
            or compare(before['data'], after['data']) != rd['review']):
        raise ContractError('Consistency resolution evidence or classification changed')
    expected = copy.deepcopy(incumbent)
    expected['measurement_consistency'] = revised_review(resolution)
    if data['outcome'] != expected:
        raise ContractError('Consistency resolution may change only review metadata, never measurements or resources')


def revise_outcome(store, parent_id, resolution_id):
    parent = store.get(parent_id)
    incumbent = parent['data'] if parent['kind'] == 'run_result' else parent['data']['outcome']
    resolution = store.get(resolution_id)
    outcome = copy.deepcopy(incumbent)
    outcome['measurement_consistency'] = revised_review(resolution)
    payload = dict(version=VERSION, parent_outcome_id=parent_id, parent_outcome_hash=digest(incumbent),
                   resolution_id=resolution_id, outcome=outcome, raw_measurements_modified=False)
    validate_revision(store, dict(data=payload, campaign=parent['campaign']), incumbent)
    return store.append('taxonomy_consistency_revision', payload, parent['campaign'],
                        'taxonomy-consistency-outcome-' + digest(payload))
