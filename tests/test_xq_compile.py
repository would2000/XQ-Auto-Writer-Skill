from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts" / "xq_compile.py"
SCRIPT_DIRECTORY = SCRIPT_PATH.parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
SPEC = importlib.util.spec_from_file_location("xq_compile", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
xq_compile = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xq_compile
SPEC.loader.exec_module(xq_compile)


class XQCompileTests(unittest.TestCase):
    def test_script_name_with_error_word_is_not_a_compile_failure(self) -> None:
        success_regex = r"編譯成功|0\s*(個|項)?錯誤"
        error_regex = r"編譯錯誤|錯誤|error"
        started = "[18:47:47] Codex錯誤明細擷取驗證 編譯開始"
        self.assertEqual(
            xq_compile.compiler_signals(started, "", success_regex, error_regex),
            (False, False),
        )
        completed = started + "\n[18:47:48] Codex錯誤明細擷取驗證 編譯成功，0項錯誤，0項警告"
        self.assertEqual(
            xq_compile.compiler_signals(completed, "", success_regex, error_regex),
            (True, True),
        )

    def test_stale_output_is_removed_before_classification(self) -> None:
        before = "舊腳本 編譯錯誤"
        current = before + "\n新腳本 編譯開始"
        self.assertEqual(
            xq_compile.compiler_signals(current, before, r"編譯成功", r"編譯錯誤|錯誤"),
            (False, False),
        )

    def test_compiler_source_contract_binds_identity_before_mutation(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--script-name")', source)
        first_identity = source.index("verify_active_document")
        mutation = source.index("replace_editor_text(editor, source, keyboard)")
        last_identity = source.rindex("verify_active_document", 0, mutation)
        self.assertLess(first_identity, last_identity)
        self.assertLess(last_identity, mutation)
        self.assertIn("source_mutated=False", source[first_identity:mutation])
        self.assertIn("source_sha256", source)
        self.assertIn("ensure_window_foreground", source[last_identity:mutation])


if __name__ == "__main__":
    unittest.main()
