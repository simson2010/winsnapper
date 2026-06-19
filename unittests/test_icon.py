"""Tests for icon.py: draw_icon, generate_svg, generate_all."""

import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from icon import draw_icon, generate_svg, generate_all


class TestDrawIcon(unittest.TestCase):
    """draw_icon returns a PIL Image of the correct size."""

    def test_returns_rgba_image(self):
        img = draw_icon(64, "blue")
        self.assertEqual(img.mode, "RGBA")

    def test_correct_size(self):
        for size in [16, 32, 64, 128, 256]:
            img = draw_icon(size, "blue")
            self.assertEqual(img.size, (size, size))

    def test_all_variants(self):
        for variant in ["blue", "green", "dark"]:
            img = draw_icon(32, variant)
            self.assertEqual(img.mode, "RGBA")
            self.assertEqual(img.size, (32, 32))


class TestGenerateSvg(unittest.TestCase):
    """generate_svg returns valid SVG markup."""

    def test_returns_string(self):
        svg = generate_svg("blue")
        self.assertIsInstance(svg, str)

    def test_contains_svg_tag(self):
        svg = generate_svg("blue")
        self.assertIn("<svg", svg)
        self.assertIn("</svg>", svg)

    def test_all_variants(self):
        for variant in ["blue", "green", "dark"]:
            svg = generate_svg(variant)
            self.assertIn("<svg", svg)


class TestGenerateAll(unittest.TestCase):
    """generate_all creates files in the output directory."""

    def setUp(self):
        self.outdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.outdir, ignore_errors=True)

    def test_creates_ico_file(self):
        generate_all(self.outdir, variants=["blue"], formats=["ico"])
        self.assertTrue(os.path.isfile(os.path.join(self.outdir, "icon.ico")))

    def test_creates_png_files(self):
        generate_all(self.outdir, variants=["blue"], formats=["png"])
        pngs = [f for f in os.listdir(self.outdir) if f.endswith(".png")]
        self.assertGreater(len(pngs), 0)

    def test_creates_svg_file(self):
        generate_all(self.outdir, variants=["blue"], formats=["svg"])
        svgs = [f for f in os.listdir(self.outdir) if f.endswith(".svg")]
        self.assertGreater(len(svgs), 0)


if __name__ == "__main__":
    unittest.main()
