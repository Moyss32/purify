import unittest
from unittest.mock import patch

from core.manager import PurifyManager
from platforms.windows.windows10 import DisableServiceOperation, RemoveAppxPackageOperation, get_operations


class WindowsCatalogTests(unittest.TestCase):
    def test_catalog_ids_are_unique_and_nothing_is_preselected(self):
        operations = get_operations()
        ids = [op.id for op in operations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(operations)
        self.assertTrue(all(not op.is_selected for op in operations))

    def test_every_appx_entry_uses_an_exact_package_identity(self):
        operations = get_operations()
        appx = [op for op in operations if isinstance(op, RemoveAppxPackageOperation)]
        self.assertGreaterEqual(len(appx), 15)
        self.assertTrue(all("*" not in op.package_name and "?" not in op.package_name for op in appx))

    def test_original_telemetry_services_are_represented(self):
        operations = get_operations()
        services = {op.service_name for op in operations if isinstance(op, DisableServiceOperation)}
        self.assertTrue({"DiagTrack", "dmwappushservice", "WerSvc"}.issubset(services))
        self.assertIn("wuauserv", services)

    @patch("platforms.windows.windows10._run_json")
    def test_full_windows_scan_batches_appx_and_services(self, run_json):
        def respond(script):
            if "Get-AppxPackage" in script:
                return True, [], ""
            if "Get-CimInstance Win32_Service" in script:
                return True, [], ""
            return False, None, "query inesperada"
        run_json.side_effect = respond
        operations = get_operations()
        manager = PurifyManager(operations, {"platform": "windows", "is_admin": True})
        result = manager.inspect_all_states(max_workers=4)
        self.assertEqual(len(result), len(operations))
        self.assertEqual(run_json.call_count, 2)
        self.assertTrue(all(state["known"] for _, state in result))
        scripts = [call.args[0] for call in run_json.call_args_list]
        self.assertTrue(any("Get-AppxPackage" in script for script in scripts))
        self.assertTrue(any("Get-CimInstance Win32_Service" in script for script in scripts))
        for script in scripts:
            self.assertNotIn("Remove-AppxPackage", script)
            self.assertNotIn("Set-Service", script)


if __name__ == "__main__":
    unittest.main()
