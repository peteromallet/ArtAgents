from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from artagents.core.pack import (
    PackValidationError,
    load_pack_manifest,
    pack_manifest_path,
    qualified_id_pack_id,
)


class PackYamlSchemaTest(unittest.TestCase):
    def _write_pack(self, root: Path, body: str, *, folder: str = "builtin") -> Path:
        pack_root = root / folder
        pack_root.mkdir(parents=True)
        (pack_root / "pack.yaml").write_text(body + ("\n" if not body.endswith("\n") else ""), encoding="utf-8")
        return pack_root

    def test_minimal_manifest_loads_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = self._write_pack(Path(tmp), "id: builtin\n")
            manifest_path = pack_manifest_path(pack_root)
            self.assertIsNotNone(manifest_path)
            pack = load_pack_manifest(manifest_path)
            self.assertEqual(pack.id, "builtin")
            self.assertEqual(pack.name, "builtin")
            self.assertEqual(pack.version, "0.1.0")
            self.assertEqual(pack.metadata, {})
            self.assertEqual(pack.root, pack_root.resolve())

    def test_full_manifest_round_trips_name_version_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = self._write_pack(
                Path(tmp),
                "id: external\nname: External Tools\nversion: 1.2.3\nmetadata: {}\n",
                folder="external",
            )
            pack = load_pack_manifest(pack_manifest_path(pack_root))
            self.assertEqual(pack.id, "external")
            self.assertEqual(pack.name, "External Tools")
            self.assertEqual(pack.version, "1.2.3")
            self.assertEqual(pack.metadata, {})

    def test_missing_id_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = self._write_pack(Path(tmp), "name: builtin\n")
            with self.assertRaisesRegex(PackValidationError, "missing required field pack.id"):
                load_pack_manifest(pack_manifest_path(pack_root))

    def test_pack_id_must_be_safe_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = self._write_pack(Path(tmp), "id: 1invalid\n", folder="invalid")
            with self.assertRaisesRegex(PackValidationError, "safe pack identifier"):
                load_pack_manifest(pack_manifest_path(pack_root))

    def test_pack_id_must_match_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = self._write_pack(Path(tmp), "id: external\n", folder="other")
            with self.assertRaisesRegex(PackValidationError, "must match folder name"):
                load_pack_manifest(pack_manifest_path(pack_root))

    def test_metadata_must_be_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack_root = self._write_pack(Path(tmp), "id: builtin\nmetadata: scalar\n")
            with self.assertRaisesRegex(PackValidationError, "metadata must be an object"):
                load_pack_manifest(pack_manifest_path(pack_root))

    def test_qualified_id_pack_segment_helper_accepts_qualified_ids(self) -> None:
        self.assertEqual(qualified_id_pack_id("builtin.cut"), "builtin")
        self.assertEqual(qualified_id_pack_id("external.vibecomfy.run"), "external")

    def test_qualified_id_pack_segment_helper_rejects_bare_or_blank(self) -> None:
        with self.assertRaisesRegex(PackValidationError, "qualified"):
            qualified_id_pack_id("cut")
        with self.assertRaisesRegex(PackValidationError, "qualified"):
            qualified_id_pack_id("")
        with self.assertRaisesRegex(PackValidationError, "qualified"):
            qualified_id_pack_id("builtin.")


if __name__ == "__main__":
    unittest.main()
