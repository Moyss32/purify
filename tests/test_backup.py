import json
import tempfile
import unittest
from pathlib import Path

from core.backup import clear_pre_state, get_pre_state, save_pre_state


class BackupTests(unittest.TestCase):
    def test_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".purify" / "session_backup.json"
            value = {"unit_file_state": "enabled", "active_state": "active"}
            save_pre_state("service-x", value, path)
            self.assertEqual(get_pre_state("service-x", path), value)
            content = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("saved_at", content["service-x"])
            clear_pre_state("service-x", path)
            self.assertIsNone(get_pre_state("service-x", path))

    def test_missing_backup_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(get_pre_state("missing", Path(folder) / "none.json"))


if __name__ == "__main__":
    unittest.main()
