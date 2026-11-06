import base64
import os
import tempfile
import unittest
from pathlib import Path

from jxr_preview import (
    build_jxr_viewer_html,
    decode_jpeg_preview_base64,
    decode_png_preview_base64,
)


class JXRPreviewTests(unittest.TestCase):
    def test_preview_html_embeds_decoder_and_jxr_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "capture.jxr"
            source.write_bytes(b"sample-jxr-bytes")
            page = build_jxr_viewer_html(str(source), "A Quiet Place: The Road Ahead", result_token="preview42")

        self.assertIn("jpegxr()", page)
        self.assertIn("A Quiet Place: The Road Ahead", page)
        self.assertIn("c2FtcGxlLWp4ci1ieXRlcw==", page)
        self.assertIn('output[target + 3] = 255;', page)
        self.assertIn("PS5_JXR_PREVIEW:preview42:", page)
        self.assertIn("PS5_JXR_SAVE_PNG:preview42:", page)
        self.assertIn("PS5_JXR_ERROR:preview42:", page)
        self.assertIn("window.ps5SavePng", page)
        self.assertNotIn("PS5_JXR_SAVE:", page)
        self.assertIn("image/jpeg", page)
        self.assertIn('bitDepth === "10"', page)
        self.assertIn("packed >>> 20", page)

    def test_jpeg_preview_bridge_validates_jpeg_bytes(self):
        jpeg = b"\xff\xd8\xffsample-jpeg"
        payload = base64.b64encode(jpeg).decode("ascii")
        self.assertEqual(decode_jpeg_preview_base64(payload), jpeg)
        with self.assertRaises(ValueError):
            decode_jpeg_preview_base64(base64.b64encode(b"not-a-jpeg").decode("ascii"))

    def test_png_preview_bridge_validates_png_signature(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        payload = base64.b64encode(png).decode("ascii")
        self.assertEqual(decode_png_preview_base64(payload), png)
        with self.assertRaises(ValueError):
            decode_png_preview_base64(base64.b64encode(b"not-a-png").decode("ascii"))

    def test_preview_token_is_embedded_in_all_events(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "capture.jxr"
            source.write_bytes(b"sample")
            page = build_jxr_viewer_html(str(source), result_token="capture42")
        self.assertIn("PS5_JXR_PREVIEW:capture42:", page)
        self.assertIn("PS5_JXR_SAVE_PNG:capture42:", page)
        self.assertIn("PS5_JXR_ERROR:capture42:", page)

    def test_invalid_preview_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "capture.jxr"
            source.write_bytes(b"sample")
            with self.assertRaises(ValueError):
                build_jxr_viewer_html(str(source), result_token="bad:token")

    def test_missing_capture_fails_cleanly(self):
        with self.assertRaises(FileNotFoundError):
            build_jxr_viewer_html(os.path.join(tempfile.gettempdir(), "missing-capture.jxr"))


if __name__ == "__main__":
    unittest.main()
