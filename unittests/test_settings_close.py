"""Tests for _on_settings_close — the fix for the Save Settings crash."""

import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tkinter as tk
import winsnap


class TestOnSettingsClose(unittest.TestCase):
    """_on_settings_close must cleanly destroy the tkinter root."""

    def test_basic_close(self):
        """Normal close destroys root and resets flag."""
        root = tk.Tk()
        root.withdraw()
        winsnap._settings_window_open = True
        winsnap._on_settings_close(root)
        self.assertFalse(winsnap._settings_window_open)

    def test_double_close_no_crash(self):
        """Calling close twice should not raise."""
        root = tk.Tk()
        root.withdraw()
        winsnap._on_settings_close(root)
        winsnap._on_settings_close(root)  # must not crash

    def test_close_with_non_tk_object(self):
        """Non-Tk objects should be safely ignored."""
        winsnap._on_settings_close("not a window")
        winsnap._on_settings_close(42)
        winsnap._on_settings_close(None)

    def test_flag_resets_on_exception(self):
        """Flag is reset even if root is already destroyed."""
        root = tk.Tk()
        root.withdraw()
        winsnap._settings_window_open = True
        root.destroy()
        # Root is already destroyed; close should still reset the flag
        winsnap._on_settings_close(root)
        self.assertFalse(winsnap._settings_window_open)


if __name__ == "__main__":
    unittest.main()
