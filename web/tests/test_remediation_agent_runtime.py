import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0,str(APP))

from remediation_agent_runtime import AgentRuntime
from remediation_skill_catalog import SkillCatalog
from remediation_tool_registry import ToolContract


class AgentRuntimeTests(unittest.TestCase):
    def test_catalog_selects_step_specific_versioned_skills(self):
        catalog=SkillCatalog()
        minimal={skill.id for skill in catalog.select(1,'generate')}
        born={skill.id for skill in catalog.select(5,'generate')}
        self.assertEqual(minimal,{'minimal-preservation-repair'})
        self.assertEqual(born,{'markdown-born-accessible-regeneration'})
        context=catalog.prompt_context(catalog.select(1,'prompt',rag=True))
        self.assertIn('grounded-accessibility-diagnosis@1.0.0',context)
        self.assertIn('adaptive-evidence-grounding@1.0.0',context)

    def test_state_machine_rejects_implicit_stage_jumps(self):
        runtime=AgentRuntime(1,42,.2,240)
        with self.assertRaisesRegex(ValueError,'init -> generate'):
            runtime.move('generate')
        for stage in ('acquire','transform','prompt','generate','evaluate','decide','complete'):
            runtime.move(stage,1,'test')
        self.assertEqual(runtime.state,'complete')
        self.assertEqual(len(runtime.transitions),7)

    def test_admitted_source_can_finish_before_prompting(self):
        runtime=AgentRuntime(1,42,.2,240)
        for stage in ('acquire','transform','complete'):
            runtime.move(stage,reason='fixture source already meets targets')
        self.assertEqual(runtime.state,'complete')
        self.assertEqual([row['to'] for row in runtime.transitions],['acquire','transform','complete'])
        self.assertEqual(runtime.tools.records,[])

    def test_tool_contract_validates_inputs_and_records_failure(self):
        runtime=AgentRuntime(1,42,.2,240)
        contract=ToolContract('double','1.0','Double a value',('value',),'integer',True)
        runtime.tools.register(contract,lambda value:value*2)
        self.assertEqual(runtime.tools.invoke('double',value=3),6)
        with self.assertRaisesRegex(ValueError,'missing required inputs'):
            runtime.tools.invoke('double')
        self.assertEqual([r['status'] for r in runtime.tools.records],['completed'])

    def test_tool_contract_rejects_invalid_output_type(self):
        runtime=AgentRuntime(1,42,.2,240)
        contract=ToolContract('inventory','1.0','Return an inventory',(),'object',True)
        runtime.tools.register(contract,lambda: [])
        with self.assertRaisesRegex(TypeError,'expected object'):
            runtime.tools.invoke('inventory')
        self.assertEqual(runtime.tools.records[-1]['status'],'failed')

    def test_snapshot_contains_reproducible_contract_evidence(self):
        runtime=AgentRuntime(4,99,.4,600)
        skills=runtime.skills_for('generate')
        snapshot=runtime.snapshot(skills)
        self.assertEqual(snapshot['schema_version'],'agent-runtime-v1')
        self.assertEqual(snapshot['iteration_skills'][0]['id'],'html-born-accessible-regeneration')
        self.assertEqual(len(snapshot['skill_manifest_sha256']),64)

    def test_empty_baseline_snapshot_has_no_activated_skills(self):
        runtime=AgentRuntime(1,100,.05,300)
        for stage in ('prompt','generate','evaluate','decide'):
            self.assertEqual(runtime.skills_for(stage,rag=True,enabled=False),[])
        runtime.tools.register(ToolContract('measure','1.0','Measure',(),'object',True),lambda:{})
        runtime.tools.invoke('measure')
        snapshot=runtime.snapshot(())
        self.assertEqual(snapshot['iteration_skills'],[])
        self.assertEqual(snapshot['activated_skills'],[])
        self.assertEqual(snapshot['tool_invocations'][0]['tool'],'measure')
