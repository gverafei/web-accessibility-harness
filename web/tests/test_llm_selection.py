import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

if "database" not in sys.modules:
    database_stub = types.ModuleType("database")
    database_stub.init_db = lambda: None
    database_stub.get_connection = lambda: None
    sys.modules["database"] = database_stub

main = importlib.import_module("main")
experiments_module = importlib.import_module("routes.experiments")


class FakeCursor:
    def __init__(self):
        self.lastrowid = 42
        self.executions = []

    def execute(self, statement, parameters=None):
        self.executions.append((statement, parameters))

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()

    def cursor(self, **_kwargs):
        return self.cursor_instance

    def commit(self):
        pass

    def close(self):
        pass


class LlmSelectionTestCase(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()
        main.app.config.update(
            OPENROUTER_API_KEY_CONFIGURED=True,
            OPENROUTER_BASE_URL_CONFIGURED=True,
            WAVE_API_KEY_CONFIGURED=True,
            LLAMA_MODEL="meta-llama/test",
            CLAUDE_MODEL="anthropic/test",
        )




    def test_unconfigured_optional_services_are_not_offered(self):
        with patch.dict(main.app.config, {
            "OPENROUTER_API_KEY_CONFIGURED": False,
            "OPENROUTER_BASE_URL_CONFIGURED": False,
            "WAVE_API_KEY_CONFIGURED": False,
        }):
            response = self.client.get("/acquisition/new")

        self.assertNotIn(b'name="include_semantic"', response.data)
        self.assertNotIn(b'name="semantic_provider"', response.data)
        self.assertNotIn(b'name="include_wave"', response.data)




if __name__ == "__main__":
    unittest.main()
