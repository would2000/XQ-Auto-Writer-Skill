# 選股回測商品選擇

本文件記錄選股腳本回測的商品範圍工作流。它只適用於已編譯成功、且使用者已明確授權執行歷史回測的選股策略；不授權啟動回測、帳號操作或任何交易行為。

## 先決條件

選股回測只可使用日線或更高頻率。開始前必須向使用者取得以下明確設定：

- 停利：是否啟用、數值及單位。
- 停損：是否啟用、數值及單位。
- 最大持有期：是否啟用及期數；在選股日頻回測中，一期以一個交易日／天數解讀。

日期區間、交易方向、持有／再平衡與部位配置仍依 [backtest-configuration-contract.md](backtest-configuration-contract.md) 取得。

## 已驗證的 XQ 3.19.03 視窗

2026-07-26 以 `MyBreakoutStrengthScreener` 開啟「執行回測[選股]」後，讀回：

| 欄位 | 控制項 | 預設讀回值 |
| --- | --- | --- |
| 市場別 | ComboBox `2092` | `台股` |
| 範圍 | ComboBox `2094` | `普通股全部(系統)` |
| 停利 | CheckBox `2122`、Edit `2003`、ComboBox `2093` | 不保存現有 UI 值為預設 |
| 停損 | CheckBox `2123`、Edit `2004`、ComboBox `2095` | 不保存現有 UI 值為預設 |
| 最大持有時間 | CheckBox `2124`、Edit `2005` | 不保存現有 UI 值為預設 |
| 開始／取消 | Button `2033`／`2034` | 未取得執行授權時只能取消 |

`2092` 當次可讀回市場包含台股、陸股、港股與美股。台股的 `2094` 清單包含系統範圍與使用者自選範圍；使用者自選名稱為私人資料，不能記入共享知識或當成預設。

## 系統預設範圍與自選股組合

選股回測的範圍不是逐檔商品清單。XQ 3.19.03 的範圍 ComboBox `2094` 可選系統預設範圍或使用者自選股組合；組合名稱與內容都是私人資料。

`xq_screener_backtest.py` 只接受使用者已手動開啟、且控制項特徵已驗證的選股回測設定視窗；它不猜測如何開啟未知的選股介面。

- 系統預設範圍：CODEX 只可在使用者明確指定完整名稱後設定與讀回，名稱必須以 `(系統)` 結尾。
- 自選股組合：使用者必須先手動選定。CODEX 不列舉、搜尋、命名、選取、清空或更改組合，只可在記憶體中確認選取值非空且不是系統範圍，且結果不保存組合名稱。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_screener_backtest.py --config .xq-auto-writer/xq-ui.json --market 台股 --system-default-scope '普通股全部(系統)' --dry-run
python .agents/skills/xq-xscript-compiler/scripts/xq_screener_backtest.py --config .xq-auto-writer/xq-ui.json --manual-watchlist-group-selected --dry-run
```

系統範圍流程先設定並讀回市場，再重新讀取範圍選項，最後設定並讀回指定範圍；成功後會取消視窗。自選股組合流程不變更目前選擇，並回傳「使用者手動選取、名稱未保留、無法由 CODEX 對私有名稱做精確最終驗證」的證據後取消。兩條流程都不會啟動回測、產生報告或改動 checkpoint。若有既有 `manual_review_required`、範圍未能精確讀回，或嘗試把自選組合名稱傳入 CLI，必須停止。

市場、系統範圍及取消等每次輸入前都必須驗證設定視窗的精確 handle 位於 Windows 前景，並輸出 `settings_evidence.foreground_guard`。前景切換失敗、視窗 disabled／hung、`WaitGuiThreadIdle`、對話框晚到或 timeout 後不得補送輸入或自動重試。

## 工作流

1. 在選股策略頁開啟「回測」，讀回市場別與範圍。
2. 使用者必須明確指定系統預設範圍，或自行選定自選股組合；不得從目前值推測預設測試範圍。
3. 使用者要求自選股組合時，不得讀取、列舉或儲存名稱與內容；只接受使用者手動完成後的非系統、非空白選取確認。
4. 在停利、停損與最大持有期都已明確定義前，不得按「開始回測」。
5. 尚未取得完整回測執行授權時，按「取消」離開並確認沒有進度或新報告視窗。

## 正式 runner 與校正證據

2026-08-02 以已編譯的 `MyBreakoutStrengthScreener` 重新讀回 XQ 3.19.03 選股回測設定：日頻 `2091`、市場 `2092`、系統範圍 `2094`、方向 `2061／2062`、進場價 `2063／2064`、出場價 `2065／2066`、日期 `2200／2201`、停利 `2122／2003／2093`、停損 `2123／2004／2095`、最大持有 `2124／2005`、股票成本 `2014`、Print `2131` 均各有唯一控制項。這些是選股頁本身的實機讀回，不是借用其他類型的 control ID。

需要重新校正時可執行：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_screener_backtest_probe.py --config .xq-auto-writer/xq-ui.json --open-settings
```

`--open-settings` 只以 XScript 唯一具名「回測」按鈕開啟一次，之後不送輸入，只列出白名單控制項的存在、類型、visible／enabled、日期與公開設定值；`2094` 若不是名稱以 `(系統)` 結尾的公開系統範圍，文字會改成 `<private-scope-redacted>`，不保存私人組合名稱。

完整 dry-run 或真實回測使用 `xq_screener_backtest_run.py`。它要求精確腳本名稱、公開系統範圍、方向、日頻、日期、進出場價、停利、停損、最大持有、股票成本及 Print 狀態全部明確傳入；每個選用規則都必須明示啟用或停用。真正 Start 另須 `--confirm-historical-backtest`。正常完成路徑接上共用 `xq_backtest_monitor.py`，只送一次 Start，只接受唯一且腳本 marker 相符的新增報告，完成後只清理該精確報告；證據不足保留 checkpoint。

2026-08-02 的真實 smoke 使用台股 `普通股全部(系統)`、日頻、2026-06-01 至 2026-06-30、做多、次期開盤進場、當期收盤出場、停利與停損各 8%、最多持有 20 期、股票成本 0.2%、Print 停用。唯一新增報告的 marker 精確吻合 `MyBreakoutStrengthScreener`，XQ 回報成功商品 1,920、失敗商品 21、交易 494；21 筆失敗只提供「選股策略執行錯誤」，沒有實際錯誤碼，因此 runner 保留 `null`，不得查表猜測。報告關閉確認曾晚到，但讀回已證明報告內容消失，結果記錄 `late_wait_observed: true`，並安全清除 checkpoint。這只驗證回測流程及證據契約，不代表策略績效。
