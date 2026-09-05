"""Unit tests for the HUD OCR worker's pure logic (worker/ocr_agent.py).

OCR/cv2/MQTT are imported lazily inside the methods that need them, so the
parsing/region/payload helpers are testable without those heavy deps.
"""

import json
import os
import tempfile
import unittest

from worker.ocr_agent import (
    build_payload,
    crop_box,
    parse_number,
    parse_regions,
    regions_from_file,
)


class TestParseNumber(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_number("42"), 42)

    def test_thousands_separator(self):
        self.assertEqual(parse_number("1,500"), 1500)

    def test_with_unit_and_label(self):
        self.assertEqual(parse_number("HP 80%"), 80)

    def test_takes_first_group(self):
        self.assertEqual(parse_number("12/30"), 12)

    def test_empty_and_garbage(self):
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number("---"))
        self.assertIsNone(parse_number(None))  # type: ignore[arg-type]


class TestParseRegions(unittest.TestCase):
    def test_single(self):
        regions = parse_regions("health:0.04,0.9,0.1,0.05")
        self.assertEqual(regions["health"], (0.04, 0.9, 0.1, 0.05))

    def test_multiple(self):
        regions = parse_regions(
            "health:0.04,0.9,0.1,0.05;ammo:0.86,0.9,0.1,0.05"
        )
        self.assertEqual(set(regions), {"health", "ammo"})

    def test_rejects_bad_shape(self):
        with self.assertRaises(ValueError):
            parse_regions("health:0.1,0.2,0.3")  # only 3 values

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_regions("health:1.2,0.2,0.3,0.1")

    def test_rejects_past_edge(self):
        with self.assertRaises(ValueError):
            parse_regions("health:0.95,0.2,0.2,0.1")  # x + w > 1

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_regions("   ")


class TestRegionsFromFile(unittest.TestCase):
    def test_roundtrip(self):
        data = {"health": [0.04, 0.9, 0.1, 0.05], "ammo": [0.86, 0.9, 0.1, 0.05]}
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            regions = regions_from_file(path)
            self.assertEqual(regions["health"], (0.04, 0.9, 0.1, 0.05))
            self.assertEqual(set(regions), {"health", "ammo"})
        finally:
            os.unlink(path)


class TestCropBox(unittest.TestCase):
    def test_basic(self):
        # 1000x500 frame, region at (0.1,0.2) size (0.2,0.1)
        self.assertEqual(crop_box(1000, 500, (0.1, 0.2, 0.2, 0.1)),
                         (100, 100, 300, 150))

    def test_clamped_and_nonempty(self):
        left, top, right, bottom = crop_box(640, 360, (0.99, 0.99, 0.01, 0.01))
        self.assertLess(left, right)
        self.assertLess(top, bottom)
        self.assertLessEqual(right, 640)
        self.assertLessEqual(bottom, 360)


class TestBuildPayload(unittest.TestCase):
    def test_shape(self):
        payload = build_payload("ocr_worker", {"health": 80}, 12.34)
        self.assertEqual(payload["worker_id"], "ocr_worker")
        self.assertEqual(payload["fields"], {"health": 80})
        self.assertEqual(payload["ocr_ms"], 12.3)
        self.assertIn("timestamp", payload)


if __name__ == "__main__":
    unittest.main()
