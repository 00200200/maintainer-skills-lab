"""Regression tests for the optional no-change sync cache and native hashing."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools import kit

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


class SyncCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in ("skills", "agents", "grok-bot", "assets"):
            shutil.copytree(ROOT / name, self.root / name)
        self.cache = self.root / kit._SYNC_CACHE_FILE
        self.providers = self.root / "providers"

    def assert_uncached_equivalent(self, **options):
        before = snapshot(self.providers)
        self.assertTrue(kit.sync_providers(self.root, check=True, **options)["up_to_date"])
        expected = kit.provider_files(self.root, **options)
        manifest = json.loads(before.pop(".manifest.json"))
        self.assertEqual(before, expected)
        self.assertEqual(
            manifest["files"], {name: kit.digest(data) for name, data in expected.items()}
        )

    def test_cold_warm_and_check_keep_results_and_public_result_schema(self):
        cold = kit.sync_providers(self.root)
        self.assertTrue(cold["written"])
        before = snapshot(self.root)
        mtimes = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file()}
        with patch.object(kit, "provider_files", side_effect=AssertionError("Warm generation")):
            warm = kit.sync_providers(self.root)
        self.assertEqual(set(warm), set(cold))
        self.assertEqual(warm["written"], [])
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in mtimes})
        with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
            checked = kit.sync_providers(self.root, check=True)
        generate.assert_called_once()
        self.assertTrue(checked["up_to_date"])
        self.assertEqual(snapshot(self.root), before)
        self.assert_uncached_equivalent()

    def test_check_without_cache_never_creates_one(self):
        before = snapshot(self.root)
        with patch.object(
            kit, "_sync_cache_key", side_effect=AssertionError("No cache in --check")
        ):
            self.assertFalse(kit.sync_providers(self.root, check=True)["up_to_date"])
        self.assertFalse(self.cache.exists())
        self.assertEqual(snapshot(self.root), before)

    def test_same_size_same_mtime_edit_is_detected(self):
        resource = self.root / "skills/mkl-humanize/cache-fixture.txt"
        resource.write_bytes(b"old")
        kit.sync_providers(self.root)
        metadata = resource.stat()
        resource.write_bytes(b"new")
        os.utime(resource, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        result = kit.sync_providers(self.root)
        self.assertTrue(result["written"])
        self.assert_uncached_equivalent()

    def test_added_and_deleted_resources_and_agent_content_invalidate(self):
        kit.sync_providers(self.root)
        resource = self.root / "skills/mkl-humanize/added.txt"
        for action in (lambda: resource.write_bytes(b"added"), resource.unlink):
            action()
            with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
                kit.sync_providers(self.root)
            generate.assert_called_once()
            self.assert_uncached_equivalent()
        agent = next((self.root / "agents").glob("*.toml"))
        agent.write_bytes(agent.read_bytes() + b"\n# Source content changed\n")
        with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
            kit.sync_providers(self.root)
        generate.assert_called_once()

    def test_parameters_and_generator_source_invalidate(self):
        kit.sync_providers(self.root)
        for options in [{"minify": True}, {"mode": "lazy"}, {"minify": False, "mode": "full"}]:
            with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
                kit.sync_providers(self.root, **options)
            generate.assert_called_once()
            self.assert_uncached_equivalent(**options)
        implementation = self.root / "generator.py"
        implementation.write_text("# Generator version 1\n", encoding="utf-8")
        with patch.object(kit, "__file__", str(implementation)):
            kit.sync_providers(self.root)
            implementation.write_text("# Generator version 2\n", encoding="utf-8")
            with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
                kit.sync_providers(self.root)
            generate.assert_called_once()

    def test_assets_and_recipe_edits_invalidate(self):
        kit.sync_providers(self.root)
        for directory in ("assets", "grok-bot"):
            path = next(p for p in (self.root / directory).rglob("*") if p.is_file())
            path.write_bytes(path.read_bytes() + b"\nAdditional source note.\n")
            with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
                kit.sync_providers(self.root)
            generate.assert_called_once()
            self.assert_uncached_equivalent()

    def test_missing_outputs_and_manifest_force_generation(self):
        kit.sync_providers(self.root)
        for relative in ["README.md", ".manifest.json"]:
            (self.providers / relative).unlink()
            self.assertFalse(kit.sync_providers(self.root, check=True)["up_to_date"])
            with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
                result = kit.sync_providers(self.root)
            generate.assert_called_once()
            self.assertTrue(result["manifest_changed"] or result["written"])
            self.assert_uncached_equivalent()

    def test_warm_cache_never_overwrites_local_edits(self):
        kit.sync_providers(self.root)
        path = self.providers / "README.md"
        path.write_text("User edits", encoding="utf-8")
        before = snapshot(self.root)
        for check in [True, False]:
            with (
                self.subTest(check=check),
                self.assertRaisesRegex(kit.KitError, "Edited or unmanaged"),
            ):
                kit.sync_providers(self.root, check=check)
            self.assertEqual(snapshot(self.root), before)

    def test_deleted_source_obsolete_owned_exports_are_removed(self):
        kit.sync_providers(self.root)
        shutil.rmtree(self.root / "skills/mkl-write-tutorial")
        self.assertFalse(kit.sync_providers(self.root, check=True)["up_to_date"])
        result = kit.sync_providers(self.root)
        self.assertTrue(result["removed"])
        self.assert_uncached_equivalent()

    def test_corrupt_cache_is_a_miss_and_check_ignores_it(self):
        kit.sync_providers(self.root)
        for corrupt in [b"{", b"[]", b"{}", b"\xff", b"[" * 2000, b"x" * 5000]:
            self.cache.write_bytes(corrupt)
            before = snapshot(self.root)
            self.assertTrue(kit.sync_providers(self.root, check=True)["up_to_date"])
            self.assertEqual(snapshot(self.root), before)
            with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
                kit.sync_providers(self.root)
            generate.assert_called_once()
        state = json.loads(self.cache.read_text())
        state["manifest_sha256"] = "0" * 64
        self.cache.write_text(json.dumps(state))
        with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
            kit.sync_providers(self.root)
        generate.assert_called_once()

    def test_schema_algorithm_and_manifest_changes_invalidate(self):
        def sha(data):
            return hashlib.sha256(data).hexdigest()

        with patch.object(kit, "_sync_hash_backend", return_value=("sha256", sha)):
            kit.sync_providers(self.root)
        before = snapshot(self.providers)
        with (
            patch.object(kit, "_sync_hash_backend", return_value=("blake3", sha)),
            patch.object(kit, "provider_files", wraps=kit.provider_files) as generate,
        ):
            kit.sync_providers(self.root)
        generate.assert_called_once()
        self.assertEqual(snapshot(self.providers), before)
        state = json.loads(self.cache.read_text())
        state["schema_version"] = 999
        self.cache.write_text(json.dumps(state))
        with patch.object(kit, "provider_files", wraps=kit.provider_files) as generate:
            kit.sync_providers(self.root)
        generate.assert_called_once()
        manifest = self.providers / ".manifest.json"
        owned = json.loads(manifest.read_text())
        owned["files"]["groq/README.md"] = kit.digest(b"old owned output")
        manifest.write_text(json.dumps(owned))
        obsolete = self.providers / "groq/README.md"
        obsolete.parent.mkdir()
        obsolete.write_bytes(b"old owned output")
        result = kit.sync_providers(self.root)
        self.assertIn("groq/README.md", result["removed"])
        self.assert_uncached_equivalent()

    def test_warm_hits_still_validate_library(self):
        kit.sync_providers(self.root)
        with patch.object(kit, "load_library", side_effect=kit.KitError("Validation changed")):
            with self.assertRaisesRegex(kit.KitError, "Validation changed"):
                kit.sync_providers(self.root)

    def test_unsafe_cache_symlink_is_not_followed_or_replaced(self):
        target = self.root / "outside.txt"
        target.write_text("Keep", encoding="utf-8")
        self.cache.parent.mkdir()
        try:
            self.cache.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        kit.sync_providers(self.root)
        self.assertTrue(self.cache.is_symlink())
        self.assertEqual(target.read_text(), "Keep")

    def test_cache_write_failure_and_non_file_cache_do_not_break_sync(self):
        original = kit.atomic_write

        def fail_cache(path, data):
            if path == self.cache:
                raise PermissionError("Cache is not writable")
            return original(path, data)

        with patch.object(kit, "atomic_write", side_effect=fail_cache):
            self.assertTrue(kit.sync_providers(self.root)["up_to_date"])
        self.assertFalse(self.cache.exists())
        self.cache.mkdir(parents=True)
        self.assertTrue(kit.sync_providers(self.root)["up_to_date"])
        self.assertTrue(self.cache.is_dir())
        self.assert_uncached_equivalent()

    def test_native_hash_failures_are_not_silently_replaced_with_sha256(self):
        native = types.ModuleType("msl_core")
        native.blake3_hash = Mock(side_effect=RuntimeError("Native hashing failed"))
        with patch.dict(sys.modules, {"msl_core": native}):
            with self.assertRaisesRegex(RuntimeError, "Native hashing failed"):
                kit.sync_providers(self.root)

    def test_no_native_extension_and_older_extension_keep_sha256_manifest(self):
        for native in [None, types.ModuleType("msl_core")]:
            with self.subTest(native=native), patch.dict(sys.modules, {"msl_core": native}):
                algorithm, hash_bytes = kit._sync_hash_backend()
                self.assertEqual(algorithm, "sha256")
                self.assertEqual(hash_bytes(b"a\r\nb"), hashlib.sha256(b"a\r\nb").hexdigest())
        with patch.object(
            kit,
            "_sync_hash_backend",
            return_value=("sha256", lambda b: hashlib.sha256(b).hexdigest()),
        ):
            kit.sync_providers(self.root)
            self.assert_uncached_equivalent()


try:
    import msl_core
except ModuleNotFoundError as error:
    if error.name != "msl_core":
        raise
    msl_core = None


@unittest.skipUnless(msl_core is not None and "blake3_hash" in vars(msl_core), "Requires native M5")
class NativeHashTests(unittest.TestCase):
    def test_known_vectors_and_exact_byte_semantics(self):
        self.assertEqual(
            msl_core.blake3_hash(b""),
            "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262",
        )
        self.assertEqual(
            msl_core.blake3_hash(b"abc"),
            "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85",
        )
        self.assertNotEqual(msl_core.blake3_hash(b"a\r\nb"), msl_core.blake3_hash(b"a\nb"))
        data = bytes(range(256)) * 100
        self.assertEqual(msl_core.blake3_hash(data), msl_core.blake3_hash(data))
        with self.assertRaises(TypeError):
            msl_core.blake3_hash("text")


if __name__ == "__main__":
    unittest.main()
