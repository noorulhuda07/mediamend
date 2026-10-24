import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class DemoModeTests(unittest.TestCase):
    def test_public_demo_exposes_no_file_actions_or_folder_picker(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        with patch.dict(os.environ, {"MEDIAMEND_DEMO": "1"}):
            app = AppTest.from_file(str(app_path)).run(timeout=15)

        self.assertFalse(app.exception)
        self.assertTrue(any("Public read-only demo" in item.value for item in app.warning))
        labels = [item.label for item in app.button]
        labels += [item.label for item in app.checkbox]
        labels += [item.label for item in app.text_input]
        self.assertNotIn("Move selected to Bin", labels)
        self.assertNotIn("Move to Bin", labels)
        self.assertNotIn("Restore", labels)
        self.assertNotIn("Delete permanently", labels)
        self.assertFalse(any(label.startswith("Media folder") for label in labels))


if __name__ == "__main__":
    unittest.main()
