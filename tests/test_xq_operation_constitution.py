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
            "保留本次成果腳本及其 XScript 編輯視窗",
            "任務完成的最後前景一律切回 ChatGPT／Codex",
        ):
            self.assertIn(required, text)

    def test_new_script_codex_creation_uses_type_scoped_storage_path(self) -> None:
        text = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "開啟「新增腳本」",
            "先選取並讀回腳本類型",
            "類型限定的「選擇資料夾」",
            "唯一 `自訂` 根節點",
            "唯一直接子節點 `CODEX`",
            "讀回精確 `自訂/CODEX/`",
            "不得為新建文件改用自繪分類頁籤",
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

    def test_specific_category_requires_manual_switch_and_read_only_verification(self) -> None:
        constitution = CONSTITUTION.read_text(encoding="utf-8")
        for required in (
            "使用者必須先手動切換到指定類別",
            "`xq_category_selector.py`",
            "不得建立臨時空腳本",
            "不得建立臨時空腳本、雙擊文件頁籤、使用座標、密集點擊或推測命令切換",
        ):
            self.assertIn(required, constitution)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("xq_category_selector.py", skill)
        self.assertIn("require the user to switch the requested category manually first", skill)
        self.assertIn("Never create a temporary routing document", skill)
        self.assertNotIn("xq_category_" + "tab_route.py", skill)

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
