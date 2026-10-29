"""Whole-frame simple random sampling with an explicit ordered reserve."""
import random
from .contracts import digest, number


def sample(ranking, list_id, seed, count, reserve_count=0):
    count = number(count, 'sample size', 1, len(ranking), True)
    reserve_count = number(reserve_count, 'reserves', 0, len(ranking) - count, True)
    ordered = sorted(ranking)
    rng = random.Random(digest({'list': list_id, 'seed': str(seed), 'sampler': 'whole-frame-srs-v1'}))
    indices = rng.sample(range(len(ordered)), count + reserve_count)
    return [{'rank': ordered[index][0], 'domain': ordered[index][1], 'url': 'https://' + ordered[index][1] + '/',
             'order': position, 'role': 'selected' if position < count else 'reserve'}
            for position, index in enumerate(indices)]


def author_sample(run_ids, count, seed):
    ordered = sorted(set(run_ids))
    if count > len(ordered):
        raise ValueError('Author sample exceeds eligible runs')
    return random.Random(str(seed)).sample(ordered, count)
