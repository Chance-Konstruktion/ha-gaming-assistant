"""Static contract tests for coordinator core logic.

The per-frame analysis hot path (the bounded image queue, the single worker
loop, and the processing lock) lives in the ``AnalysisPipeline`` collaborator
(``pipeline.py``); the coordinator wires it up and delegates to it. These
contracts assert the safety-relevant shape of that pipeline wherever it lives.
"""

from pathlib import Path
import unittest


class TestCoordinatorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = Path("custom_components/gaming_assistant")
        cls.src = (base / "coordinator.py").read_text(encoding="utf-8")
        cls.pipeline = (base / "pipeline.py").read_text(encoding="utf-8")
        cls.registry_src = (base / "client_registry.py").read_text(encoding="utf-8")

    def test_coordinator_delegates_to_pipeline(self):
        # The coordinator owns the pipeline collaborator and routes frames to it.
        self.assertIn("AnalysisPipeline(self)", self.src)
        self.assertIn("self._pipeline._enqueue_image(", self.src)
        self.assertIn("self._pipeline._process_image(", self.src)

    def test_has_bounded_image_queue(self):
        self.assertIn("asyncio.Queue(maxsize=3)", self.pipeline)

    def test_has_drop_oldest_strategy(self):
        self.assertIn("if self._image_queue.full()", self.pipeline)
        self.assertIn("self._image_queue.get_nowait()", self.pipeline)

    def test_has_single_worker_loop(self):
        self.assertIn("async def _image_worker_loop", self.pipeline)
        self.assertIn("await self._process_image(client_id, image_bytes)", self.pipeline)

    def test_has_inactivity_and_lock(self):
        self.assertIn("self._process_lock = asyncio.Lock()", self.pipeline)
        # Inactivity handling now lives in the ClientRegistry collaborator.
        self.assertIn("async def _handle_inactive", self.registry_src)


if __name__ == "__main__":
    unittest.main()
