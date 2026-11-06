import json
import unittest

from ps5_ftp import FTPEntry
from ps5_media import (
    build_capture_details,
    capture_datetime,
    capture_title_id,
    parse_capture_game_name,
)


class FakeFTP:
    def __init__(self):
        self.files = {}
        self.directories = {}

    def list_dir(self, path):
        return self.directories.get(path, [])

    def read_bytes(self, path, max_bytes=None):
        data = self.files[path]
        return data if max_bytes is None else data[:max_bytes]


def make_dat(game_name: str) -> bytes:
    data = bytearray(1024)
    encoded = game_name.encode("utf-8")
    data[0x44:0x44 + len(encoded)] = encoded
    return bytes(data)


class PS5MediaTests(unittest.TestCase):
    def test_parse_dat_game_name_and_strip_timestamp(self):
        dat = make_dat("A Quiet Place: The Road Ahead_20261105231538")
        self.assertEqual(parse_capture_game_name(dat), "A Quiet Place: The Road Ahead")

    def test_extract_title_id_from_folder_tree(self):
        entry = FTPEntry(
            "20261105_231538_00412378.jxr",
            "/user/av_contents/photo/NPXS40087/PPSA19007/054/20261105_231538_00412378.jxr",
            False,
            201551,
        )
        self.assertEqual(capture_title_id(entry), "PPSA19007")

    def test_pair_dat_and_meta(self):
        parent = "/user/av_contents/photo/NPXS40087/PPSA19007/054"
        stem = "20261105_231538_00412378"
        media = FTPEntry(stem + ".jxr", parent + "/" + stem + ".jxr", False, 201551)
        dat_entry = FTPEntry(stem + ".dat", parent + "/" + stem + ".dat", False, 1024)
        meta_entry = FTPEntry(stem + ".meta", parent + "/" + stem + ".meta", False, 944)

        meta = {
            "appVer": "01.006.000",
            "appVerTitleId": "PPSA19007",
            "segmentInfo": {"absoluteTime": [[1793931338000, 1793931338000]]},
        }
        client = FakeFTP()
        client.directories[parent] = [media, dat_entry, meta_entry]
        client.files[dat_entry.path] = make_dat("A Quiet Place: The Road Ahead_20261105231538")
        client.files[meta_entry.path] = json.dumps(meta).encode("utf-8")

        details = build_capture_details(client, [media])[media.path]
        self.assertEqual(details["title_id"], "PPSA19007")
        self.assertEqual(details["game_name"], "A Quiet Place: The Road Ahead")
        self.assertEqual(details["captured_at"], "05/11/2026 23:15:38")
        self.assertTrue(details["has_dat"])
        self.assertTrue(details["has_meta"])
        self.assertEqual(details["app_version"], "01.006.000")

    def test_filename_timestamp_fallback(self):
        entry = FTPEntry(
            "20261105_231538_00412378.mp4",
            "/user/av_contents/video/NPXS40087/PPSA19007/054/20261105_231538_00412378.mp4",
            False,
            123,
        )
        self.assertEqual(capture_datetime(entry), "05/11/2026 23:15:38")


if __name__ == "__main__":
    unittest.main()

