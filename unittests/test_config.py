"""Tests for configuration load/save (winsnap.load_config, winsnap.save_config)."""

import json
import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import winsnap


class TestLoadConfig(unittest.TestCase):
    """load_config() returns merged defaults when file is missing or invalid."""

    def test_missing_file_returns_defaults(self):
        """When config file doesn't exist, defaults are returned."""
        original = winsnap.CONFIG_PATH
        winsnap.CONFIG_PATH = os.path.join(tempfile.gettempdir(), "nonexistent_winsnap.json")
        try:
            result = winsnap.load_config()
            self.assertEqual(result, winsnap.DEFAULT_HOTKEYS)
        finally:
            winsnap.CONFIG_PATH = original

    def test_invalid_json_returns_defaults(self):
        """When config file contains invalid JSON, defaults are returned."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            path = f.name
        original = winsnap.CONFIG_PATH
        winsnap.CONFIG_PATH = path
        try:
            result = winsnap.load_config()
            self.assertEqual(result, winsnap.DEFAULT_HOTKEYS)
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)

    def test_empty_hotkeys_merges_defaults(self):
        """When hotkeys dict is empty, all defaults are kept."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"hotkeys": {}}, f)
            path = f.name
        original = winsnap.CONFIG_PATH
        winsnap.CONFIG_PATH = path
        try:
            result = winsnap.load_config()
            self.assertEqual(result, winsnap.DEFAULT_HOTKEYS)
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)

    def test_partial_override(self):
        """Custom values override defaults; missing keys keep defaults."""
        custom = {"left": "ctrl+shift+a"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"hotkeys": custom}, f)
            path = f.name
        original = winsnap.CONFIG_PATH
        winsnap.CONFIG_PATH = path
        try:
            result = winsnap.load_config()
            self.assertEqual(result["left"], "ctrl+shift+a")
            self.assertEqual(result["right"], winsnap.DEFAULT_HOTKEYS["right"])
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)

    def test_unknown_keys_ignored(self):
        """Keys not in DEFAULT_HOTKEYS are silently ignored."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"hotkeys": {"unknown_key": "ctrl+x", "left": "ctrl+1"}}, f)
            path = f.name
        original = winsnap.CONFIG_PATH
        winsnap.CONFIG_PATH = path
        try:
            result = winsnap.load_config()
            self.assertNotIn("unknown_key", result)
            self.assertEqual(result["left"], "ctrl+1")
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)

    def test_whitespace_values_ignored(self):
        """Blank/whitespace-only values fall back to defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"hotkeys": {"left": "  ", "right": ""}}, f)
            path = f.name
        original = winsnap.CONFIG_PATH
        winsnap.CONFIG_PATH = path
        try:
            result = winsnap.load_config()
            self.assertEqual(result["left"], winsnap.DEFAULT_HOTKEYS["left"])
            self.assertEqual(result["right"], winsnap.DEFAULT_HOTKEYS["right"])
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)


class TestSaveConfig(unittest.TestCase):
    """save_config() writes valid JSON that load_config() can round-trip."""

    def test_round_trip(self):
        """save_config then load_config returns the same data."""
        original = winsnap.CONFIG_PATH
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        winsnap.CONFIG_PATH = path
        try:
            custom = dict(winsnap.DEFAULT_HOTKEYS)
            custom["left"] = "ctrl+shift+z"
            winsnap.save_config(custom)
            result = winsnap.load_config()
            self.assertEqual(result["left"], "ctrl+shift+z")
            self.assertEqual(result["right"], winsnap.DEFAULT_HOTKEYS["right"])
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)

    def test_file_is_valid_json(self):
        """The output file is parseable JSON."""
        original = winsnap.CONFIG_PATH
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name
        winsnap.CONFIG_PATH = path
        try:
            winsnap.save_config(winsnap.DEFAULT_HOTKEYS)
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("hotkeys", data)
            self.assertIsInstance(data["hotkeys"], dict)
        finally:
            winsnap.CONFIG_PATH = original
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
