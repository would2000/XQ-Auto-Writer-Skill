# 第十一階段：五類實際執行證據與 1.1.0 發布準備

本階段把第十階段的既有 CODEX 文件編譯閘門擴充為可續跑的代表性執行套件。函數不是獨立執行環境，因此由四組函數／caller pair 同時涵蓋函數、指標、選股、警示與自動交易五類；每案都先重新取得函數及 caller 的當次 XQ 編譯成功，再進入對應執行工具。

## 固定案例與安全邊界

版本化案例位於 `.agents/skills/xq-xscript-compiler/references/runtime-evidence-cases-v1.json`，只保存公開測試設定。runner 拒絕案例自行控制 `--config`、`--script-name`、確認旗標、dry-run 或 recovery-status；非乾跑的選股、警示與自動交易案必須明確帶入 `--confirm-historical-backtest`。

執行順序固定為：

1. 唯讀 recovery-status 必須是 `safe_to_start`。
2. 依精確名稱、類型、`自訂/CODEX/` 與來源 SHA-256 重新編譯函數及 caller。
3. 重新開啟 caller 並讀回相同身分。
4. 執行類型專用工具。
5. 再次確認 recovery-status 安全、無 checkpoint。

manifest、JSON、JUnit、Markdown 與原始 XQ 證據只寫入 Git 忽略的 `.xq-auto-writer/runtime-evidence-results/`。completed 案續跑時不重做；failed 案必須明確使用 `--retry-failed`。底層非預期例外也會先保存失敗狀態並清空 `active_case`。

## 2026-08-02 真實 XQ 3.19.03 結果

| Pair | 當次編譯 | 執行結果 | 清理／復原 |
| --- | --- | --- | --- |
| `MyTrendScore` → 指標 | 函數與 caller 成功 | 匯出 99 列 Plot；回傳 5 列樣本 | 原技術線圖頁復原；後置 recovery 安全 |
| `MyBreakoutStrength` → 選股 | 函數與 caller 成功 | 成功商品 50、失敗 0、交易 32 | 唯一 marker 報告已清理；無 checkpoint |
| `MyBullishSignal` → 警示 | 函數與 caller 成功 | 成功商品 1、失敗 0、交易 1 | 唯一 marker 報告已清理；無 checkpoint |
| `CodexV1FlowMomentum` → 自動交易 | 函數與 caller 成功 | 成功商品 1、失敗 0、交易 8 | 唯一 marker 報告已清理；無 checkpoint |

選股與自動交易等待超過一分鐘時只擷取精確 XQ 視窗；畫面分別顯示正常執行或已編譯文件，沒有 Windows 無回應、disabled、`WaitGuiThreadIdle` 或 XQ 錯誤碼。等待期間未補送 Start 或其他輸入。所有成功報告的 `new_report_count` 都是 1 且 `marker_matched` 為 true；XQ 沒有回報錯誤碼，因此公開證明維持 `actual_error_code: null`、`actual_error_code_observed: false`。

自動交易案的 `SetTotalBar(20)` 使預載欄位停用；要求預載 1 筆，但工具讀回 `preload_control_enabled: false` 與 `preload_records_applied: false`，沒有強制寫入停用欄位。

以上是代表案例的軟體流程與執行證據，不是策略績效、獲利能力、安全性或實盤適用性的證明。

## 問題修正

- Windows 子 Python 程序現在強制使用 UTF-8 模式，避免 CP950 多位元字元中的反斜線破壞 JSON 或造成輸出例外。
- 指標加入工具改為只接受唯一 `XS指標／自訂／CODEX／<完整名稱>`，不再錯把腳本視為 `自訂` 的直接子項目。
- 自動交易回測新增 `--script-name`；開啟設定前必須讀回相同的已編譯 CODEX 交易文件。
- 重試會將前次失敗移入 attempts，不讓 completed 案殘留目前錯誤欄位。

## 公開證明與 1.1.0 契約

`xq_runtime_evidence_attestation.py` 只接受私有 manifest，重新核對完整案例集、suite digest、來源 SHA-256 及每案乾淨的後置 recovery。輸出必須位於 `release/`、明確使用 `--confirm-public-attestation`，而且拒絕覆寫。`release/xq-runtime-evidence-v1.json` 不含商品、日期、report／window handle、視窗標題、原始編譯訊息、匯出列或本機路徑。

`release/rc-interface-v3.json` 是從 1.0.0 到 1.1.0 的新凍結契約；已發布的 v1、v2 契約保持不變。開發階段 `VERSION` 仍維持 1.0.0，只有發布 PR 才升版。

## 重現命令

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_runtime_evidence_suite.py `
  --config .xq-auto-writer/xq-ui.json `
  --cases .agents/skills/xq-xscript-compiler/references/runtime-evidence-cases-v1.json `
  --dry-run

python .agents/skills/xq-xscript-compiler/scripts/xq_runtime_evidence_suite.py `
  --config .xq-auto-writer/xq-ui.json `
  --cases .agents/skills/xq-xscript-compiler/references/runtime-evidence-cases-v1.json `
  --confirm-historical-backtest

python .agents/skills/xq-xscript-compiler/scripts/xq_runtime_evidence_attestation.py `
  --manifest .xq-auto-writer/runtime-evidence-results/<run>/manifest.json `
  --cases .agents/skills/xq-xscript-compiler/references/runtime-evidence-cases-v1.json `
  --xq-version 3.19.03 `
  --output release/xq-runtime-evidence-v2.json `
  --confirm-public-attestation
```

新證明必須使用新的檔名及重新審查後的版本；不得覆寫 v1。
