"""Large discovery caches and failed transactions must not lock catalogue edits."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import settings

class SettingsStorageTests(unittest.TestCase):
    def test_existing_text_column_is_widened_and_second_check_is_idempotent(self):
        spec=importlib.util.spec_from_file_location('settings_storage_database',Path(__file__).parents[1]/'app'/'database.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        cursor=Mock();cursor.fetchone.return_value=('setting_value','text')
        module.ensure_settings_capacity(cursor)
        self.assertIn('LONGTEXT',cursor.execute.call_args.args[0])
        cursor.reset_mock();cursor.fetchone.return_value=('setting_value','longtext')
        module.ensure_settings_capacity(cursor)
        self.assertEqual(cursor.execute.call_count,1)
    def test_failed_cache_save_rolls_back_and_releases_connection(self):
        conn=Mock();cursor=conn.cursor.return_value;cursor.execute.side_effect=ValueError('fixture storage failure')
        with patch.object(settings,'get_connection',return_value=conn),self.assertRaises(ValueError):
            settings.save_settings({'generative_model_metadata_json':'x'*100000})
        conn.rollback.assert_called_once();cursor.close.assert_called_once();conn.close.assert_called_once()
        conn.commit.assert_not_called()
