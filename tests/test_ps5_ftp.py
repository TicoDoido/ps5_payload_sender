import ftplib
import os
import tempfile
import unittest

from ps5_ftp import FTPEntry, PS5FTPClient


class FakeFTP:
    def __init__(self):
        self.current = "/"
        self.directories = {
            "/": [],
            "/gallery": [
                ("CUSA00001", {"type": "dir"}),
                ("cover.jpg", {"type": "file", "size": "123", "modify": "20261106120000"}),
            ],
            "/gallery/CUSA00001": [
                ("capture one.mp4", {"type": "file", "size": "456", "modify": "20261106130000"}),
                ("shot.png", {"type": "file", "size": "789", "modify": "20261106110000"}),
            ],
        }
        self.uploaded = b""

    def pwd(self):
        return self.current

    def cwd(self, path):
        if path == "/":
            target = "/"
        elif path.startswith("/"):
            target = os.path.normpath(path).replace("\\", "/")
        else:
            target = os.path.normpath(self.current.rstrip("/") + "/" + path).replace("\\", "/")
        if target not in self.directories:
            raise ftplib.error_perm("550 Not a directory")
        self.current = target

    def mlsd(self):
        return iter(self.directories.get(self.current, []))

    def retrbinary(self, command, callback, blocksize=8192):
        callback(b"capture-bytes")

    def storbinary(self, command, source, blocksize=8192):
        self.uploaded = source.read()

    def quit(self):
        pass

    def close(self):
        pass


class PS5FTPTests(unittest.TestCase):
    def setUp(self):
        self.client = PS5FTPClient("127.0.0.1")
        self.fake = FakeFTP()
        self.client.ftp = self.fake

    def test_list_dir_uses_mlsd_and_restores_current_directory(self):
        entries = self.client.list_dir("/gallery")
        self.assertEqual(self.fake.pwd(), "/")
        self.assertEqual([entry.name for entry in entries], ["CUSA00001", "cover.jpg"])
        self.assertTrue(entries[0].is_dir)
        self.assertEqual(entries[1].size, 123)

    def test_walk_media_finds_nested_photos_and_videos(self):
        entries = self.client.walk_media("/gallery", [".jpg", ".png", ".mp4"], max_depth=3)
        self.assertEqual({entry.name for entry in entries}, {"cover.jpg", "shot.png", "capture one.mp4"})

    def test_download_is_written_to_local_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = os.path.join(folder, "capture.mp4")
            self.client.download_file("/gallery/capture.mp4", target)
            with open(target, "rb") as stream:
                self.assertEqual(stream.read(), b"capture-bytes")

    def test_read_bytes_reads_and_limits_sidecar_payload(self):
        self.assertEqual(self.client.read_bytes("/gallery/capture.dat"), b"capture-bytes")
        self.assertEqual(self.client.read_bytes("/gallery/capture.dat", max_bytes=7), b"capture")

    def test_upload_file_uses_stor_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "payload.elf")
            with open(source, "wb") as stream:
                stream.write(b"payload-to-upload")
            self.client.upload_file(source, "/gallery/payload.elf")
        self.assertEqual(self.fake.uploaded, b"payload-to-upload")

    def test_upload_rejects_missing_local_file(self):
        with self.assertRaises(FileNotFoundError):
            self.client.upload_file(r"C:\missing\payload.elf", "/gallery/payload.elf")
    def test_unix_list_parser_keeps_spaces_in_file_name(self):
        entry = self.client._entry_from_list_line(
            "-rw-r--r-- 1 user group 123 Nov 06 12:30 screenshot one.jpg",
            "/gallery",
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.name, "screenshot one.jpg")
        self.assertFalse(entry.is_dir)
        self.assertEqual(entry.size, 123)


if __name__ == "__main__":
    unittest.main()

