"""Independent task contracts with recorded starts, outputs and completion."""
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class TaskContract:
    name: str
    goal: str
    result_type: str


TASKS = {
    'source-verifier': TaskContract('Source verifier', 'Verify the same stored page and its replay.', 'object'),
    'component-planner': TaskContract('Component planner', 'Plan evidence-grounded component repair.', 'model_result'),
    'repair-diagnostician': TaskContract('Repair diagnostician', 'Identify a supported cause of repair stagnation.', 'model_result'),
    'repair-generator': TaskContract('Repair generator', 'Generate within the assigned intervention contract.', 'model_result'),
    'contextual-assessor': TaskContract('Contextual assessor', 'Measure the candidate taxonomy and census coverage.', 'object'),
    'visual-reviewer': TaskContract('Visual reviewer', 'Record observable candidate-local visual findings.', 'object'),
    'decision-specialist': TaskContract('Decision specialist', 'Choose useful continuation within fixed permissions and budgets.', 'object'),
}


class TaskAgent:
    def __init__(self, contract):
        self.contract = contract

    def execute(self, handler, input_keys, records):
        started = time.monotonic()
        record = {'agent': self.contract.name, 'goal': self.contract.goal,
                  'input_keys': sorted(input_keys), 'status': 'running'}
        records.append(record)
        try:
            result = handler()
            valid = (isinstance(result, dict) if self.contract.result_type == 'object'
                     else isinstance(result, tuple) and len(result) == 6
                     and isinstance(result[0], str))
            if not valid:
                raise TypeError('Task result does not match ' + self.contract.result_type)
            record.update(status='completed', result_type=self.contract.result_type)
            return result
        except Exception as error:
            record.update(status='incomplete', error_type=type(error).__name__)
            raise
        finally:
            record['seconds'] = round(time.monotonic() - started, 4)
