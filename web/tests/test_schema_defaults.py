import unittest
from unittest.mock import Mock
from pathlib import Path
from runpy import run_path
ensure_string_column_default = run_path(str(Path(__file__).resolve().parents[1] / "app/database.py"))["ensure_string_column_default"]

class SchemaDefaultTests(unittest.TestCase):
    def test_current_default_does_not_request_ddl_lock(self):
        cursor=Mock();cursor.fetchone.return_value=('disabled',)
        ensure_string_column_default(cursor,'remediation_runs','diagnosis_policy','disabled')
        self.assertEqual(cursor.execute.call_count,1)
        self.assertTrue(cursor.execute.call_args.args[0].startswith('SELECT COLUMN_DEFAULT'))

    def test_legacy_default_is_migrated_without_changing_existing_rows(self):
        cursor=Mock();cursor.fetchone.return_value=('conditional',)
        ensure_string_column_default(cursor,'remediation_runs','diagnosis_policy','disabled')
        self.assertEqual(cursor.execute.call_args.args,
            ('ALTER TABLE `remediation_runs` ALTER COLUMN `diagnosis_policy` SET DEFAULT %s', ('disabled',)))
        self.assertEqual(cursor.execute.call_count,2)

    def test_missing_column_is_not_silently_treated_as_current(self):
        cursor=Mock();cursor.fetchone.return_value=None
        with self.assertRaises(ValueError):ensure_string_column_default(cursor,'remediation_runs','diagnosis_policy','disabled')
