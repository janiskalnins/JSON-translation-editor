"""Unit tests for make_readme_images.py.  python Tools/test_make_readme_images.py"""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_readme_images as mri  # noqa: E402


class VersionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "app.py"

    def tearDown(self):
        self._tmp.cleanup()

    def test_version_is_read_from_source(self):
        self.src.write_text('X = 1\nAPP_VERSION = "39"   # comment\n', encoding="utf-8")
        self.assertEqual(mri.read_app_version(self.src), "39")

    def test_missing_version_raises(self):
        self.src.write_text("X = 1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            mri.read_app_version(self.src)


class TitleTests(unittest.TestCase):
    def test_main_title_matches_the_app(self):
        self.assertEqual(mri.main_title("39"), "JSON Translation Editor v39 — es.json")


class GradientTests(unittest.TestCase):
    def test_top_left_is_the_first_stop(self):
        img = mri.gradient((100, 100), mri.THEMES["dark"]["stops"])
        self.assertTrue(all(abs(a - b) <= 4 for a, b in zip(img.getpixel((0, 0)), (0x0E, 0x63, 0x9C))))


class FrameTests(unittest.TestCase):
    def setUp(self):
        self.win = mri.frame(Image.new("RGB", (400, 200), "#336699"), "Title", "dark", True)

    def test_frame_adds_a_title_bar(self):
        self.assertEqual(self.win.size, (400, 200 + mri.px(mri.TITLE_H)))

    def test_frame_corners_are_transparent(self):
        self.assertEqual(self.win.getpixel((0, 0))[3], 0)

    def test_frame_keeps_the_screenshot(self):
        self.assertEqual(self.win.getpixel((200, 150))[:3], (0x33, 0x66, 0x99))


class FinishTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "out.png"
        mri.finish(Image.new("RGBA", (1000, 500), (10, 20, 30, 255)), 500, self.path)
        self.img = Image.open(self.path)

    def tearDown(self):
        self.img.close()
        self._tmp.cleanup()

    def test_finish_scales_to_the_width(self):
        self.assertEqual(self.img.size, (500, 250))

    def test_finish_rounds_the_outer_corners(self):
        self.assertEqual(self.img.getpixel((0, 0))[3], 0)


if __name__ == "__main__":
    unittest.main()
