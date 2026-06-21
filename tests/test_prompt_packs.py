"""Validation tests for prompt pack loader and JSON structure."""

import importlib
import json
import unittest
import io
import zipfile
import tempfile
import hashlib
from pathlib import Path


PACK_DIR = Path(__file__).parent.parent / "custom_components" / "gaming_assistant" / "prompt_packs"

REQUIRED_FIELDS = {"id", "name", "keywords", "system_prompt"}
OPTIONAL_FIELDS = {"spoiler_defaults", "additional_context", "state_schema"}
VALID_SPOILER_CATEGORIES = {"story", "items", "enemies", "bosses", "locations", "lore", "mechanics"}
VALID_SPOILER_LEVELS = {"none", "low", "medium", "high"}


def _import_prompt_packs():
    """Import prompt_packs module directly, bypassing integration __init__."""
    spec = importlib.util.spec_from_file_location(
        "prompt_packs",
        PACK_DIR / "__init__.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPromptPackValidation(unittest.TestCase):
    """Validate prompt pack JSON files have correct structure."""

    def _get_pack_files(self) -> list[Path]:
        """Return all non-template pack files from bundled directory."""
        return [
            f for f in PACK_DIR.glob("*.json")
            if not f.name.startswith("_") and f.name != "pack_manifest.json"
        ]

    def test_packs_directory_exists(self):
        self.assertTrue(PACK_DIR.exists(), f"Pack directory not found: {PACK_DIR}")

    def test_template_exists(self):
        """The _template.json should always be bundled."""
        template = PACK_DIR / "_template.json"
        self.assertTrue(template.exists(), "_template.json missing from prompt_packs")

    def test_template_has_required_fields(self):
        template = PACK_DIR / "_template.json"
        data = json.loads(template.read_text(encoding="utf-8"))
        for field in REQUIRED_FIELDS:
            self.assertIn(field, data, f"_template.json missing '{field}'")

    def test_all_bundled_packs_valid_json(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                text = path.read_text(encoding="utf-8")
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    self.fail(f"{path.name} is invalid JSON: {e}")
                self.assertIsInstance(data, dict, f"{path.name} root is not a dict")

    def test_all_bundled_packs_have_required_fields(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                for field in REQUIRED_FIELDS:
                    self.assertIn(field, data, f"{path.name} missing '{field}'")

    def test_spoiler_defaults_valid(self):
        for path in self._get_pack_files():
            with self.subTest(pack=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                spoilers = data.get("spoiler_defaults", {})
                if spoilers:
                    for cat, level in spoilers.items():
                        self.assertIn(
                            cat, VALID_SPOILER_CATEGORIES,
                            f"{path.name} invalid spoiler category: {cat}",
                        )
                        self.assertIn(
                            level, VALID_SPOILER_LEVELS,
                            f"{path.name} invalid spoiler level for {cat}: {level}",
                        )


class TestPromptPackLoader(unittest.TestCase):
    """Test the PromptPackLoader class."""

    @classmethod
    def setUpClass(cls):
        cls._mod = _import_prompt_packs()

    def _make_loader(self, cache_dir=None):
        return self._mod.PromptPackLoader(cache_dir=cache_dir)

    def test_loader_initializes_empty(self):
        loader = self._make_loader()
        self.assertFalse(loader._loaded)
        self.assertEqual(len(loader._packs), 0)

    def test_loader_with_cache_dir(self):
        loader = self._make_loader(cache_dir=Path("/tmp/test_packs"))
        self.assertEqual(loader._cache_dir, Path("/tmp/test_packs"))

    def test_load_all_sets_loaded_flag(self):
        loader = self._make_loader()
        loader.load_all()
        self.assertTrue(loader._loaded)

    def test_load_all_idempotent(self):
        loader = self._make_loader()
        packs1 = loader.load_all()
        packs2 = loader.load_all()
        self.assertIs(packs1, packs2)

    def test_reload_clears_and_reloads(self):
        loader = self._make_loader()
        loader.load_all()
        self.assertTrue(loader._loaded)
        loader.reload()
        self.assertTrue(loader._loaded)

    def test_find_by_keyword_returns_none_for_unknown(self):
        loader = self._make_loader()
        result = loader.find_by_keyword("nonexistent_game_xyz")
        self.assertIsNone(result)

    def test_get_returns_none_for_unknown(self):
        loader = self._make_loader()
        result = loader.get("nonexistent_pack_id")
        self.assertIsNone(result)

    def test_loader_loads_from_cache_dir(self):
        """Packs in cache_dir take priority over bundled packs."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            pack = {
                "id": "test_game",
                "name": "Test Game",
                "keywords": ["test"],
                "system_prompt": "You are a test coach.",
            }
            (cache_dir / "test_game.json").write_text(
                json.dumps(pack), encoding="utf-8"
            )
            loader = self._make_loader(cache_dir=cache_dir)
            loader.load_all()
            result = loader.get("test_game")
            self.assertIsNotNone(result)
            self.assertEqual(result["name"], "Test Game")

    def test_find_by_keyword_matches(self):
        """find_by_keyword returns a pack when keyword matches."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            pack = {
                "id": "test_game",
                "name": "Test Game",
                "keywords": ["test game", "testgame"],
                "system_prompt": "You are a test coach.",
            }
            (cache_dir / "test_game.json").write_text(
                json.dumps(pack), encoding="utf-8"
            )
            loader = self._make_loader(cache_dir=cache_dir)
            result = loader.find_by_keyword("Playing Test Game now")
            self.assertIsNotNone(result)
            self.assertEqual(result["id"], "test_game")

    def test_cache_dir_priority_over_bundled(self):
        """Cached pack overrides a bundled pack with the same ID."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            pack = {
                "id": "override_test",
                "name": "Cached Version",
                "keywords": ["override"],
                "system_prompt": "Cached version of the pack.",
            }
            (cache_dir / "override_test.json").write_text(
                json.dumps(pack), encoding="utf-8"
            )
            loader = self._make_loader(cache_dir=cache_dir)
            loader.load_all()
            result = loader.get("override_test")
            self.assertEqual(result["name"], "Cached Version")

    def test_non_utf8_pack_is_skipped_not_fatal(self):
        """A mis-encoded (Latin-1) pack must be skipped, not abort the load.

        Regression: ``UnicodeDecodeError`` is a ``ValueError``, not an
        ``OSError``/``JSONDecodeError``, so a single Latin-1 file in the cache
        used to raise straight through ``load_all`` and kill every pack.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            # Valid UTF-8 pack that must still load despite the bad neighbour.
            good = {
                "id": "good_game",
                "name": "Good Game",
                "keywords": ["good"],
                "system_prompt": "You are a coach.",
            }
            (cache_dir / "good_game.json").write_text(
                json.dumps(good), encoding="utf-8"
            )
            # Latin-1 encoded German pack: 0xDC ('Ü') is not valid UTF-8.
            (cache_dir / "bad_encoding.json").write_bytes(
                '{"id": "bad", "name": "FÜR", "keywords": ["x"], '
                '"system_prompt": "Drücke X."}'.encode("latin-1")
            )
            loader = self._make_loader(cache_dir=cache_dir)
            # Must not raise.
            loader.load_all()
            self.assertIsNotNone(loader.get("good_game"))
            self.assertIn("bad_encoding.json", loader.invalid_packs)


class TestPackValidation(unittest.TestCase):
    """Test the explicit validate_pack function against fixture files."""

    FIXTURE_DIR = Path(__file__).parent / "fixtures" / "prompt_packs"

    @classmethod
    def setUpClass(cls):
        cls._mod = _import_prompt_packs()

    def _load_fixture(self, name: str) -> dict:
        return json.loads((self.FIXTURE_DIR / name).read_text(encoding="utf-8"))

    def test_valid_minimal_pack_passes(self):
        errors = self._mod.validate_pack(self._load_fixture("valid_minimal.json"))
        self.assertEqual(errors, [])

    def test_valid_full_pack_passes(self):
        errors = self._mod.validate_pack(self._load_fixture("valid_full.json"))
        self.assertEqual(errors, [])

    def test_bad_id_is_rejected(self):
        errors = self._mod.validate_pack(self._load_fixture("invalid_bad_id.json"))
        self.assertTrue(any("id" in e for e in errors), errors)

    def test_missing_required_fields_rejected(self):
        errors = self._mod.validate_pack(
            self._load_fixture("invalid_missing_fields.json")
        )
        joined = " ".join(errors)
        self.assertIn("keywords", joined)
        self.assertIn("system_prompt", joined)

    def test_bad_version_rejected(self):
        errors = self._mod.validate_pack({
            "id": "x", "name": "x", "keywords": ["x"],
            "system_prompt": "x", "version": "not-a-version",
        })
        self.assertTrue(any("version" in e for e in errors), errors)

    def test_loader_skips_invalid_fixture(self):
        import tempfile
        import shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            # Copy only the invalid ID fixture into the cache dir.
            shutil.copy(self.FIXTURE_DIR / "invalid_bad_id.json", cache_dir)
            loader = self._mod.PromptPackLoader(cache_dir=cache_dir)
            loader.load_all()
            # The invalid one must not appear in loaded packs.
            for pack in loader._packs.values():
                self.assertNotEqual(pack.get("name"), "Bad ID")
            self.assertIn("invalid_bad_id.json", loader.invalid_packs)

    def test_optional_field_issue_loads_with_warning(self):
        # A pack with valid required fields but a bad OPTIONAL field (version)
        # must still load — recorded as an advisory, not dropped.
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            (cache_dir / "x.json").write_text(json.dumps({
                "id": "x", "name": "X", "keywords": ["x"],
                "system_prompt": "coach", "version": "2026-04-14",
            }), encoding="utf-8")
            loader = self._mod.PromptPackLoader(cache_dir=cache_dir)
            loader.load_all()
            self.assertIn("x", loader._packs)
            self.assertNotIn("x.json", loader.invalid_packs)
            self.assertIn("x.json", loader.pack_warnings)

    def test_manifest_available(self):
        loader = self._mod.PromptPackLoader()
        manifest = loader.manifest
        self.assertEqual(manifest.get("manifest_version"), 1)
        self.assertIn("pack_schema", manifest)


class TestDownloadConfig(unittest.TestCase):
    """Test download configuration."""

    def test_repo_url_points_to_correct_repo(self):
        mod = _import_prompt_packs()
        self.assertIn("ha-gaming-assistant-prompts", mod.PROMPTS_REPO_URL)
        self.assertIn("main.zip", mod.PROMPTS_REPO_URL)

    def test_download_function_exists(self):
        mod = _import_prompt_packs()
        self.assertTrue(callable(mod.download_prompt_packs))

    def test_pin_ref_constant_drives_url(self):
        mod = _import_prompt_packs()
        self.assertTrue(hasattr(mod, "PROMPTS_REPO_REF"))
        # The download URL is built from the pinnable ref.
        self.assertIn(mod.PROMPTS_REPO_REF + ".zip", mod.PROMPTS_REPO_URL)


def _make_repo_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestRemotePackVerification(unittest.TestCase):
    """Checksum verification of downloaded packs (extract_prompt_packs)."""

    def setUp(self):
        self.mod = _import_prompt_packs()
        self.tmp = Path(tempfile.mkdtemp())

    def _pack(self, pid: str) -> bytes:
        return json.dumps({
            "id": pid, "name": pid, "keywords": [pid],
            "system_prompt": "x", "language": "de",
        }).encode("utf-8")

    def test_verified_written_tampered_and_unlisted_skipped(self):
        good = self._pack("good")
        tampered = self._pack("tampered")
        unlisted = self._pack("unlisted")
        manifest = {
            "algorithm": "sha256",
            "packs": {
                "base/good.json": hashlib.sha256(good).hexdigest(),
                # Hash of different bytes -> the shipped file must be rejected.
                "base/tampered.json": hashlib.sha256(b"original").hexdigest(),
            },
        }
        zip_bytes = _make_repo_zip({
            "repo-main/checksums.json": json.dumps(manifest).encode("utf-8"),
            "repo-main/packs/base/good.json": good,
            "repo-main/packs/base/tampered.json": tampered,
            "repo-main/packs/base/unlisted.json": unlisted,
        })
        written = self.mod.extract_prompt_packs(zip_bytes, self.tmp)
        self.assertEqual(written, 1)
        self.assertTrue((self.tmp / "base" / "good.json").exists())
        self.assertFalse((self.tmp / "base" / "tampered.json").exists())
        self.assertFalse((self.tmp / "base" / "unlisted.json").exists())

    def test_missing_manifest_writes_unverified(self):
        good = self._pack("good")
        zip_bytes = _make_repo_zip({"repo-main/packs/base/good.json": good})
        written = self.mod.extract_prompt_packs(zip_bytes, self.tmp)
        self.assertEqual(written, 1)
        self.assertTrue((self.tmp / "base" / "good.json").exists())

    def test_template_and_non_json_ignored(self):
        good = self._pack("good")
        manifest = {"algorithm": "sha256",
                    "packs": {"base/good.json": hashlib.sha256(good).hexdigest()}}
        zip_bytes = _make_repo_zip({
            "repo-main/checksums.json": json.dumps(manifest).encode("utf-8"),
            "repo-main/packs/base/good.json": good,
            "repo-main/packs/_template.json": self._pack("tmpl"),
            "repo-main/README.md": b"# readme",
        })
        written = self.mod.extract_prompt_packs(zip_bytes, self.tmp)
        self.assertEqual(written, 1)
        self.assertFalse((self.tmp / "_template.json").exists())


if __name__ == "__main__":
    unittest.main()
