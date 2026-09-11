import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from flash_firmware import validate_bundle, validate_partition


class FirmwarePackageTests(unittest.TestCase):
    def test_modified_firmware_is_rejected_before_usb_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = {}
            for name in ("FoloToy-AI-Passport.bin", "partition-table.bin"):
                (root / name).write_bytes(b"test fixture")
                hashes[name] = hashlib.sha256(b"test fixture").hexdigest()
            (root / "manifest.json").write_text(json.dumps({"version": "test", "sha256": hashes}))
            self.assertEqual(validate_bundle(root)["version"], "test")
            (root / "FoloToy-AI-Passport.bin").write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "checksum"):
                validate_bundle(root)

    def test_different_partition_layout_is_rejected(self):
        expected = b"\xaa\x50" + bytes(30)
        validate_partition(expected + b"\xff" * 32, expected)
        for actual in (b"", bytes(32), expected[:-1]):
            with self.assertRaises(ValueError):
                validate_partition(actual, expected)
        with self.assertRaises(ValueError):
            validate_partition(b"", b"")
