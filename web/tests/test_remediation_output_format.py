import tempfile,unittest
from pathlib import Path
from remediation_output_format import output_format,recorded_output_format
from remediation_report_presentation import retained_progress
class OutputFormatTests(unittest.TestCase):
 def test_prose_is_retained_but_not_described_as_a_corrected_page(self):
  self.assertEqual(output_format("I cannot provide the full document. The `div` needs a label."),'no-html-document')
  run={'status':'completed_with_warnings','execution_mode':'single_shot','accepted_iteration_id':343,'recorded_output_format':'no-html-document'}
  self.assertEqual(retained_progress(run,1,2,50),'Raw zero-shot response retained · no HTML document returned')
 def test_valid_and_fragment_outputs_are_distinct(self):
  self.assertEqual(output_format('<!doctype html><html lang="en"><head><title>A</title></head><body><main>A</main></body></html>'),'html-document')
  self.assertEqual(output_format('<main>Hello</main>'),'html-fragment')
 def test_history_projection_uses_scoped_bytes_without_writes(self):
  with tempfile.TemporaryDirectory()as root:
   path=Path(root)/'remediations/276/candidate.html';path.parent.mkdir(parents=True);path.write_text('No complete document returned.');before=path.read_bytes()
   self.assertEqual(recorded_output_format(path,276,root),'no-html-document');self.assertIsNone(recorded_output_format(path,277,root));self.assertEqual(path.read_bytes(),before)
