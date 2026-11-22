import unittest
from unittest.mock import MagicMock, patch

from main import app
from settings import SETTING_DEFAULTS


class RemediationTargetSettingsTests(unittest.TestCase):


    def test_fresh_installation_preserves_illustrative_study_defaults(self):
        self.assertEqual(SETTING_DEFAULTS['remediation_min_lighthouse'],'90')
        self.assertEqual(SETTING_DEFAULTS['remediation_max_axe'],'5')
        self.assertEqual(SETTING_DEFAULTS['remediation_max_iterations'],'3')
        self.assertEqual(SETTING_DEFAULTS['remediation_max_cost_usd'],'0.25')
        self.assertEqual(SETTING_DEFAULTS['remediation_max_execution_seconds'],'360')
