import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from payload_sender import send_payload


class FakeSocket:
    def __init__(self):
        self.chunks = []
        self.timeout = None
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        self.chunks.append(bytes(data))


class PayloadSenderTests(unittest.TestCase):
    def test_sends_raw_file_in_chunks_without_protocol_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "payload.elf"
            source.write_bytes(bytes(range(32)))
            fake = FakeSocket()
            with patch("payload_sender.socket.create_connection", return_value=fake) as connect:
                ok, message = send_payload(str(source), "192.168.15.4", 9021,
                                           timeout=3, chunk_size=7)

        self.assertTrue(ok, message)
        connect.assert_called_once_with(("192.168.15.4", 9021), timeout=3)
        self.assertEqual(b"".join(fake.chunks), bytes(range(32)))
        self.assertEqual([len(chunk) for chunk in fake.chunks], [7, 7, 7, 7, 4])
        self.assertTrue(fake.closed)

    def test_missing_file_returns_failure(self):
        ok, message = send_payload(r"C:\missing\payload.elf", "192.168.15.4")
        self.assertFalse(ok)
        self.assertIn("encontrado", message)

    def test_zero_chunk_size_is_rejected(self):
        ok, message = send_payload("unused", "192.168.15.4", chunk_size=0)
        self.assertFalse(ok)
        self.assertIn("maior que zero", message)


if __name__ == "__main__":
    unittest.main()
