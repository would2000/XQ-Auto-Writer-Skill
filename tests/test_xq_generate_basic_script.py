from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
    / "xq_generate_basic_script.py"
)
SPEC = importlib.util.spec_from_file_location("xq_generate_basic_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
xq_generate_basic_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xq_generate_basic_script
SPEC.loader.exec_module(xq_generate_basic_script)


class XQGenerateBasicScriptTests(unittest.TestCase):
    def test_each_type_has_a_basic_compiler_oriented_template(self) -> None:
        expected_headers = {
            "indicator": "{@type:indicator}",
            "screener": "{@type:filter}",
            "alert": "{@type:sensor}",
            "function": "{@type:function}",
            "autotrade": "{@type:autotrade}",
        }
        for script_type, header in expected_headers.items():
            with self.subTest(script_type=script_type):
                source = xq_generate_basic_script.render_basic_script(script_type)
                self.assertTrue(source.startswith(header))
                self.assertTrue(source.endswith("\n"))
        function_source = xq_generate_basic_script.render_basic_script("function")
        self.assertIn("retval = Close - Open + Offset;", function_source)

    def test_each_non_function_type_can_render_a_function_caller(self) -> None:
        for script_type in xq_generate_basic_script.FUNCTION_CALLER_TYPES:
            with self.subTest(script_type=script_type):
                source = xq_generate_basic_script.render_basic_script(
                    script_type, "CodexBasicDelta"
                )
                self.assertIn("CodexBasicDelta(0)", source)
        with self.assertRaises(ValueError):
            xq_generate_basic_script.render_basic_script("function", "CodexBasicDelta")

    def test_cli_writes_one_new_source_and_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "basic-indicator.xs"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--script-type",
                    "indicator",
                    "--output",
                    str(output),
                    "--with-function",
                    "--function-name",
                    "CodexBasicDelta",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(payload["status"], "success")
            self.assertFalse(payload["xq_compilation_proven"])
            self.assertEqual(output.read_text(encoding="utf-8"), xq_generate_basic_script.render_basic_script("indicator", "CodexBasicDelta"))

    def test_cli_refuses_existing_output_or_incomplete_function_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "already-exists.xs"
            output.write_text("private content", encoding="utf-8")
            existing = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--script-type", "alert", "--output", str(output)],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(existing.returncode, 3)
            self.assertIn("output_already_exists", json.loads(existing.stdout)["message"])
            self.assertEqual(output.read_text(encoding="utf-8"), "private content")

            incomplete = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--script-type",
                    "alert",
                    "--output",
                    str(Path(temp_dir) / "incomplete.xs"),
                    "--with-function",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(incomplete.returncode, 3)
            self.assertIn("with_function_and_function_name", json.loads(incomplete.stdout)["message"])

    def test_skill_and_docs_distinguish_generation_from_xq_proof(self) -> None:
        skill = (
            PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "SKILL.md"
        ).read_text(encoding="utf-8")
        function_guide = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "function-guide.md"
        ).read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for text in (skill, function_guide, readme):
            self.assertIn("xq_generate_basic_script.py", text)
        self.assertIn("not XQ compilation", skill)
        self.assertIn("不證明編譯或任何執行結果", function_guide)
        self.assertIn("不代表 XQ 編譯", readme)


if __name__ == "__main__":
    unittest.main()
