"""Unit tests for the game-audio worker's pure DSP (worker/audio_agent.py).

sounddevice / numpy / MQTT are imported lazily inside the capture/MQTT paths,
so the DSP helpers and the analyzer are testable without those heavy deps.
"""

import math
import unittest

from worker.audio_agent import (
    AudioAnalyzer,
    AudioReading,
    build_payload,
    classify_intensity,
    event_for,
    peak,
    rms,
    to_db,
)


class TestLevelHelpers(unittest.TestCase):
    def test_rms_of_silence_is_zero(self):
        self.assertEqual(rms([0.0, 0.0, 0.0]), 0.0)
        self.assertEqual(rms([]), 0.0)

    def test_rms_of_constant(self):
        self.assertAlmostEqual(rms([0.5, 0.5, 0.5, 0.5]), 0.5)

    def test_rms_known_value(self):
        # RMS of [+1, -1] is 1.0
        self.assertAlmostEqual(rms([1.0, -1.0]), 1.0)

    def test_peak_takes_abs_max(self):
        self.assertEqual(peak([0.1, -0.8, 0.3]), 0.8)
        self.assertEqual(peak([]), 0.0)

    def test_to_db_floor_for_silence(self):
        self.assertEqual(to_db(0.0), -80.0)
        self.assertEqual(to_db(-0.5), -80.0)

    def test_to_db_full_scale_is_zero(self):
        self.assertAlmostEqual(to_db(1.0), 0.0)

    def test_to_db_half_scale(self):
        self.assertAlmostEqual(to_db(0.5), 20.0 * math.log10(0.5))


class TestClassifyIntensity(unittest.TestCase):
    def test_quiet(self):
        self.assertEqual(classify_intensity(0.01), "quiet")

    def test_moderate(self):
        self.assertEqual(classify_intensity(0.1), "moderate")

    def test_intense(self):
        self.assertEqual(classify_intensity(0.5), "intense")


class TestAnalyzer(unittest.TestCase):
    def test_first_loud_block_is_onset(self):
        an = AudioAnalyzer()
        reading = an.process([0.5] * 64)
        self.assertTrue(reading.onset)
        self.assertEqual(reading.intensity, "intense")

    def test_quiet_then_spike_is_onset(self):
        an = AudioAnalyzer()
        # Settle a quiet baseline first.
        for _ in range(20):
            an.process([0.005] * 64)
        spike = an.process([0.6] * 64)
        self.assertTrue(spike.onset)

    def test_steady_loud_stops_being_onset(self):
        an = AudioAnalyzer()
        an.process([0.5] * 64)  # first block: onset
        # After the baseline catches up, a steady level is no longer an onset.
        last = None
        for _ in range(50):
            last = an.process([0.5] * 64)
        self.assertFalse(last.onset)

    def test_intensity_change_flagged(self):
        an = AudioAnalyzer()
        an.process([0.005] * 64)  # quiet, establishes prev_intensity
        reading = an.process([0.5] * 64)  # jumps to intense
        self.assertTrue(reading.intensity_changed)

    def test_reset_clears_state(self):
        an = AudioAnalyzer()
        for _ in range(10):
            an.process([0.5] * 64)
        an.reset()
        # After reset the next loud block is treated as a fresh onset again.
        self.assertTrue(an.process([0.5] * 64).onset)


class TestEventFor(unittest.TestCase):
    def _reading(self, onset=False, changed=False):
        return AudioReading(
            rms=0.1, peak=0.2, db=-20.0, intensity="moderate",
            onset=onset, intensity_changed=changed,
        )

    def test_onset_wins(self):
        self.assertEqual(event_for(self._reading(onset=True, changed=True)), "onset")

    def test_intensity_change(self):
        self.assertEqual(
            event_for(self._reading(changed=True)), "intensity_change"
        )

    def test_routine_is_none(self):
        self.assertIsNone(event_for(self._reading()))


class TestBuildPayload(unittest.TestCase):
    def test_shape_with_event(self):
        reading = AudioReading(
            rms=0.4242, peak=0.7, db=-7.45, intensity="intense",
            onset=True, intensity_changed=False,
        )
        payload = build_payload("audio_worker", reading, "onset")
        self.assertEqual(payload["worker_id"], "audio_worker")
        self.assertEqual(payload["event"], "onset")
        signals = payload["signals"]
        self.assertEqual(signals["audio_db"], -7.5)
        self.assertEqual(signals["audio_level"], 0.4242)
        self.assertEqual(signals["audio_intensity"], "intense")
        self.assertEqual(signals["audio_event"], "onset")
        self.assertIn("timestamp", payload)

    def test_shape_without_event(self):
        reading = AudioReading(
            rms=0.01, peak=0.02, db=-40.0, intensity="quiet",
            onset=False, intensity_changed=False,
        )
        payload = build_payload("audio_worker", reading, None)
        self.assertNotIn("event", payload)
        self.assertNotIn("audio_event", payload["signals"])


if __name__ == "__main__":
    unittest.main()
