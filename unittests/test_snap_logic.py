"""Tests for snap logic: identity matching, snapifiability, icon path resolution."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import winsnap


class TestWindowIdentity(unittest.TestCase):
    """_window_identity returns (pid, class_name, title) or None."""

    def test_identities_match_same(self):
        id1 = (1234, "Notepad", "Untitled - Notepad")
        id2 = (1234, "Notepad", "Untitled - Notepad")
        self.assertTrue(winsnap._identities_match(id1, id2))

    def test_identities_match_different_pid(self):
        id1 = (1234, "Notepad", "Untitled - Notepad")
        id2 = (5678, "Notepad", "Untitled - Notepad")
        self.assertFalse(winsnap._identities_match(id1, id2))

    def test_identities_match_different_class(self):
        id1 = (1234, "Notepad", "Untitled - Notepad")
        id2 = (1234, "Chrome", "Untitled - Notepad")
        self.assertFalse(winsnap._identities_match(id1, id2))


class TestIsSnapifiable(unittest.TestCase):
    """_is_snapifiable filters out null, invisible, and shell windows."""

    def test_null_hwnd(self):
        self.assertFalse(winsnap._is_snapifiable(0))

    def test_negative_hwnd(self):
        self.assertFalse(winsnap._is_snapifiable(-1))


class TestResolveIconPath(unittest.TestCase):
    """_resolve_icon_path picks dev vs frozen path correctly."""

    def test_dev_path(self):
        """Without sys.frozen, returns icon/icon.ico next to script."""
        with patch.object(sys, "frozen", False, create=True):
            path = winsnap._resolve_icon_path()
            self.assertTrue(path.endswith(os.path.join("icon", "icon.ico")))

    def test_frozen_path(self):
        """With sys.frozen, returns icon.ico in _MEIPASS."""
        fake_meipass = "C:\\fake\\_MEIPASS"
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", fake_meipass, create=True):
            path = winsnap._resolve_icon_path()
            self.assertEqual(path, os.path.join(fake_meipass, "icon.ico"))


class TestGetBorderOffsets(unittest.TestCase):
    """get_border_offsets returns (0,0,0,0) on failure."""

    def test_invalid_hwnd_returns_zeros(self):
        """An invalid HWND should return the safe fallback."""
        result = winsnap.get_border_offsets(0)
        self.assertEqual(result, (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
