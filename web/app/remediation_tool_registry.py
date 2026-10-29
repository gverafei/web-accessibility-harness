"""Typed tool contracts and auditable invocation records for agent roles."""
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class ToolContract:
    name: str
    version: str
    description: str
    required_inputs: tuple
    output_type: str
    deterministic: bool
    mutates_candidate: bool = False

    def evidence(self):
        return {'name':self.name,'version':self.version,'description':self.description,
                'required_inputs':list(self.required_inputs),'output_type':self.output_type,
                'deterministic':self.deterministic,'mutates_candidate':self.mutates_candidate}


class ToolRegistry:
    def __init__(self):
        self._tools = {}
        self.records = []

    def register(self, contract, handler):
        if contract.name in self._tools: raise ValueError('Duplicate tool: '+contract.name)
        self._tools[contract.name] = (contract,handler)

    def invoke(self, name, **inputs):
        if name not in self._tools: raise KeyError('Unregistered remediation tool: '+name)
        contract, handler = self._tools[name]
        missing = [key for key in contract.required_inputs if key not in inputs]
        if missing: raise ValueError(f"{name} missing required inputs: {', '.join(missing)}")
        started = time.monotonic()
        record = {'tool':name,'version':contract.version,'status':'running',
                  'input_keys':sorted(inputs),'deterministic':contract.deterministic,
                  'mutates_candidate':contract.mutates_candidate}
        try:
            result = handler(**inputs)
            validators = {
                'object': lambda value: isinstance(value,dict),
                'array': lambda value: isinstance(value,list),
                'tuple': lambda value: isinstance(value,tuple),
                'integer': lambda value: isinstance(value,int) and not isinstance(value,bool),
                'number': lambda value: isinstance(value,(int,float)) and not isinstance(value,bool),
                'number_or_null': lambda value: value is None or isinstance(value,(int,float)) and not isinstance(value,bool),
            }
            validator = validators.get(contract.output_type)
            if validator and not validator(result):
                raise TypeError(f'{name} returned {type(result).__name__}; expected {contract.output_type}')
            record['status'] = 'completed'
            record['output_type'] = type(result).__name__
            return result
        except Exception as error:
            record['status'] = 'failed'; record['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            record['seconds'] = round(time.monotonic()-started,4)
            self.records.append(record)

    def contracts(self):
        return [contract.evidence() for contract,_ in self._tools.values()]
