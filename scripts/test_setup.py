"""Offline setup checks; no network, model downloads, compiler, or GPU."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("experiment_setup", Path(__file__).with_name("setup.py"))
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_manifest_path_cannot_escape(self):
        self.assertEqual(setup.checked_child(self.root, "model/config.json"), self.root / "model/config.json")
        for name in ("../outside", str(self.root.parent / "outside"), "."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                setup.checked_child(self.root, name)

    def test_hash_rejects_same_size_corruption(self):
        path = self.root / "weights.bin"
        path.write_bytes(b"good")
        digest = setup.sha256(path)
        setup.verify_file(path, digest, 4)
        path.write_bytes(b"evil")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            setup.verify_file(path, digest, 4)

    def test_models_do_not_commit_partial_verification(self):
        paths = [self.root / "model", self.root / "draft"]
        specs = []
        for name, path in zip(("model", "draft"), paths):
            path.mkdir()
            (path / "config.json").write_bytes(b"{}")
            specs.append({"repo": f"test/{name}", "revision": "abc", "files": [{
                "name": "config.json", "bytes": 2, "sha256": setup.sha256(path / "config.json")}]})
        (self.root / "models-manifest.json").write_text(json.dumps({"models": specs}))
        (paths[1] / "config.json").write_bytes(b"[]")
        args = argparse.Namespace(model_path=paths[0], drafter_path=paths[1])
        with patch.object(setup, "ROOT", self.root), patch.object(setup, "RUNTIME", self.root / ".runtime"):
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                setup.models(args)
            failed = setup.read_json(self.root / ".runtime/models.json")
            self.assertEqual([False, False], [x["verified"] for x in failed["models"]])
            (paths[1] / "config.json").write_bytes(b"{}")
            setup.models(args)
            receipt = setup.read_json(self.root / ".runtime/models.json")
            self.assertEqual([True, True], [x["verified"] for x in receipt["models"]])

    def test_prepare_checks_pin_patch_and_modified_source(self):
        upstream = self.root / "upstream"
        upstream.mkdir()
        setup.run(["git", "init", upstream], capture_output=True)
        (upstream / "file.txt").write_bytes(b"before\n")
        (upstream / "unchanged.txt").write_bytes(b"keep\n")
        setup.git(upstream, "add", ".")
        setup.git(upstream, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                  "commit", "-m", "fixture", capture=True)
        commit = setup.git(upstream, "rev-parse", "HEAD", capture=True)
        (upstream / "file.txt").write_bytes(b"after\n")
        patch_bytes = subprocess.run(["git", "-C", str(upstream), "diff", "--binary"],
                                     check=True, capture_output=True).stdout
        (self.root / "fixture.patch").write_bytes(patch_bytes)
        manifest = {"upstream": {"url": str(upstream), "commit": commit}, "variants": {"fanout": {
            "patch": "fixture.patch", "patch_sha256": setup.sha256(self.root / "fixture.patch"),
            "source_files": [{"path": "file.txt", "sha256": hashlib.sha256(b"after\n").hexdigest(), "size": 6}]}}}
        with patch.object(setup, "ROOT", self.root), patch.object(setup, "RUNTIME", self.root / ".runtime"):
            source = setup.prepare("fanout", manifest)
            self.assertEqual((source / "file.txt").read_bytes(), b"after\n")
            setup.prepare("fanout", manifest)
            (source / "unchanged.txt").write_bytes(b"edit\n")
            with self.assertRaisesRegex(ValueError, "Unexpected source modifications"):
                setup.prepare("fanout", manifest)
            (source / "file.txt").write_bytes(b"wrong\n")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                setup.prepare("fanout", manifest)


if __name__ == "__main__":
    unittest.main()
