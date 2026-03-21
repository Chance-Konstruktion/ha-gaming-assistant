"""Static contract tests for coordinator core logic."""

from pathlib import Path
import unittest


class TestCoordinatorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("custom_components/gaming_assistant/coordinator.py").read_text(encoding="utf-8")

    def test_has_bounded_image_queue(self):
        self.assertIn("asyncio.Queue(maxsize=2)", self.src)

    def test_has_drop_oldest_strategy(self):
        self.assertIn("if self._image_queue.full()", self.src)
        self.assertIn("self._image_queue.get_nowait()", self.src)

    def test_has_single_worker_loop(self):
        self.assertIn("async def _image_worker_loop", self.src)
        self.assertIn("await self._process_image(client_id, image_bytes)", self.src)

    def test_has_inactivity_and_lock(self):
        self.assertIn("self._process_lock = asyncio.Lock()", self.src)
        self.assertIn("async def _handle_client_inactive", self.src)


if __name__ == "__main__":
    unittest.main()
