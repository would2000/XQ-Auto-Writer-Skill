from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "SKILL.md"
FUNCTION_GUIDE = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references" / "function-guide.md"
AUTOTRADE_GUIDE = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references" / "autotrade-window-guide.md"
README = PROJECT_ROOT / "README.md"
BACKTEST = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts" / "xq_backtest.py"
BOUNDARY_RUNNER = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
    / "xq_function_boundary_runner.py"
)
CASE_V5 = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references"
    / "function-regression" / "cases-v5.json"
)
SPEC = importlib.util.spec_from_file_location(
    "function_data_boundary_knowledge_runner", BOUNDARY_RUNNER
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class FunctionDataBoundaryKnowledgeTests(unittest.TestCase):
    def test_boundary_evidence_is_scoped_and_requires_sentinels(self) -> None:
        function_guide = FUNCTION_GUIDE.read_text(encoding="utf-8")
        for value in (
            "日 `[44]`、週 `[9]`、月 `[2]`",
            "CODEX_BOUNDARY_M3_DEFAULT_USED",
            "CODEX_BOUNDARY_M100_DEFAULT_USED",
            "未出現任何原生資料不足代碼",
            "較短控制",
        ):
            self.assertIn(value, function_guide)

        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("A `GetField(..., Default := value)` comparison must branch", skill)
        self.assertIn("execution-path sentinel", skill)

    def test_settotalbar_disabled_preload_is_explicit(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL, AUTOTRADE_GUIDE, README)
        )
        for value in (
            "preload_control_enabled",
            "preload_records_applied",
            "SetTotalBar(1)",
            "SetBarBack(21, \"D\")",
        ):
            self.assertIn(value, combined)

        source = BACKTEST.read_text(encoding="utf-8")
        self.assertIn("def apply_preload_records", source)
        self.assertIn('"preload_records_applied": enabled', source)

    def test_rendered_boundary_sources_keep_function_contracts(self) -> None:
        _suite, cases = runner.load_case_file(CASE_V5)
        dynamic_case = next(
            case for case in cases
            if case.role == "shortage" and case.access_mode == "dynamic"
            and case.source_frequency == "D"
        )
        fixed_case = next(
            case for case in cases
            if case.role == "shortage" and case.access_mode == "fixed"
            and case.source_frequency == "W"
        )
        default_case = next(
            case for case in cases
            if case.role == "shortage" and case.default_value == -999
            and case.source_frequency == "M"
        )
        dynamic_function, _dynamic_caller = runner.render_sources(
            dynamic_case, "CodexBoundaryDynamicFixture"
        )
        fixed_function, _fixed_caller = runner.render_sources(
            fixed_case, "CodexBoundaryFixedFixture"
        )
        _default_function, default_probe = runner.render_sources(
            default_case, "CodexBoundaryDefaultFixture"
        )

        self.assertIn("SourceSeries(NumericSeries)", dynamic_function)
        self.assertIn("SourceSeries[LookbackBars]", dynamic_function)
        self.assertIn('GetField("Close", "W")[10]', fixed_function)
        self.assertIn("Default := -999", default_probe)
        self.assertIn("CODEX_B5_DAY_M_DEFAULT_SHORTAGE", default_probe)

    def test_fifth_phase_documents_matrix_resume_and_machine_outputs(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL, FUNCTION_GUIDE, AUTOTRADE_GUIDE, README)
        )
        for value in (
            "function-data-boundary-cases-v5.json",
            "caller_index",
            "control_caller_index",
            "expected_preload_state",
            "--resume-manifest",
            "suite digest",
            "JUnit",
            "--require-late-recovery-probe",
            "不重新建檔、編譯或回測",
        ):
            self.assertIn(value, combined)

    def test_sixth_phase_documents_private_immutable_regression_baselines(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL, FUNCTION_GUIDE, AUTOTRADE_GUIDE, README)
        )
        for value in (
            "xq_function_regression.py",
            "--confirm-baseline-update",
            "version_mismatch",
            "affected_pair_ids",
            "--only-pair",
            "runner contract",
            "JSON／JUnit／Markdown",
            "不可覆寫",
            "斷網",
        ):
            self.assertIn(value, combined)

    def test_eighth_phase_documents_batch_gates_and_codex_scope(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL, FUNCTION_GUIDE, AUTOTRADE_GUIDE, README)
        )
        for value in (
            "xq_function_batch_runner.py",
            "safe_to_start",
            "caller-stable child run ID",
            "cooldown",
            "自訂/CODEX/",
            "baseline-v2",
            "缺 pair",
            "Windows wait incident",
        ):
            self.assertIn(value, combined)


if __name__ == "__main__":
    unittest.main()
