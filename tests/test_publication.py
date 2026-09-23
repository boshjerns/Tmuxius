"""Keep private metadata and hidden trailing data out of published screenshots."""

from pathlib import Path
import runpy
import struct
import unittest
import zlib


CHECK = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/check-publication.py"))
PNG_PROBLEM = CHECK["png_problem"]
SIGNATURE = b"\x89PNG\r\n\x1a\n"
PIXELS = b"\x00\x20\x30\x40"


def chunk(kind, payload=b""):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload)))


def header(width=1, height=1):
    return chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))


def png(compressed=None):
    if compressed is None:
        compressed = zlib.compress(PIXELS)
    return SIGNATURE + header() + chunk(b"IDAT", compressed) + chunk(b"IEND")


class PublicationImageTests(unittest.TestCase):
    def test_accepts_plain_png_and_split_image_chunks(self):
        self.assertIsNone(PNG_PROBLEM(png()))
        data = zlib.compress(PIXELS)
        split = (SIGNATURE + header() + chunk(b"IDAT", data[:3])
                 + chunk(b"IDAT", data[3:]) + chunk(b"IEND"))
        self.assertIsNone(PNG_PROBLEM(split))

    def test_rejects_trailing_bytes_even_when_they_resemble_chunks(self):
        for trailer in (b"PRIVATE", b"\x00\x00\x40\x00IDATprivate-fixture", chunk(b"IEND")):
            with self.subTest(trailer=trailer):
                self.assertIsNotNone(PNG_PROBLEM(png() + trailer))

    def test_rejects_truncation_at_every_byte(self):
        data = png()
        for length in range(len(data)):
            with self.subTest(length=length):
                self.assertIsNotNone(PNG_PROBLEM(data[:length]))

    def test_rejects_metadata(self):
        for kind in (b"eXIf", b"iTXt", b"tEXt", b"zTXt", b"acTL"):
            with self.subTest(kind=kind):
                data = png()
                self.assertIsNotNone(PNG_PROBLEM(data[:-12] + chunk(kind, b"private-fixture") + data[-12:]))

    def test_rejects_bad_checksums_and_chunk_order(self):
        data = bytearray(png())
        data[29] ^= 1
        self.assertIsNotNone(PNG_PROBLEM(bytes(data)))
        self.assertIsNotNone(PNG_PROBLEM(SIGNATURE + chunk(b"IEND")))
        self.assertIsNotNone(PNG_PROBLEM(SIGNATURE + header() + header() + png()[33:]))
        self.assertIsNotNone(PNG_PROBLEM(SIGNATURE + header() + chunk(b"IEND")))

    def test_rejects_hidden_data_inside_compressed_stream(self):
        for payload in (zlib.compress(PIXELS) + b"private-fixture",
                        zlib.compress(PIXELS) + zlib.compress(b"private-fixture"),
                        zlib.compress(PIXELS + b"private-fixture")):
            with self.subTest(payload=payload):
                self.assertIsNotNone(PNG_PROBLEM(png(payload)))

    def test_rejects_invalid_pixels_and_decompression_bombs(self):
        for pixels in (PIXELS[:-1], b"\x05\x20\x30\x40", b"x" * 100_000):
            with self.subTest(length=len(pixels)):
                self.assertIsNotNone(PNG_PROBLEM(png(zlib.compress(pixels))))
        self.assertIsNotNone(PNG_PROBLEM(SIGNATURE + header(100_000, 100_000)))
        self.assertIsNotNone(PNG_PROBLEM(SIGNATURE + header(0, 1)))


if __name__ == "__main__":
    unittest.main()
