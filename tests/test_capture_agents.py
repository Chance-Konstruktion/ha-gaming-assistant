"""
Unit tests for Gaming Assistant capture agents.
Tests game detection, ADB helpers, snapshot fetching, and window title parsing.
"""

import hashlib
import subprocess
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

# ---------------------------------------------------------------------------
# Helpers – create a small JPEG for testing
# ---------------------------------------------------------------------------

def _make_jpeg(width: int = 64, height: int = 64, quality: int = 75) -> bytes:
    """Create a small solid-color JPEG in memory."""
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _make_png_bytes(width: int = 64, height: int = 64) -> bytes:
    """Create a small PNG in memory (simulates ADB screencap -p output)."""
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ===========================================================================
# PC Capture Agent tests
# ===========================================================================

class TestPCAgentDetection(unittest.TestCase):
    """Tests for capture_agent.py game detection helpers."""

    def test_detect_active_game_match(self):
        from worker.capture_agent import detect_active_game
        self.assertEqual(detect_active_game("Elden Ring - v1.09"), "Elden Ring")
        self.assertEqual(detect_active_game("DARK SOULS III"), "Dark Souls")

    def test_detect_active_game_no_match(self):
        from worker.capture_agent import detect_active_game
        self.assertEqual(detect_active_game("Google Chrome"), "")
        self.assertEqual(detect_active_game(""), "")

    def test_known_games_list_not_empty(self):
        from worker.capture_agent import KNOWN_GAMES
        self.assertTrue(len(KNOWN_GAMES) > 0)

    @patch("worker.capture_agent._detect_window_title_x11")
    @patch("worker.capture_agent._detect_window_title_windows")
    def test_detect_window_title_returns_tuple(self, mock_win, mock_x11):
        """detect_window_title() now returns (title, detector_source)."""
        from worker.capture_agent import detect_window_title
        mock_win.return_value = ""
        mock_x11.return_value = "Minecraft 1.20"
        title, detector = detect_window_title()
        self.assertEqual(title, "Minecraft 1.20")
        self.assertEqual(detector, "x11_xprop")

    @patch("worker.capture_agent._detect_window_title_x11")
    @patch("worker.capture_agent._detect_window_title_windows")
    def test_detect_window_title_windows_first(self, mock_win, mock_x11):
        """Windows detection takes priority over X11."""
        from worker.capture_agent import detect_window_title
        mock_win.return_value = "Elden Ring"
        mock_x11.return_value = ""
        title, detector = detect_window_title()
        self.assertEqual(title, "Elden Ring")
        self.assertEqual(detector, "win32gui")

    @patch("worker.capture_agent._detect_window_title_x11")
    @patch("worker.capture_agent._detect_window_title_windows")
    def test_detect_window_title_none(self, mock_win, mock_x11):
        """Returns empty with 'none' detector when nothing found."""
        from worker.capture_agent import detect_window_title
        mock_win.return_value = ""
        mock_x11.return_value = ""
        title, detector = detect_window_title()
        self.assertEqual(title, "")
        self.assertEqual(detector, "none")


# ===========================================================================
# Android Capture Agent tests
# ===========================================================================

class TestAndroidAgent(unittest.TestCase):
    """Tests for capture_agent_android.py."""

    def test_adb_cmd_without_device(self):
        from worker.capture_agent_android import _adb_cmd
        cmd = _adb_cmd(["shell", "echo", "ok"])
        self.assertEqual(cmd, ["adb", "shell", "echo", "ok"])

    def test_adb_cmd_with_device(self):
        from worker.capture_agent_android import _adb_cmd
        cmd = _adb_cmd(["shell", "echo", "ok"], device="192.168.1.42:5555")
        self.assertEqual(cmd, ["adb", "-s", "192.168.1.42:5555", "shell", "echo", "ok"])

    def test_detect_foreground_app_match(self):
        from worker.capture_agent_android import detect_foreground_app
        mock_result = MagicMock()
        mock_result.stdout = "mResumedActivity: ActivityRecord{abc com.mojang.minecraftpe/.MainActivity}"
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            game = detect_foreground_app()
            self.assertEqual(game, "Minecraft")

    def test_detect_foreground_app_no_match(self):
        from worker.capture_agent_android import detect_foreground_app
        mock_result = MagicMock()
        mock_result.stdout = "mResumedActivity: ActivityRecord{abc com.android.launcher/.Main}"
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            game = detect_foreground_app()
            self.assertEqual(game, "")

    def test_capture_android_screen(self):
        from worker.capture_agent_android import capture_android_screen
        png_data = _make_png_bytes(320, 240)
        mock_result = MagicMock()
        mock_result.stdout = png_data
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            jpeg_bytes, frame_hash = capture_android_screen(resize=(64, 64), quality=50)
            self.assertIsInstance(jpeg_bytes, bytes)
            self.assertTrue(len(jpeg_bytes) > 0)
            self.assertEqual(frame_hash, hashlib.md5(jpeg_bytes).hexdigest())


# ===========================================================================
# Android TV Capture Agent tests
# ===========================================================================

class TestAndroidTVAgent(unittest.TestCase):
    """Tests for capture_agent_android_tv.py."""

    def test_adb_cmd_with_device(self):
        from worker.capture_agent_android_tv import _adb_cmd
        cmd = _adb_cmd(["exec-out", "screencap", "-p"], device="192.168.1.100:5555")
        self.assertEqual(
            cmd,
            ["adb", "-s", "192.168.1.100:5555", "exec-out", "screencap", "-p"],
        )

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_check_adb_connection_true(self, mock_run):
        from worker.capture_agent_android_tv import check_adb_connection
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="device\n")
        self.assertTrue(check_adb_connection("tv-device"))

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_check_adb_connection_offline(self, mock_run):
        from worker.capture_agent_android_tv import check_adb_connection
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="offline\n")
        self.assertFalse(check_adb_connection("tv-device"))

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_detect_foreground_package(self, mock_run):
        from worker.capture_agent_android_tv import detect_foreground_package
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout="  mCurrentFocus=Window{abc123 u0 com.retroarch/.browser.mainmenu}\n",
        )
        self.assertEqual(detect_foreground_package("tv"), "com.retroarch")

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_detect_foreground_package_empty(self, mock_run):
        from worker.capture_agent_android_tv import detect_foreground_package
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="nothing useful\n")
        self.assertEqual(detect_foreground_package("tv"), "")

    def test_capture_tv_screen(self):
        from worker.capture_agent_android_tv import capture_tv_screen
        png_data = _make_png_bytes(640, 480)
        mock_result = MagicMock()
        mock_result.stdout = png_data
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            jpeg_bytes, frame_hash = capture_tv_screen("dev", (64, 64), 50)
            self.assertIsInstance(jpeg_bytes, bytes)
            self.assertEqual(frame_hash, hashlib.md5(jpeg_bytes).hexdigest())

    @patch("worker.capture_agent_android_tv.subprocess.run")
    def test_capture_tv_screen_raises_on_failure(self, mock_run):
        from worker.capture_agent_android_tv import capture_tv_screen
        mock_run.return_value = SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"screencap failed"
        )
        with self.assertRaises(RuntimeError):
            capture_tv_screen("tv", (960, 540), 75)


# ===========================================================================
# IP Webcam Capture Agent tests
# ===========================================================================

class TestIPCamAgent(unittest.TestCase):
    """Tests for capture_agent_ipcam.py."""

    def test_fetch_snapshot(self):
        from worker.capture_agent_ipcam import fetch_snapshot
        jpeg_data = _make_jpeg(320, 240)
        mock_response = MagicMock()
        mock_response.content = jpeg_data
        mock_response.raise_for_status = MagicMock()
        with patch("worker.capture_agent_ipcam.requests.get", return_value=mock_response):
            result_bytes, result_hash = fetch_snapshot(
                url="http://192.168.1.42:8080/shot.jpg",
                timeout=5,
                resize=(64, 64),
                quality=50,
                auth_user="",
                auth_password="",
            )
            self.assertIsInstance(result_bytes, bytes)
            self.assertTrue(len(result_bytes) > 0)
            self.assertEqual(result_hash, hashlib.md5(result_bytes).hexdigest())

    def test_fetch_snapshot_with_auth(self):
        from worker.capture_agent_ipcam import fetch_snapshot
        jpeg_data = _make_jpeg(320, 240)
        mock_response = MagicMock()
        mock_response.content = jpeg_data
        mock_response.raise_for_status = MagicMock()
        with patch("worker.capture_agent_ipcam.requests.get", return_value=mock_response) as mock_get:
            fetch_snapshot(
                url="http://192.168.1.42:8080/shot.jpg",
                timeout=5,
                resize=(64, 64),
                quality=50,
                auth_user="admin",
                auth_password="secret",
            )
            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["auth"], ("admin", "secret"))


# ===========================================================================
# HDMI Bridge Capture Agent tests (opencv optional – test via mocks)
# ===========================================================================

class TestBridgeAgent(unittest.TestCase):
    """Tests for capture_agent_bridge.py that don't require OpenCV."""

    def test_topic_cmd_matches(self):
        from worker.capture_agent_bridge import TOPIC_CMD
        self.assertEqual(TOPIC_CMD, "gaming_assistant/command")

    def test_grab_frame_formats_jpeg(self):
        """grab_frame should produce valid JPEG bytes and a stable hash."""
        import numpy as np
        from worker import capture_agent_bridge as bridge

        fake_frame = np.zeros((16, 16, 3), dtype=np.uint8)
        fake_frame[:, :] = (20, 40, 60)  # BGR

        fake_cap = MagicMock()
        fake_cap.read.return_value = (True, fake_frame)

        # Patch cv2 shims – real OpenCV may not be installed during tests.
        fake_cv2 = SimpleNamespace(
            cvtColor=lambda f, code: f[:, :, ::-1],
            COLOR_BGR2RGB=0,
        )
        with patch.object(bridge, "cv2", fake_cv2):
            jpeg_bytes, frame_hash = bridge.grab_frame(
                fake_cap, resize=(8, 8), quality=60
            )
        self.assertIsInstance(jpeg_bytes, bytes)
        self.assertGreater(len(jpeg_bytes), 0)
        self.assertEqual(frame_hash, hashlib.md5(jpeg_bytes).hexdigest())

    def test_grab_frame_raises_on_no_frame(self):
        from worker import capture_agent_bridge as bridge

        fake_cap = MagicMock()
        fake_cap.read.return_value = (False, None)
        with patch.object(bridge, "cv2", SimpleNamespace()):
            with self.assertRaises(RuntimeError):
                bridge.grab_frame(fake_cap, resize=(8, 8), quality=50)

    def test_open_device_raises_without_cv2(self):
        from worker import capture_agent_bridge as bridge
        with patch.object(bridge, "cv2", None):
            with self.assertRaises(RuntimeError):
                bridge.open_device("/dev/video0", 640, 480)


# ===========================================================================
# Cross-agent: MQTT topic format consistency
# ===========================================================================

class TestMQTTTopicFormat(unittest.TestCase):
    """Verify all agents use the same topic naming convention."""

    def test_topic_cmd_consistent(self):
        from worker.capture_agent import TOPIC_CMD as pc_cmd
        from worker.capture_agent_android import TOPIC_CMD as android_cmd
        from worker.capture_agent_android_tv import TOPIC_CMD as tv_cmd
        from worker.capture_agent_ipcam import TOPIC_CMD as ipcam_cmd
        from worker.capture_agent_bridge import TOPIC_CMD as bridge_cmd
        self.assertEqual(pc_cmd, "gaming_assistant/command")
        self.assertEqual(android_cmd, "gaming_assistant/command")
        self.assertEqual(tv_cmd, "gaming_assistant/command")
        self.assertEqual(ipcam_cmd, "gaming_assistant/command")
        self.assertEqual(bridge_cmd, "gaming_assistant/command")


if __name__ == "__main__":
    unittest.main()
