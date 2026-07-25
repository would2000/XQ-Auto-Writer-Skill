# 發布候選驗證與維護模式

本文件定義第九階段的發布候選（Release Candidate，RC）流程。這次候選從正式版 `0.3.0` 升級到目標 `1.0.0`；在發布 PR 準備完成前不改動 `VERSION`，也不得建立 tag、推送分支或發布 GitHub Release。

## 安全邊界

- 維護模式狀態只寫入已忽略的 `.xq-auto-writer/release-candidate/maintenance.json`，不得包含帳號、商品、策略、報告內容或私人路徑以外的執行資料。
- `release/rc-interface-v2.json` 是版本化、可公開且不含私人資料的 1.0.0 介面凍結契約，包含五類基礎產生器。任何 CLI 選項或 schema 常數差異都必須先人工審查並建立新版契約；檢查器不會自動覆寫。`release/rc-interface-v1.json` 保留為 0.x 已發布合約。
- 離線 CI 成功不等於真實 XQ 已驗證。XQ UI 驗證必須遵守操作憲法、先讀 recovery-status、只使用 `自訂/CODEX/`、慢速輸入及逐項清理。
- XQ 五類任一類缺少唯一 CODEX 資料夾或可驗證選擇器時，相關真實測試標為 `blocked`，不得改用私人根目錄、座標或既有私人文件。
- CI 與本文件中的演練不得建立 tag、Release、真實下單、故障注入或中斷網路。

## 1. 進入維護模式

先確認工作樹與正式版本，再以明確確認建立本機狀態：

```powershell
git status --short
python scripts/release_maintenance.py status
python scripts/release_maintenance.py enter `
  --reason "phase-9-release-candidate" `
  --current-version 0.3.0 `
  --target-version 1.0.0 `
  --confirm-maintenance-mode
```

重複進入會失敗；損壞或未知 schema 的狀態不會被覆寫。維護模式期間只接受 RC 修正、測試、文件及發布準備，不更新 baseline 或凍結契約，除非另行人工審查並明確建立新版本。

## 2. 驗證凍結介面

```powershell
python scripts/check_release_candidate.py
```

檢查器唯讀驗證：

- `VERSION` 仍為目前正式版，RC 目標是下一個 MINOR；
- 必要入口、文件、schema／runner contract 常數；
- 回測、函數 boundary、批次與 regression 的完整長選項集合；
- CI 已包含 RC 介面檢查、升級／復原演練與完整 Git 歷史。

輸出只有一筆 JSON。`ready: true` 代表離線介面契約吻合，不代表 XQ UI、GitHub Actions 或發布本身已完成。差異時退出碼為 `3`，契約不會被改寫。

## 3. 完整離線回歸

```powershell
python scripts/check_release_metadata.py
python scripts/check_repository_hygiene.py
python -W error::ResourceWarning -m unittest discover -s tests -v
$scripts = Get-ChildItem .agents/skills/xq-xscript-compiler/scripts -Filter *.py
python -m py_compile `
  $scripts.FullName `
  scripts/check_release_metadata.py `
  scripts/check_repository_hygiene.py `
  scripts/check_release_candidate.py `
  scripts/release_maintenance.py `
  scripts/rehearse_upgrade_rollback.py
python scripts/check_release_candidate.py
```

Skill 結構另以目前可用的 Skill validator 驗證。任何一步失敗都維持維護模式，不得宣稱 RC ready。

繁體中文 Windows 的預設 CP950 可能讓 validator 無法讀取 UTF-8 `SKILL.md`；此時以 UTF-8 模式重跑，不要改寫文件編碼：

```powershell
$env:PYTHONUTF8 = "1"
$skillValidator = Join-Path `
  ([Environment]::GetFolderPath("UserProfile")) `
  ".codex\skills\.system\skill-creator\scripts\quick_validate.py"
python $skillValidator `
  .agents\skills\xq-xscript-compiler
Remove-Item Env:\PYTHONUTF8
```

## 4. 升級與復原演練

```powershell
python scripts/rehearse_upgrade_rollback.py --source-tag v0.3.0
```

演練只在臨時目錄執行：從不可變的 `v0.3.0` tag 匯出舊 Skill、建立備份、安裝目前候選樹、驗證必要檔案，再還原舊樹並比較 byte-level SHA-256。路徑穿越、symlink、缺少 tag、缺少必要檔案或 digest 不同均失敗。演練不修改儲存庫、Codex 的實際 Skill 安裝或 XQ。

若升級演練失敗：

1. 保持維護模式，不修改正式 tag。
2. 依 JSON 的 `error` 修復候選內容或補齊 clone 的 tag 歷史。
3. 重跑完整離線回歸與演練。
4. 已發布版本若發現問題，建立新 PATCH；不得移動既有 tag 或替換已發布附件。

## 5. 真實 XQ RC smoke

只有下列條件全部成立才可開始：

1. 離線回歸、介面檢查、演練及 Skill validator 全部成功。
2. XQ 已由使用者登入、桌面解鎖，且沒有登入／帳戶／實單操作需求。
3. 五類測試所需的 `自訂/CODEX/` 都能用非座標選擇器唯一讀回。
4. 唯讀 `xq_backtest.py --recovery-status` 回傳 `safe_to_start`。

真實 RC 先以一組不含真實交易指令的代表 pair 慢速 smoke，再依第八階段批次 runner 逐 pair 執行完整矩陣。任何 Windows 無回應、`WaitGuiThreadIdle`、晚到對話框、timeout、非唯一報告、marker 不符或證據不足，都立即停止輸入並保存 incident；不得因任意新報告清除 checkpoint，也不得推測 XQ 未回報的錯誤碼。

完成後只清理本次 manifest 且經名稱、類型、`自訂/CODEX/` 讀回一致的文件，以及本次報告、暫存與 checkpoint。保留使用者文件；隱藏 XScript、切回 ChatGPT 並驗證前景。

## 6. CI 與發布準備

PR 的 `CI / verify` 必須 Passed。CI 是唯讀 Windows 工作，不接觸 XQ，並執行 metadata、repository hygiene、完整 unittest、Python 編譯、RC 介面及 `v0.3.0` 升級／復原演練。CI 顯示成功時，真實 XQ 欄仍應明列 `Unable to Test`，由人工證據補足。

全部閘門通過後才準備發布 PR：

1. 把 `VERSION` 改為 `1.0.0`。
2. 將 `[Unreleased]` 內容移到 `## [1.0.0] - YYYY-MM-DD`，保留新的空白 `[Unreleased]`。
3. 更新比較連結與 Release Notes，區分離線測試、真實 XQ 已驗證及未驗證項目。
4. 建立 Draft PR；CI Passed 後才合併。
5. 合併後才建立 `v1.0.0` tag 與 Draft Release，核對後發布並執行 `gh release verify`。

本階段不自動執行以上 GitHub 寫入。

## 7. 離開維護模式

只有介面檢查 JSON 的 `status` 為 `success`、`ready` 為 `true`，且版本與維護狀態完全一致時才可離開。將檢查器的單一 JSON 保存為本機證據後執行：

```powershell
python scripts/check_release_candidate.py |
  Set-Content -Encoding utf8 .xq-auto-writer/release-candidate/rc-check.json
python scripts/release_maintenance.py leave `
  --rc-evidence .xq-auto-writer/release-candidate/rc-check.json `
  --confirm-leave-maintenance
```

RC 仍有真實 XQ 阻礙時，即使離線介面吻合也應維持維護模式，直到阻礙排除或使用者明確終止本次候選。
