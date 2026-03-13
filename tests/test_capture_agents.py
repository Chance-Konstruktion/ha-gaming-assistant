"""Unit tests for thin-client capture agents."""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from worker import capture_agent_android_tv as tv_agent
from worker import capture_agent_ipcam as ipcam_agent


class TestIpCamAgent(unittest.TestCase):
    def _jpeg_bytes(self) -> bytes:
        img = Image.new("RGB", (32, 24), color=(120, 30, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    @patch("worker.capture_agent_ipcam.requests.get")
    def test_fetch_snapshot_returns_bytes_and_hash(self, mock_get):
        mock_resp = SimpleNamespace(
            content=self._jpeg_bytes(),
            raise_for_status=lambda: None,
        )
        mock_get.return_value = mock_resp

        jpeg_bytes, frame_hash = ipcam_agent.fetch_snapshot(
            url="http://camera.local/shot.jpg",
            timeout=3,
            resize=(64, 36),
            quality=70,
            auth_user="user",
            auth_password="pass",
        )

        self.assertGreater(len(jpeg_bytes), 0)
        self.assertEqual(len(frame_hash), 32)
        mock_get.assert_called_once_with(
            "http://camera.local/shot.jpg",
            timeout=3,
            auth=("user", "pass"),
        )


class TestAndroidTvAgent(unittest.TestCase):
    def test_adb_cmd_with_device(self):
        cmd = tv_agent._adb_cmd(["exec-out", "screencap", "-p"], "192.168.1.50:5555")
        self.assertEqual(
            cmd,
            ["adb", "-s", "192.168.1.50:5555", "exec-out", "screencap", "-p"],
        )

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_check_adb_connection_true(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="device\n")
        self.assertTrue(tv_agent.check_adb_connection("tv-device"))

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_detect_foreground_package_parses_output(self, mock_run):
        mock_run.return_value = SimpleNamespace(
            stdout="mCurrentFocus=Window{abc u0 com.supercell.clashroyale/com.supercell.GameActivity}\n"
        )
        package_name = tv_agent.detect_foreground_package("tv-device")
        self.assertEqual(package_name, "com.supercell.clashroyale")

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_capture_tv_screen_raises_on_failed_screencap(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1, stdout=b"", stderr=b"failed")
        with self.assertRaises(RuntimeError):
            tv_agent.capture_tv_screen("tv-device", (960, 540), 75)


if __name__ == "__main__":
    unittest.main()
