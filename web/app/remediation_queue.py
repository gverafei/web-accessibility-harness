"""Bounded asynchronous queue; shared execution slots enforce the global limit."""
from concurrent.futures import ThreadPoolExecutor

from remediation_concurrency import MAX_PARALLEL_REMEDIATIONS


class RemediationQueue:
    def __init__(self, app):
        self.app = app
        self.executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_REMEDIATIONS,
                                           thread_name_prefix='remediation')
        self.active = {}

    def _execute(self, run_id):
        from remediation_jobs import process_remediation
        with self.app.app_context():
            return process_remediation(self.app, run_id)

    def dispatch(self, run_ids, limit):
        for run_id, future in list(self.active.items()):
            if future.done():
                del self.active[run_id]
                try:
                    future.result()
                except Exception:
                    self.app.logger.exception('Remediation %s ended with an execution error', run_id)
        for run_id in run_ids:
            if len(self.active) >= limit:
                break
            if run_id not in self.active:
                self.active[run_id] = self.executor.submit(self._execute, run_id)
        return bool(self.active)

    def close(self):
        self.executor.shutdown(wait=True)
