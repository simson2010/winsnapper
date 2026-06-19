"""Tests for hotkey normalization and duplicate detection."""

import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import winsnap


class TestNormalizeHotkey(unittest.TestCase):
    """_normalize_hotkey lowercases and strips whitespace around '+' separators."""

    def test_already_normalized(self):
        self.assertEqual(winsnap._normalize_hotkey("ctrl+alt+left"), "ctrl+alt+left")

    def test_uppercase(self):
        self.assertEqual(winsnap._normalize_hotkey("Ctrl+Alt+Left"), "ctrl+alt+left")

    def test_extra_spaces(self):
        self.assertEqual(winsnap._normalize_hotkey("ctrl + alt + left"), "ctrl+alt+left")

    def test_single_key(self):
        self.assertEqual(winsnap._normalize_hotkey("f1"), "f1")

    def test_empty_string(self):
        self.assertEqual(winsnap._normalize_hotkey(""), "")


class TestFindDuplicateHotkeys(unittest.TestCase):
    """_find_duplicate_hotkeys returns pairs of actions sharing a combo."""

    def test_no_duplicates(self):
        result = winsnap._find_duplicate_hotkeys(winsnap.DEFAULT_HOTKEYS)
        self.assertEqual(result, [])

    def test_duplicate_pair(self):
        hotkeys = dict(winsnap.DEFAULT_HOTKEYS)
        hotkeys["right"] = hotkeys["left"]  # both ctrl+alt+left
        result = winsnap._find_duplicate_hotkeys(hotkeys)
        self.assertEqual(len(result), 1)
        a, b = result[0]
        self.assertIn(a, ("left", "right"))
        self.assertIn(b, ("left", "right"))
        self.assertNotEqual(a, b)

    def test_empty_hotkey_not_duplicate(self):
        """Empty hotkey strings are not considered duplicates."""
        hotkeys = dict(winsnap.DEFAULT_HOTKEYS)
        hotkeys["left"] = ""
        hotkeys["right"] = ""
        result = winsnap._find_duplicate_hotkeys(hotkeys)
        self.assertEqual(result, [])

    def test_case_insensitive_duplicate(self):
        """Duplicates are detected regardless of case."""
        hotkeys = dict(winsnap.DEFAULT_HOTKEYS)
        hotkeys["left"] = "CTRL+ALT+LEFT"
        hotkeys["right"] = "ctrl+alt+left"
        result = winsnap._find_duplicate_hotkeys(hotkeys)
        self.assertEqual(len(result), 1)


class TestConstants(unittest.TestCase):
    """Verify increment sizing constants are sane."""

    def test_increment_width_has_three_levels(self):
        self.assertEqual(len(winsnap.INCREMENT_WIDTH_PCT), 3)

    def test_increment_height_has_three_levels(self):
        self.assertEqual(len(winsnap.INCREMENT_HEIGHT_PCT), 3)

    def test_increment_values_order(self):
        """Values should be increasing: 50%, 75%, 100%."""
        self.assertEqual(winsnap.INCREMENT_WIDTH_PCT, [0.50, 0.75, 1.00])
        self.assertEqual(winsnap.INCREMENT_HEIGHT_PCT, [0.50, 0.75, 1.00])

    def test_default_hotkeys_has_all_actions(self):
        expected = {"left", "right", "top", "bottom", "center", "full", "restore"}
        self.assertEqual(set(winsnap.DEFAULT_HOTKEYS.keys()), expected)

    def test_action_labels_match_hotkeys(self):
        """Every key in DEFAULT_HOTKEYS has a label in ACTION_LABELS."""
        for action in winsnap.DEFAULT_HOTKEYS:
            self.assertIn(action, winsnap.ACTION_LABELS)


if __name__ == "__main__":
    unittest.main()
