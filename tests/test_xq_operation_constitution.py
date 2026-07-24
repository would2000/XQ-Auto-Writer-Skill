from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = PROJECT_ROOT / "docs" / "XQ-OPERATION-CONSTITUTION.md"
AGENTS = PROJECT_ROOT / "AGENTS.md"
SKILL = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "SKILL.md"
README = PROJECT_ROOT / "README.md"


class XQOperationConstitutionTests(unittest.TestCase):
    def test_constitution_is_linked_from_every_persistent_entry_point(self) -> None:
        self.assertTrue(CONSTITUTION.is_file())
        for path in (AGENTS, SKILL, README):
            with self.subTest(path=path.name):
                self.assertIn(
                    "XQ-OPERATION-CONSTITUTION.md",
                    path.read_text(encoding="utf-8"),
                )

    def test_private_content_and_codex_folder_boundaries_are_explicit(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "最高優先持久規則",
            "只允許複製與唯讀讀取",
            "自訂範圍內建立或使用 `CODEX` 專用資料夾",
            "選股中心",
            "策略雷達",
            "本次 manifest",
            "刪除後再驗證不存在",
        ):
            self.assertIn(required, text)

    def test_account_slow_operation_cleanup_and_foreground_rules_are_explicit(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "不得操作 XQ 軟體帳號的登入或登出",
            "不得操作實際證券帳號下單功能",
            "只允許使用 XQ 內建模擬帳號",
            "`WaitGuiThreadIdle`",
            "立即停止後續輸入",
            "使用者指定成果及其必要函數必須保留",
            "最後隱藏 XScript",
        ):
            self.assertIn(required, text)

    def test_all_xq_windows_forbid_coordinate_targeting(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "學習或操作 XQ 的任何視窗",
            "絕對不得使用固定座標、相對座標",
            "依視窗矩形計算的座標",
            "不得傳入 `coords`",
            "沒有穩定選擇器時立即停止並重新校正",
        ):
            self.assertIn(required, constitution)
        for path in (AGENTS, SKILL, README):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("coords", text)

    def test_print_contract_preserves_exact_user_examples_and_requires_confirmation(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        self.assertIn(r'print(file("C:\print\"),date,symbol,close);', text)
        self.assertIn(
            r'print(file("c:\Print\[Symbol].log"),date,symbol,close);',
            text,
        )
        self.assertIn("第一次啟用 Print 檔案輸出前，必須向使用者確認", text)
        self.assertIn("C:\\SysJust\\XQLite", text)


if __name__ == "__main__":
    unittest.main()
