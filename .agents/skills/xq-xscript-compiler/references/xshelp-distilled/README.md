# XSHelp 蒸餾知識

這個目錄保存由 XSHelp 官方頁面人工改寫、結構化後的知識，不是官方正文鏡像。

## 資料邊界

- `quote-fields.json` 只保存欄位識別、單位、格式、支援腳本、支援商品、使用時機、限制及短篇改寫結論。
- 不保存 HTML、原始 `syntax`／`description`、完整官方範例或足以還原頁面的長段文字。
- `verification_status` 為 `文件蒸餾`，表示只由文件核對；必須經目前 XQ 編譯器實測後，才能升級為編譯器驗證規則。
- `manifest.json` 是批次 checkpoint 與涵蓋率紀錄，不含網頁正文。

## 使用方式

先按名稱、單位、腳本或商品搜尋：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/search_xshelp_distilled.py --query "成交量 台股"
python .agents/skills/xq-xscript-compiler/scripts/search_xshelp_distilled.py --query "警示 期貨" --limit 10
```

命中後仍應核對 `supported_scripts` 與 `supported_products`。`GetQuote` 是即時報價快照入口，適用於官方列出的警示、交易與函數腳本；若要歷史序列、跨頻率或選股資料，應改查相應的 `GetField`／選股欄位文件，不能只因欄位名稱相同就互換。

## 更新流程

每批最多 20 頁，限定 `third_party/xshelp/index.json` 內的同站 URL，頁間至少 0.3 秒，設定逾時與重試。正文只在記憶體中暫時處理；成功蒸餾後以原子寫入更新資料與 checkpoint，部分失敗時保留上一版。全站 1,459 頁的工作必須分批續跑，不在 CI 中執行無界限抓取。
