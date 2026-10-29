"""Visible count units follow the existing records-versus-unique-URLs contracts."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from flask import render_template, render_template_string, session

APP_DIR = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP_DIR))
if 'database' not in sys.modules:
    stub = types.ModuleType('database')
    stub.init_db = lambda: None
    stub.get_connection = lambda: None
    sys.modules['database'] = stub

from main import app
from routes.experiments import build_experiments_summary


class PageCountLabelTests(unittest.TestCase):

    def test_summary_keeps_failed_and_imported_records_without_deduplication(self):
        summary = build_experiments_summary([
            {'status': 'completed', 'processed_urls': 10, 'completed_urls': 8},
            {'status': 'completed', 'processed_urls': 5, 'completed_urls': 5,
             'experiment_origin': 'import'},
            {'status': 'running', 'processed_urls': 2, 'completed_urls': 1},
        ])
        self.assertEqual(summary['processed_urls'], 17)
        self.assertEqual(summary['total_experiments'], 3)


if __name__ == '__main__':
    unittest.main()
