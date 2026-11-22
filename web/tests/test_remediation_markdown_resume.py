import unittest
from unittest.mock import patch
from remediation_jobs import restored_markdown_view


class MarkdownResumeTests(unittest.TestCase):
    def test_legacy_local_markdown_resolves_captured_base_without_loop_locals(self):
        run = {'transformation_format':'markdown', 'markdown_provider':'local',
               'captured_url':'https://example.org/redirect/', 'source_url':'https://initial.test/'}
        source = '<html><head><base href="../assets/"></head><body><a href="task">Task</a></body></html>'
        result = restored_markdown_view({}, run, source)
        self.assertIn('https://example.org/assets/task', result['markdown'])

    def test_saved_external_view_is_reused_without_requesting_provider(self):
        saved = {'provider':'jina', 'markdown':'Saved paid projection'}
        with patch('remediation_jobs.markdown_representation', side_effect=AssertionError('No new extraction')):
            self.assertIs(restored_markdown_view({'markdown_view':saved},
                          {'transformation_format':'markdown', 'markdown_provider':'jina'}, ''), saved)
            self.assertIsNone(restored_markdown_view({},
                              {'transformation_format':'markdown', 'markdown_provider':'jina'}, ''))
