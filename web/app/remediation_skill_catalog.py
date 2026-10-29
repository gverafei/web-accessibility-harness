"""Versioned, immutable skill contracts used by the remediation runtime."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


MANIFEST = Path(__file__).with_name('agent_skills') / 'manifest.json'


@dataclass(frozen=True)
class Skill:
    id: str
    version: str
    stages: tuple
    steps: tuple
    tools: tuple
    instruction: str
    sources: tuple
    digest: str

    def evidence(self):
        return {'id': self.id, 'version': self.version, 'sha256': self.digest,
                'tools': list(self.tools), 'sources': list(self.sources)}


class SkillCatalog:
    def __init__(self, path=MANIFEST):
        raw = Path(path).read_bytes()
        data = json.loads(raw)
        self._load(data, hashlib.sha256(raw).hexdigest())

    @classmethod
    def from_data(cls, data):
        instance = cls.__new__(cls)
        raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        instance._load(data, hashlib.sha256(raw).hexdigest())
        return instance

    def _load(self, data, manifest_digest):
        if data.get('schema_version') != '1.0':
            raise ValueError('Unsupported remediation skill manifest schema')
        self.manifest_sha256 = manifest_digest
        self.skills = {}
        for item in data.get('skills') or []:
            required = {'id','version','stages','steps','tools','instruction','sources'}
            if required - item.keys():
                raise ValueError('Incomplete remediation skill contract: '+str(sorted(required-item.keys())))
            canonical = json.dumps(item,sort_keys=True,separators=(',',':')).encode()
            skill = Skill(item['id'],item['version'],tuple(item['stages']),tuple(item['steps']),
                          tuple(item['tools']),item['instruction'],tuple(item['sources']),
                          hashlib.sha256(canonical).hexdigest())
            if skill.id in self.skills: raise ValueError('Duplicate remediation skill: '+skill.id)
            self.skills[skill.id] = skill

    def select(self, step, stage, rag=False):
        selected = [skill for skill in self.skills.values()
                    if int(step) in skill.steps and stage in skill.stages]
        if not rag:
            selected = [skill for skill in selected if skill.id != 'adaptive-evidence-grounding']
        return selected

    def prompt_context(self, skills):
        if not skills: return ''
        return '\n'.join(f"SKILL {s.id}@{s.version} [{s.digest[:12]}]: {s.instruction}"
                         for s in skills)
