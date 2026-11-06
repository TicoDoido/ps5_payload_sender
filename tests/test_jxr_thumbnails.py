import tempfile
import unittest
from pathlib import Path

from jxr_thumbnails import build_jxr_thumbnails_html


class JXRThumbnailTests(unittest.TestCase):
    def test_batch_page_embeds_items_and_console_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "thumbnail.jxr"
            source.write_bytes(b"small-jxr-thumbnail")
            page = build_jxr_thumbnails_html([("abcdef0123456789", str(source))])

        self.assertIn("jpegxr()", page)
        self.assertIn("abcdef0123456789", page)
        self.assertIn("c21hbGwtanhyLXRodW1ibmFpbA==", page)
        self.assertIn("PS5_THUMB:", page)
        self.assertIn("image/jpeg", page)
        self.assertIn('info.bitDepth === "10"', page)
        self.assertIn("packed >>> 22", page)

    def test_invalid_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "thumbnail.jxr"
            source.write_bytes(b"data")
            with self.assertRaises(ValueError):
                build_jxr_thumbnails_html([("../unsafe", str(source))])

    def test_empty_batch_is_rejected(self):
        with self.assertRaises(ValueError):
            build_jxr_thumbnails_html([])


if __name__ == "__main__":
    unittest.main()
