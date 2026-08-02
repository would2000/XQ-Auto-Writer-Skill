import argparse
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".agents/skills/xq-xscript-compiler/scripts/xq_screener_pipeline.py"
SPEC = importlib.util.spec_from_file_location("xq_screener_pipeline", MODULE_PATH)
xq_screener_pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(xq_screener_pipeline)


def child(status="success", returncode=0, **extra):
    return {
        "script": "child.py",
        "returncode": returncode,
        "payload": {"status": status, "message": status, **extra},
        "stderr": "",
    }


class ScreenerPipelineTests(unittest.TestCase):
    def make_inputs(self, directory):
        root = Path(directory)
        config = root / "xq-ui.json"
        source = root / "screen.xs"
        config.write_text('{"calibrated": true}', encoding="utf-8")
        source.write_text("{@type:filter}\nret = 1;\n", encoding="utf-8")
        return config, source

    def args(self, config, source):
        return argparse.Namespace(
            config=config,
            source=source,
            script_name="PipelineScript",
            strategy_name="Pipeline Strategy",
            universe="台灣五十成分股(系統)",
            direction="unspecified",
            timeout_seconds=30.0,
            stop_recovery_seconds=10.0,
            native_export=None,
            native_error_export=None,
            max_rows=2,
            max_error_rows=2,
        )

    def run_main(self, argv, results, baseline=None, cleanup=None):
        output = io.StringIO()
        with (
            patch.object(xq_screener_pipeline, "parse_args", return_value=argv),
            patch.object(
                xq_screener_pipeline,
                "xscript_windows",
                return_value=[] if baseline is None else baseline,
            ),
            patch.object(
                xq_screener_pipeline,
                "run_json_tool",
                side_effect=results,
            ) as runner,
            patch.object(
                xq_screener_pipeline,
                "close_pipeline_editor",
                return_value={"attempted": True, "closed": True}
                if cleanup is None
                else cleanup,
            ) as closer,
            redirect_stdout(output),
        ):
            returncode = xq_screener_pipeline.main()
        return returncode, json.loads(output.getvalue()), runner, closer

    def test_validation_rejects_bad_name_before_touching_xq(self):
        with tempfile.TemporaryDirectory() as directory:
            config, source = self.make_inputs(directory)
            args = self.args(config, source)
            args.script_name = "bad name"
            with patch.object(xq_screener_pipeline, "xscript_windows") as windows:
                with self.assertRaises(ValueError):
                    xq_screener_pipeline.validate_inputs(args)
                windows.assert_not_called()

    def test_json_child_parser_rejects_multiple_objects(self):
        completed = subprocess.CompletedProcess(
            ["python"], 0, stdout='{"status":"success"}\n{"status":"success"}\n', stderr=""
        )
        with patch.object(xq_screener_pipeline.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "exactly one valid JSON object"):
                xq_screener_pipeline.run_json_tool("child.py", [], 1)

    def test_pipeline_preserves_screener_partial_and_cancelled_statuses(self):
        for status in ("partial_failure", "cancelled"):
            with self.subTest(status=status):
                with self.assertRaises(xq_screener_pipeline.StageError) as captured:
                    xq_screener_pipeline.require_success(child(status, 2), "capture")
                self.assertEqual(captured.exception.status, status)

    def test_compile_error_stops_before_strategy_and_keeps_editor_open(self):
        with tempfile.TemporaryDirectory() as directory:
            config, source = self.make_inputs(directory)
            returncode, payload, runner, closer = self.run_main(
                self.args(config, source),
                [child(), child(), child("compile_error", 2, compiler_output="line 2 error")],
            )
        self.assertEqual(returncode, 2)
        self.assertEqual(payload["status"], "compile_error")
        self.assertEqual(payload["failed_stage"], "compile_script")
        self.assertEqual(payload["stage_result"]["compiler_output"], "line 2 error")
        self.assertIn("prepare", payload["completed_stages"])
        self.assertIn("preflight", payload["completed_stages"])
        self.assertEqual(runner.call_count, 3)
        closer.assert_not_called()
        self.assertEqual(payload["editor_cleanup"]["reason"], "not_created")

    def test_success_runs_prepare_compile_and_capture_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            config, source = self.make_inputs(directory)
            returncode, payload, runner, closer = self.run_main(
                self.args(config, source),
                [
                    child(),
                    child(active_title="XScript - [PipelineScript] (選股)"),
                    child(compiler_output="0 errors, 0 warnings"),
                    child(matched_count=3, returned_count=2, rows=[{"商品":"A"}, {"商品":"B"}]),
                ],
                baseline=[{"handle": 77, "title": "XScript - [UserDoc]"}],
            )
        self.assertEqual(returncode, 0)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["matched_count"], 3)
        self.assertEqual([call.args[0] for call in runner.call_args_list], [
            "xq_prepare_script.py", "xq_prepare_script.py", "xq_compile.py", "xq_screener.py"
        ])
        preflight_args = runner.call_args_list[0].args[1]
        prepare_args = runner.call_args_list[1].args[1]
        compile_args = runner.call_args_list[2].args[1]
        screener_args = runner.call_args_list[3].args[1]
        self.assertIn("--dry-run", preflight_args)
        self.assertIn("screener", prepare_args)
        self.assertIn("screener", compile_args)
        self.assertEqual(compile_args[compile_args.index("--script-name") + 1], "PipelineScript")
        self.assertIn("--create-strategy", screener_args)
        self.assertIn("PipelineScript", screener_args)
        closer.assert_called_once_with({77}, "PipelineScript")
        self.assertTrue(payload["editor_cleanup"]["closed"])

    def test_screener_failure_propagates_and_closes_only_compiled_new_editor(self):
        with tempfile.TemporaryDirectory() as directory:
            config, source = self.make_inputs(directory)
            returncode, payload, runner, closer = self.run_main(
                self.args(config, source),
                [child(), child(), child(), child("failure", 2, strategy_created=False)],
            )
        self.assertEqual(returncode, 2)
        self.assertEqual(payload["status"], "failure")
        self.assertEqual(payload["failed_stage"], "create_run_capture")
        self.assertEqual(runner.call_count, 4)
        closer.assert_called_once()

    def test_transient_script_search_failure_gets_one_safe_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            config, source = self.make_inputs(directory)
            returncode, payload, runner, _ = self.run_main(
                self.args(config, source),
                [
                    child(),
                    child(),
                    child(),
                    child(
                        "automation_error",
                        3,
                        strategy_created=False,
                        message="XQ search control 17053 did not clear for the no-match sentinel",
                    ),
                    child(matched_count=0, returned_count=0, rows=[]),
                ],
            )
        self.assertEqual(returncode, 0)
        self.assertEqual(payload["screener_attempts"], 2)
        self.assertEqual(runner.call_count, 5)

    def test_cleanup_preserves_preexisting_and_nonmatching_windows(self):
        existing = Mock(handle=10)
        existing.is_visible.return_value = True
        existing.window_text.return_value = "XScript 編輯器 - [PipelineScript(選股)]"
        other = Mock(handle=11)
        other.is_visible.return_value = True
        other.window_text.return_value = "XScript - [OtherDoc] (選股)"
        desktop = Mock()
        desktop.windows.return_value = [existing, other]
        with patch.dict("sys.modules", {"pywinauto": Mock(Desktop=Mock(return_value=desktop))}):
            result = xq_screener_pipeline.close_pipeline_editor({10}, "PipelineScript")
        self.assertFalse(result["closed"])
        existing.close.assert_not_called()
        other.close.assert_not_called()

    def test_cleanup_closes_exact_new_editor_with_xq_type_suffix(self):
        editor = Mock(handle=11)
        editor.is_visible.return_value = True
        editor.window_text.return_value = "XScript 編輯器 - [PipelineScript(選股)]"
        desktop = Mock()
        desktop.windows.return_value = [editor]
        pywinauto = Mock(Desktop=Mock(return_value=desktop))
        win32gui = Mock(
            IsWindow=Mock(return_value=True), IsWindowVisible=Mock(return_value=False)
        )
        with patch.dict("sys.modules", {"pywinauto": pywinauto, "win32gui": win32gui}):
            result = xq_screener_pipeline.close_pipeline_editor(set(), "PipelineScript")
        self.assertTrue(result["closed"])
        self.assertEqual(result["disposition"], "hidden")
        editor.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
