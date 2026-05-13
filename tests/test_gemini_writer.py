from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from cc_switch_tool.writers import gemini


class GeminiWriterTest(unittest.TestCase):
    def test_apply_profile_writes_model_to_settings(self) -> None:
        with tempfile.TemporaryDirectory() as home, patch.dict("os.environ", {"HOME": home}):
            changed = gemini.apply_profile(
                {
                    "api_key": "test-key",
                    "base_url": "https://example.test/",
                    "model": "gemini-3.1-pro-preview",
                }
            )

            from pathlib import Path

            home_path = Path(home)
            settings_path = home_path / ".gemini" / "settings.json"
            env_path = home_path / ".gemini" / ".env"
            active_env_path = home_path / ".cc-switch-tool" / "active.env"

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(settings["model"]["name"], "gemini-3.1-pro-preview")
            self.assertEqual(settings["security"]["auth"]["selectedType"], "gemini-api-key")
            self.assertEqual(
                env_path.read_text(encoding="utf-8"),
                "GEMINI_API_KEY=test-key\n"
                "GOOGLE_GEMINI_BASE_URL=https://example.test/\n",
            )
            self.assertIn("GEMINI_API_KEY=test-key", active_env_path.read_text(encoding="utf-8"))
            self.assertIn(str(settings_path), changed)
