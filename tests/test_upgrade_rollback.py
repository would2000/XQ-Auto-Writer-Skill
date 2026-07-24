from __future__ import annotations

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "rehearse_upgrade_rollback.py"
SPEC = importlib.util.spec_from_file_location("rehearse_upgrade_rollback", MODULE_PATH)
assert SPEC and SPEC.loader
rehearsal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rehearsal)


class UpgradeRollbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _skill(self, name: str, marker: str) -> Path:
        root = self.root / name
        for relative in rehearsal.REQUIRED_SKILL_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = f"---\nname: fixture\n---\n{marker}\n" if relative == "SKILL.md" else marker
            path.write_text(content, encoding="utf-8")
        return root

    def test_upgrade_and_rollback_restore_exact_previous_digest(self) -> None:
        previous = self._skill("previous", "old")
        current = self._skill("current", "new")
        result = rehearsal.rehearse_from_directories(
            previous, current, self.root / "workspace"
        )
        self.assertTrue(result["upgrade_verified"])
        self.assertTrue(result["rollback_verified"])
        self.assertEqual(
            result["previous_tree_sha256"], result["restored_tree_sha256"]
        )
        self.assertNotEqual(
            result["previous_tree_sha256"], result["current_tree_sha256"]
        )

    def test_archive_path_traversal_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            data = b"unsafe"
            member = tarfile.TarInfo("../outside.txt")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, "unsafe_archive_member"):
            rehearsal._safe_extract_tar(buffer.getvalue(), self.root / "extract")

    def test_missing_required_file_is_rejected(self) -> None:
        previous = self._skill("previous", "old")
        current = self._skill("current", "new")
        (current / "scripts" / "xq_compile.py").unlink()
        with self.assertRaisesRegex(ValueError, "required_skill_files_missing"):
            rehearsal.rehearse_from_directories(
                previous, current, self.root / "workspace"
            )


if __name__ == "__main__":
    unittest.main()
