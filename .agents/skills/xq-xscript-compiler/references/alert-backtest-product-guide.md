# 警示回測商品選擇

本文件適用於已取得同一名稱、警示類型及來源版本之當次真實 XQ 編譯 `success`，且使用者明確授權進行歷史回測的警示腳本。XScript 標題含「未編譯」或只有名稱／`自訂/CODEX/` 位置讀回時必須拒絕開啟回測。它只規範商品來源與暫時回測設定；不授權帳號操作、策略啟動或下單。

## 回測設定入口

2026-07-26 在 XQ 3.19.03 的 `MyBullishSignalAlert` 開啟「執行回測[策略]」後，商品來源 ComboBox `2092` 可讀回：`商品`、`組合`、`選股`、`庫存`、`檔案`，預設為 `商品`。本工作流只學習並自動化公開「商品」來源；其他來源可能指向使用者私人資料，除非使用者明確指定，否則不讀取或修改。

按商品區的「設定」(Button `2031`) 可開啟巢狀的商品選擇器；完成有效選取後，會回到「執行回測[策略]」。

## 商品選擇器

| 功能 | 控制項 | 已驗證行為 |
| --- | --- | --- |
| 市場／類別 | ComboBox `761` | 選擇市場、資產或分類後，會重建下一層選單與結果清單。 |
| 產業／組合 | ComboBox `762` | 內容依 `761` 的選擇變化；若是「我的商品組合」類型，內容可能是私人自選組合，不得保存其名稱或自動猜選。 |
| 結果 | ListView `782` | 顯示目前兩層分類或查詢字串所對應的商品。 |
| 全部加入 | Button `804` | 在公開 `台股指數`／`上市櫃指數` 測試中，結果清單 242 筆，已選清單讀回 243 筆；功能可將清單成員批次加入。此差異可能含介面空白／既有列，不可用來推論精確商品總數。 |
| 個別查詢 | Edit `741`、Button `802` | 查詢 `2330` 後結果第一列為 `2330`。 |
| 加入選取 | Button `803` | 選取結果列後可加入；本次讀回 `台積電(2330)`。 |
| 已選清單／完成 | ListBox `781`、Button `1` | 至少一個有效商品時「完成」可用；完成後父視窗商品讀回 `台積電(2330)`。 |
| 取消 | Button `806` | 未取得回測啟動授權時使用，避免保留暫時商品設定。 |

範例的市場／類別與產業／組合搭配為：`台股指數` → `上市櫃指數`，結果清單包含公開台股指數代碼。每次切換第一層都必須重新讀回第二層與結果，不能假定跨市場的組合相容。

## 逐檔商品範圍轉接器

`xq_alert_backtest.py` 只用於已開啟警示腳本時的安全設定演練：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_alert_backtest.py --config .xq-auto-writer/xq-ui.json --product 2330 --dry-run
```

它會套用公開商品的清空、精確加入與讀回驗證，將證據放在 `settings_evidence.scope_selection`，然後取消回測視窗。它不會按開始、讀取報告、建立／清除 checkpoint，亦不會碰觸私人商品來源。`recovery-status` 不是 `safe_to_start`、腳本類型讀回不符、或商品有多個搜尋結果時，均應拒絕執行。

每個 `click_input` 前都必須以父視窗精確 handle 通過 foreground guard；結果另保存 `settings_evidence.foreground_guard`，商品選取內則保存 `scope_selection.foreground_guard`。若目標被 Codex 或其他應用程式遮住、Windows 不接受前景切換、視窗 disabled／hung、`WaitGuiThreadIdle`、對話框晚到或 timeout，立即停止且不得在 `finally` 補送取消。只有使用者確認後才能做一次受控續跑。

## 工作流

1. 開啟回測後，讀回商品來源；未指定時採 `商品`，並向使用者揭露此預設。
2. 只有使用者要求公開市場／產業分類時，才依 `761` → `762` → `782` 選取；若指定組合、選股、庫存或檔案，停在對應選擇畫面讓使用者選取私人來源。
3. 需要整個公開分類時使用「全部加入」，並讀回已選清單；需要單一商品時，以代碼／名稱查詢、選取結果後按「加入選取」。
4. 按「完成」前，讀回至少一個有效標的；回到父視窗後再次讀回商品欄。
5. 執行警示回測前，必須向使用者明確詢問停利與停損（是否啟用、數值、單位）。其餘設定僅可採已揭露的預設值。
6. 未取得完整設定與「開始回測」授權時，取消商品選擇器及父視窗，不得按「開始回測」。

## 已確認設定的最小真實回測

完整設定必須由使用者逐項確認後，才可使用 `xq_alert_backtest_run.py`。以下命令只是一個已確認設定的形式範例，不是可自行套用的預設：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_alert_backtest_run.py `
  --config .xq-auto-writer/xq-ui.json --script-name MyBullishSignalAlert `
  --product 2330 --product-kind stock `
  --direction long --frequency day --start-date 2026-06-01 --end-date 2026-06-30 `
  --price-basis original --entry-price next_open --exit-price next_open `
  --no-simulate-entry-ticks --no-simulate-exit-ticks `
  --max-concurrent-entries 1 --take-profit 8 --take-profit-unit percent `
  --stop-loss 8 --stop-loss-unit percent --max-holding-periods 20 `
  --stock-fee-percent 0.2 --no-print-enabled --confirm-historical-backtest
```

runner 先唯讀驗證目前文件名稱、警示類型及 `自訂/CODEX/` 位置，再保存既有報告 handle 基準與 checkpoint。開始鍵只以 Windows 正式按鈕命令送出一次；設定視窗延遲關閉時不得重按，改以原生視窗清單唯讀監控 `starting → running → late_report → completed`，隱藏的進度視窗也算執行證據。一般 timeout 後進入有界的晚到報告寬限期，不重播任何輸入。

報告解析會先以快速 Win32 對話框列舉縮小候選，再對候選做局部 UIA 解析。只有「相對基準唯一新增報告 handle＋視窗標題包含指定腳本名稱 marker＋報告摘要有結論」三項同時成立，才能完成並清除 checkpoint；報告不唯一、marker 不符或摘要不足均回報 `manual_review_required`。成功、失敗與部分失敗只按 XQ 報告的實際商品數、交易數及錯誤明細回報，不推測錯誤碼。得到完整報告後只關閉該新增 handle，既有報告不變；前景拒絕、disabled／hung、`WaitGuiThreadIdle` 或最終 timeout 後停止輸入並保存私有 incident。

2026-08-02 以相同的 `MyBullishSignalAlert`／2330／日線代表設定完成慢速真實 smoke：Start 命令只送出一次，狀態在 1.234 秒讀到 `running`、4.828 秒讀到 `late_report`、8.906 秒讀到 `completed`；唯一新增報告標題 marker 相符，XQ 實際回報成功商品 1、失敗 0、交易 1。runner 精確關閉該報告並清除本次 checkpoint，未使用人工復原。此證據只證明本次自動化流程正常，不代表策略績效或實盤安全。

timeout 時若 checkpoint 的精確進度視窗仍可見、啟用且未無回應，runner 會先截取該視窗本身，並唯讀保存已顯示的商品執行狀態；不截整個桌面，也不因截圖自動關閉進度、清除 checkpoint 或重跑。2026-08-01 的 XQ 3.19.03 實測顯示 `其他失敗 - 回測執行異常(1)`；官方自動交易錯誤文章的回測表將代碼 `1` 定義為回測執行階段的未細分異常。沒有報告時只記 `actual_progress_error_code: 1`，`actual_report_error_code` 仍為 `null`。

警示方向的「作多／作空」是 XQ 自繪按鈕，Windows `BM_GETCHECK` 不會回報選取狀態。runner 仍以讀回的 control ID 操作，但用各控制項自身的局部填色讀回驗證唯一選取方向；此例外不得擴張成固定螢幕座標，也不得只因 click 成功就聲稱方向已套用。
