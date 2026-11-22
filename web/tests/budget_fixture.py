"""Pilot readiness fixtures; no provider or acquisition observations."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import test_harness
from harness.contracts import ContractError, validate_manifest
from harness.engine import create_campaign
from harness.export import bundle
from harness.providers import Ledger, BudgetStop, UncertainCall
from harness.preparation import protocol_bundle
from harness.pilot import build, resolve, choose_pages
from harness import benchmark
from harness.relevance import relevance_metrics

class PreparationTest(unittest.TestCase):

    def setUp(self):
        self.fixture = test_harness.HarnessTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.store = self.fixture.store
        self.manifest = self.fixture.manifest

    def group_campaign(self, stage='matrix', limits=None):
        value = copy.deepcopy(self.manifest)
        value['budget_group'] = {'id': 'shared', 'stage': stage, 'total_usd': 0.3, 'stage_limits': limits or {'matrix': 0.1, 'other': 0.2}}
        return create_campaign(self.store, value)
