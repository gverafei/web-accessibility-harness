"""Explicit deterministic state machine around LLM roles and typed tools."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from remediation_skill_catalog import SkillCatalog
from remediation_tool_registry import ToolRegistry


TRANSITIONS = {
    'init': {'acquire'}, 'acquire': {'transform'}, 'transform': {'prompt','complete'},
    'prompt': {'generate','complete'}, 'generate': {'evaluate','decide','complete'},
    'evaluate': {'decide','complete'}, 'decide': {'prompt','complete'}, 'complete': set()
}


@dataclass
class AgentRuntime:
    step: int
    run_id: int
    max_cost_usd: float
    max_seconds: int
    catalog: SkillCatalog = field(default_factory=SkillCatalog)
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    state: str = 'init'
    transitions: list = field(default_factory=list)
    activated: dict = field(default_factory=dict)
    task_records: list = field(default_factory=list)

    def perform(self, name, handler, input_keys=()):
        from remediation_task_agents import TASKS, TaskAgent
        previous = getattr(self, 'active_task_name', None)
        self.active_task_name = name
        try:
            return TaskAgent(TASKS[name]).execute(handler, input_keys, self.task_records)
        finally:
            self.active_task_name = previous

    def move(self, target, iteration=None, reason=None):
        if target == self.state: return
        if target not in TRANSITIONS[self.state]:
            raise ValueError(f'Invalid remediation state transition: {self.state} -> {target}')
        self.transitions.append({'from':self.state,'to':target,'iteration':iteration,
            'reason':reason,'at':datetime.now(timezone.utc).isoformat()})
        self.state = target

    def skills_for(self, stage, rag=False, enabled=True):
        if not enabled:
            return []
        skills = self.catalog.select(self.step,stage,rag)
        for skill in skills: self.activated[skill.id] = skill
        return skills

    def snapshot(self, iteration_skills=(), tool_record_start=0):
        return {'schema_version':'agent-runtime-v1','state':self.state,
            'run_id':self.run_id,'step':self.step,
            'budgets':{'max_cost_usd':self.max_cost_usd,'max_seconds':self.max_seconds},
            'skill_manifest_sha256':self.catalog.manifest_sha256,
            'iteration_skills':[skill.evidence() for skill in iteration_skills],
            'activated_skills':[skill.evidence() for skill in self.activated.values()],
            'tool_contracts':self.tools.contracts(),
            'tool_invocations':list(self.tools.records[tool_record_start:]),
            'agent_tasks':list(self.task_records),
            'transitions':list(self.transitions)}
