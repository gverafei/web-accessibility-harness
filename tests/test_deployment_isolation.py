import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("isolation", ROOT / "tools/verify_isolation.py")
isolation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isolation)


class DeploymentIsolationTests(unittest.TestCase):
    def test_localhost_default(self):
        isolation.check_config(isolation.compose_config(80), 80)

    def test_configurable_alternative(self):
        isolation.check_config(isolation.compose_config(18081), 18081)

    def test_invalid_port_is_rejected(self):
        for port in (0, -1, 65536):
            with self.assertRaises(ValueError):
                isolation.compose_config(port)

    def test_wrong_listener_is_rejected(self):
        config = isolation.compose_config(18081)
        config["services"]["web"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(AssertionError):
            isolation.check_config(config, 18081)

    def test_fixed_name_is_rejected(self):
        config = isolation.compose_config(18081)
        config["services"]["db"]["container_name"] = "accessibility_db"
        with self.assertRaises(AssertionError):
            isolation.check_config(config, 18081)

    def test_external_storage_is_rejected(self):
        config = isolation.compose_config(18081)
        config["volumes"]["mysql_data"]["external"] = True
        with self.assertRaises(AssertionError):
            isolation.check_config(config, 18081)


if __name__ == "__main__":
    unittest.main()
