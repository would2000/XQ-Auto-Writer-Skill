# 第十階段：五類端到端整合與 1.0.0 封板

本階段補上既有 `自訂/CODEX/` 文件從精確開啟、當次編譯到下游工具交接的共同安全閘門。它不修改 `release/rc-interface-v2.json`，也不代表已正式發布 1.0.0。

## 實作結果

- `xq_compile.py` 可選擇以 `--script-name` 綁定活動文件；來源寫入前與編譯前都驗證名稱、類型、`自訂/CODEX/` 與前景，並回報 UTF-8 來源 SHA-256。
- `xq_existing_script_pipeline.py` 只開啟完整名稱唯一的 CODEX 文件。函數先編譯、caller 後編譯；任一失敗即停止，不進入下游。
- 指標、選股、警示與交易的下游工具沿用各自既有的 recovery、marker、商品範圍、設定讀回及清理契約。
- `--dry-run` 只做開啟計畫；下游工具的 dry-run 只證明設定讀回與取消。

## 2026-08-02 真實 XQ 3.19.03 證據

| 函數 | Caller | 結果 |
| --- | --- | --- |
| `MyTrendScore`（數值） | `MyTrendScoreIndicator`（指標） | 兩份皆 0 錯誤、0 警告 |
| `MyBreakoutStrength`（數值） | `MyBreakoutStrengthScreener`（選股） | 兩份皆 0 錯誤、0 警告 |
| `MyBullishSignal`（邏輯值） | `MyBullishSignalAlert`（警示） | 兩份皆 0 錯誤、0 警告 |
| `CodexV1FlowMomentum`（數值） | `CodexV1FlowAutotrade`（交易） | 兩份皆 0 錯誤、0 警告 |

原本缺少的必要函數 `MyTrendScore` 已依現有 `generated/my-trend-score-function.xs` 建立在函數類型的 `自訂/CODEX/` 並保留，因它是使用者指標的相依文件，不是可刪除的暫存測試腳本。

交易下游以公開商品 2330、日頻、2026-06-01 至 2026-06-30 完成設定乾跑後取消。`SetTotalBar(20)` 停用預載欄位時，要求值 1 被記錄但沒有宣稱已套用。沒有按開始回測、沒有建立報告或 checkpoint，也沒有操作帳號、即時策略或下單。

## 證據界線

八份文件的結果只證明指定名稱與來源版本在該 XQ 版本通過編譯。交易設定乾跑只證明下游交接與設定讀回；本階段沒有新增指標繪值、選股結果、警示觸發或交易回測報告，因此不推論策略正確性、獲利能力或投資價值。
