# XScript 函數腳本指南

本指南只處理 XQ 的「函數」文件。函數是供其他指標、選股、警示、函數或自動交易腳本呼叫的可重用計算單元；它不是獨立的畫圖、篩選、警示或下單腳本。

## 建立前必須確認的契約

在產生程式碼前，取得下列資料：

1. 函數名稱及用途。
2. 回傳型別：數值 `number`、邏輯值 `boolean` 或字串 `string`。
3. 依呼叫順序排列的參數名稱、意義、型別、單位與合法範圍。
4. 回傳值的意義、單位及所有邊界情況，例如期數不足、分母為零、空字串或不支援商品。
5. 函數是逐根獨立計算，還是依賴前期狀態的序列計算。
6. 可使用的腳本類型、商品、頻率及資料欄位限制。

若使用者沒有指定回傳型別，不可由函數名稱猜測。若參數或邊界行為會改變結果，也應在寫程式前確認。

## 文件類型與回傳值

| 回傳型別 | XQ 建檔選項 | Canonical header | 產生碼的回傳方式 |
| --- | --- | --- | --- |
| 數值 | 數值 | `{@type:function}` | `retval = <數值運算式>;` |
| 邏輯值 | 邏輯值 | `{@type:function_bool}` | `retval = <布林運算式>;` |
| 字串 | 字串 | `{@type:function_string}` | `retval = <字串運算式>;` |

產生碼一律使用 `retval`，不要把 XQ 顯示名稱當成回傳變數。中文名稱直接出現在指定敘述左側曾被目前編譯器判定為無法辨認的字。也不要使用選股／警示的 `ret`。

每個正常執行路徑都必須得到明確回傳值。複雜分支宜先指定安全的預設 `retval`，再於各分支覆寫；靜態前置檢查只能證明程式中存在指定敘述，不能證明所有控制流程都已涵蓋。

## 參數與計算模式

本地官方 preset 可觀察到 `NumericSimple`、`NumericSeries`、`NumericRef`、`NumericArray`、`NumericArrayRef`、`StringSimple`、`TrueFalseSimple` 與 `TrueFalseSeries` 等參數型態。不得只依名稱互換：

- `Simple` 適合單次值或逐根彼此獨立的參數。
- `Series` 用於呼叫端傳入可回看歷史值的序列。
- `Ref` 與 `ArrayRef` 會讓函數修改呼叫端資料，屬可見副作用；只有需求明確要求多輸出或更新呼叫端狀態時才使用。
- 陣列必須確認維度、有效長度、索引起點及容量不足時的行為。

XSHelp 對 `SetBarMode` 的文件蒸餾指出：`0` 由系統判斷、`1` 指定逐根獨立的 simple 計算、`2` 指定會承接前期狀態的 series 計算。只有能說明狀態模型時才明確設定；不可為了通過編譯任意選值。

## 邊界與執行期錯誤

- 期數、陣列長度、分母及索引在使用前先驗證。
- 有合理中性結果時，明確回傳該結果；輸入違反函數契約且繼續運算會誤導時，才使用 `RaiseRunTimeError`。
- `return` 只離開當次執行；XSHelp 對 `RaiseRunTimeError` 的文件蒸餾指出，它會中止腳本並顯示錯誤訊息。兩者不可視為同義。
- 使用 `GetField`／`GetQuote` 前，查明欄位單位、更新時點、支援腳本與商品。跨頻率資料要明確指定來源，不可假設呼叫端週期。
- 函數不應包含 `Plot`、`OutputField`、`SetPosition` 或 `CancelAllOrders`；圖表、報表及交易副作用留在呼叫端腳本。

## 寫作與驗證流程

1. 依回傳型別搜尋同類型本地範例；字串函數的上游樣本很少，不能由數值函數類推未驗證語法。
2. 搜尋 XSHelp metadata、已蒸餾欄位與 `compiler-lessons.md`；一般任務最多暫讀三個相關官方頁面。
3. 產生 UTF-8 `.xs`，使用 canonical header 與 `retval`。
4. 執行離線前置檢查：

   ```powershell
   python .agents/skills/xq-xscript-compiler/scripts/xq_function_preflight.py `
     --source generated/<name>.xs `
     --function-return-type <number|boolean|string>
   ```

5. 使用 `xq_prepare_script.py` 新建「函數」文件並選擇完全相同的回傳型別。
6. 使用 `xq_compile.py` 編譯；只有當次 `success` 才是語法通過證據。
7. 若函數將供其他類型腳本使用，再建立最小呼叫端腳本驗證參數順序、型別、序列行為與實際輸出。函數本身編譯成功不證明呼叫契約正確。

## 紅燈／綠燈整合測試

需要執行結果證據時，建立兩個彼此獨立的最小自動交易呼叫端：

1. 使用非對稱常數編碼參數位置，例如第一參數乘 `10000`、第二參數乘 `100`，讓同型別參數交換後產生不同答案。
2. 讓函數接受 `NumericSeries`，呼叫端以獨立公式計算同一根與前一根資料；expected 不可再次呼叫受測函數。
3. 紅燈呼叫端故意把 expected 偏移固定值，斷言必須執行 `RaiseRunTimeError`。只有新回測報告為純失敗、錯誤碼為 `1301`、說明含唯一預期標記，才證明測試路徑確實執行。
4. 綠燈呼叫端使用正確 expected，並分別驗證正常與交換參數順序；只有新報告至少一個成功商品、零失敗商品，才通過。
5. 紅綠兩次使用完全相同的公開商品、頻率、日期、暖機與回測假設，且都不得留下 recovery checkpoint。呼叫端可為了確保成功報告而產生歷史模擬交易，但不得選帳號、建立實盤策略或啟動即時交易。

進階參數須把每種可見效果分開斷言：

- `NumericRef`：呼叫前以不同哨兵值初始化每個輸出；呼叫後逐一比對，不能只驗證 `retval`。
- `NumericArray`：由呼叫端設定明確長度及非對稱元素，再由函數唯讀取值；不要用相同元素測順序。
- `NumericArrayRef`：呼叫後同時比對 `Array_GetMaxIndex` 與每個預期元素，才能證明尺寸及內容都已回寫。
- 多維 `NumericArray`：函數輸入要宣告每一維，呼叫端傳入相同維度數的陣列；以不對稱資料逐格驗證，不能只驗證總和或單一元素。`Array_SetMaxIndex` 只用於一維動態陣列，不可拿來調整多維陣列。
- 陣列長度與越界：把零長度防護、最小合法長度、擴充後長度及原生越界分成不同案例。自訂契約防護可用 `RaiseRunTimeError` 取得 `1301`；未防護的非法索引應記錄 XQ 原生錯誤，不可預先假設仍是 `1301`。
- 數值哨兵：非對稱權重必須保持在安全範圍。若呼叫端常數運算超過 32 位元有號整數範圍，expected 可能先溢位，造成函數值正確卻被測試誤判。
- 函數呼叫函數：每一層都有獨立名稱、簽章、計算模式與邊界契約。先前置檢查並編譯最內層，再編譯直接依賴它的外層；不可只因外層可編譯就省略內層證據。
- 巢狀綠燈：呼叫端從原始常數及序列完整展開內外層公式，不得呼叫任一受測函數來產生 expected。至少用一組正序與反序會得到不同值的非對稱參數，才能檢出外層轉送順序錯誤。
- 巢狀紅燈：把唯一錯誤標記放在內層防護，經外層呼叫後要求最終報告仍為同一個 `1301` 標記。若紅燈由外層自行拋錯，只能證明外層路徑，不能證明內層錯誤傳播。
- `TrueFalseSeries`：傳入會確定變化的布林序列，函數內分別讀取當根、`[1]`、`[2]`，以不對稱權重編碼；呼叫端必須從原始規則重建三根 expected。測試序列要保證至少一根的三個布林值不同，否則無法排除只重複傳入當根值。
- `SetBarMode(2)`：在每根 bar 都呼叫函數，以不引用受測函數的封閉公式逐根計算 expected；不同呼叫位置應各自驗證。若另設「兩序列不得相等」斷言，必須先求出可能交點，不能把合法相交誤判成狀態錯誤。
- `SetBarMode(2)` 條件式呼叫：把「函數內部 series」與「呼叫端接收變數」分開驗證。XQ 3.19.03 的指定案例中，條件為 false 的 bar 雖未執行賦值語句，函數的 `retval[1] + StepSize` 仍按 bar 延續；呼叫端變數則維持前次賦值，到下一次條件為 true 才跳到新的函數值。因此 expected 應由 `CurrentBar` 的封閉公式重建，另用前次接收值證明 caller 在跳過 bar 未被賦值；不可只用「實際進入分支次數」推算函數狀態，也不可把這個單一案例外推至所有函數或版本。
- 跨頻率：函數內每個 `GetField`／`GetFieldDate` 都明確指定來源頻率，caller 再用原生分鐘欄位及日期轉換獨立重建 expected。1 分鐘 caller 讀取 `"D"` 時，須分別斷言當日日頻值、前一個日頻期別及欄位資料日期；`GetField(..., "D")[1]` 的 `[1]` 是前一日頻期別，不是前一根 1 分鐘 bar。可在 `Date <> Date[1]` 時把 `Close[1]` 保存為前一日最後分鐘收盤，於同日後續分鐘持續比對；另要求當日日頻 Close 至少在同日內隨分鐘 Close 發生一次變化，避免靜態常數也誤通過。資料對位模式、欄位、商品或版本不同時必須重測。
- 資料不足與初始化：把回測介面的預先執行筆數、`SetTotalBar` 的資料讀取範圍、`SetBarBack` 的指定頻率最大引用範圍，以及函數實際的 `[n]` 回看分開記錄。第一根需要中性結果時，由函數契約明確回傳哨兵或中性值，資料就緒後才讀取歷史；不要依賴未證明的系統預設。每個案例都要有必定執行的路徑哨兵，因為商品報告為 `success`、交易 0 仍可能是正式區間沒有任何 bar 進入腳本，不能據此宣稱深度索引回傳 0、`Default` 生效或函數斷言通過。
- 深度回看邊界：先用同商品、頻率與日期的較短足量回看證明路徑哨兵可觸發，再增加到不足長度。只有報告實際出現失敗明細時才能保存原生代碼；若不足案例是成功 1／失敗 0／交易 0 且哨兵未執行，應分類為「無正式執行證據」，不得查表補成 `1401`。`GetFieldStartOffset` 只支援選股，不能拿來替自動交易 caller 證明可用資料長度。

`TrueFalseSeries` 與 `SetBarMode(2)` 證明的是兩件事：前者是呼叫端布林參數的歷史可回看性，後者是函數自身跨 bar 狀態。不能因其中一項通過就宣稱另一項也正確。

## 函數資料邊界自動化第四階段

`xq_function_boundary_runner.py` 將第三階段的人工矩陣收斂成可重複的 JSON 案例。案例檔只列不足案，欄位包含商品、日期、caller 頻率、來源頻率、索引、`Default`、`SetTotalBar`、`SetBarBack`、預載值、預期結果、預期 marker 及較短控制索引；載入時自動展開同商品、日期與設定的足量控制組。控制索引必須小於不足索引，兩條路徑 marker 必須在整個 suite 唯一。

清理報告時，XQ 會先顯示「是否要儲存回測報告？」。runner 只在 manifest 記錄的報告 handle 內動態辨識唯一「不儲存」控制，並等待報告內容消失；只送出視窗 close、仍看到報告內容時不得回報清理完成。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_boundary_runner.py `
  --config .xq-auto-writer/xq-ui.json `
  --cases generated/function-data-boundary-cases-v4.json `
  --confirm-historical-backtest
```

每案分別建立函數與自動交易 caller，保存兩份當次編譯訊息，再輸出商品成功／失敗數、交易數、報告實際錯誤碼、實際 marker、正式路徑是否被證明，以及 `settings_evidence` 中預載控制項是否可用與 CLI 值是否套用。`no_execution_evidence` 只在報告為成功商品、失敗 0、交易 0且沒有任何實際 marker 時成立；它不是函數成功或資料不足錯誤碼。

回測 checkpoint schema v2 會在按開始前保存可見報告 handle 基準，不保存商品、腳本正文、參數或績效。正常監控逾時後，runner 只允許「相對基準唯一新增的報告」且失敗明細含該案例精確 marker 時完成晚到報告復原；新增報告為零、多於一份、明細擷取失敗或 marker 不符，一律保留 checkpoint 並回傳 `manual_review_required`。不能因任意新報告出現就解除保護，也不能由本地錯誤碼表補值。

本次文件清理由 run manifest 限定。清理器先用 XQ 開啟清單精確篩選，再從活動文件及公式區屬性讀回完全相同的名稱、腳本類型與 `自訂/CODEX/` 儲存位置；任一不一致即拒絕刪除。回測報告也只依 manifest 記錄的 handle 關閉，暫存來源與 manifest 只能在本次 run 目錄內移除；使用者原有文件與報告不在清理範圍。

## 函數資料邊界自動化第五階段

案例 schema v2 將函數內的來源回看 `index` 與 caller 接收值的 `caller_index` 分開，控制組則使用 `control_index` 與 `control_caller_index`。控制組的兩個索引都不得大於不足組，且至少一項必須更短；因此 caller `[n]` 邊界不會被錯當成來源頻率邊界。每案另以 `expected_preload_state: enabled|disabled` 明確斷言回測預載控制項狀態，不能只由是否出現 `SetTotalBar` 在本地推測結果。需要區分 `Default` 分支時，以 `expect_default_value` 指定 marker 應落在相等或不相等路徑，兩條路徑仍由 XQ 報告實際 marker 判定。

第五階段矩陣至少涵蓋分鐘／日頻 caller、`D`／`W`／`M` 來源、固定／動態索引、有／無 `Default`、獨立的 `SetTotalBar`／`SetBarBack`、caller `[n]`，以及預載啟用／停用。這是覆蓋每個維度的代表案例，不宣稱所有欄位、商品、日期及參數的完整笛卡兒積皆已驗證。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_boundary_runner.py `
  --config .xq-auto-writer/xq-ui.json `
  --cases generated/function-data-boundary-cases-v5.json `
  --late-recovery-probe-case minute-dynamic-d-caller-series-control `
  --late-recovery-timeout-seconds 0.05 `
  --require-late-recovery-probe `
  --confirm-historical-backtest
```

runner 在私有 `.xq-auto-writer/function-boundary-results/` 原子更新 JSON 與 JUnit XML。JSON 保存逐案狀態、編譯、商品、交易、實際錯誤碼、marker、執行與設定證據；JUnit 將尚未完成案標成 skipped，完成或失敗後隨進度改寫。兩份彙總是本次使用者測試資料，不得提交；XQ 文件、報告、checkpoint、來源暫存與 manifest 仍在完成後清除。

若工作中斷，只能使用失敗結果回傳的精確 manifest：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_boundary_runner.py `
  --config .xq-auto-writer/xq-ui.json `
  --cases generated/function-data-boundary-cases-v5.json `
  --resume-manifest .xq-auto-writer/function-boundary-runs/<run>/manifest.json `
  --confirm-historical-backtest
```

續跑前必須驗證 manifest schema、suite digest、逐案契約、私有輸出路徑與唯一 active case。`completed` 案只載入既有結果，不重新建檔、編譯或回測。若 active case 尚未按開始且 recovery 為安全狀態，先依 manifest 清理它已建立的文件，再以新 attempt 重做；若已進入回測，只能用開始前 baseline 排除舊報告，並在唯一新增報告的失敗明細實際取得完全相同 marker 後完成該案。無 marker 的 active case、報告不唯一、marker 不符或證據不足一律維持 `manual_review_required`，不得自動重跑。

`--late-recovery-probe-case` 只接受預期為唯一哨兵失敗的控制案。搭配極短監控期限時，runner 必須先取得 `indeterminate_timeout` 與保留的 checkpoint，再等晚到報告；`--require-late-recovery-probe` 會要求本次確實走過這條路。報告若在期限內正常完成，不能把它冒充晚到復原證據。

2026-07-23 已在真實 XQ 3.19.03 完成 run `f5df0ba5-90d2-4f87-94df-19716d454f4e` 的 8／8 案。0.05 秒控制案先逾時，再由相對 baseline 唯一新增的報告 handle 與完全相同 marker 安全復原；續跑期間已完成案例未重跑。報告實際回傳的哨兵錯誤碼為 `1301`，未出現哨兵的案例不補錯誤碼。`SetTotalBar` 案實際讀回預載欄位停用；固定索引 5000 搭配 `Default := -999` 的指定案例則走非 Default marker，故案例明列 `expect_default_value: false`，不外推成其他索引、欄位或版本的通則。所有本次報告、XQ 測試文件、checkpoint、暫存與 manifest 已依 manifest 完整清除，JSON 與 JUnit 彙總保留於私有結果目錄。

## 函數資料邊界自動化第六階段

`xq_function_regression.py` 將 runner 的逐案結果正規化成不含 run ID、文件名稱、報告 handle、商品、日期、時間戳及原始編譯文字的 baseline。可比較的白名單只包含案例契約 SHA-256、pair／role、函數與 caller 編譯狀態及錯誤／警告數、商品成功／失敗數、交易數、XQ 實際錯誤碼與 marker、執行證據、預載設定讀回及 Default 分支。baseline 另外鎖定 XQ 版本、案例 schema 與 runner contract；任一版本不同時分類為 `version_mismatch`，不能冒充回歸一致。

建立或更新 baseline 必須同時指定新的、尚不存在的檔案、遞增版本與 `--confirm-baseline-update`。工具拒絕覆寫既有 baseline；更新時舊檔保留，當次 JSON／JUnit／Markdown 差異報告形成更新紀錄：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_regression.py `
  --result-json .xq-auto-writer/function-boundary-results/<result>.json `
  --xq-version 3.19.03 --case-schema-version 2 --runner-contract-version 6 `
  --output-directory .xq-auto-writer/function-regression-results/<run> `
  --write-baseline .agents/skills/xq-xscript-compiler/references/function-regression/baseline-v1.json `
  --baseline-version 1 --confirm-baseline-update
```

一般比較傳入 `--baseline`，輸出 `unchanged`、`regression`、`version_mismatch` 或 `evidence_insufficient`，並列出 `affected_case_ids`、`affected_pair_ids` 及可直接交給 runner 的 `runner_only_pair_arguments`。runner 的 `--only-pair` 必須以 pair 為最小單位，同時執行控制與不足案；續跑時要再次提供相同 pair 選擇，manifest schema v3 會核對 `selected_pair_ids` 與 runner contract，不能把不同子集接到舊 manifest。

第六階段 smoke 案例位於 `references/function-regression/cases-v6.json`，只選兩個公開商品與兩組已知日期：短歷史 7818 的月頻 Default marker pair，以及長歷史 2330 的日頻 marker pair。這是有限代表組，不是多商品、日期或市場的完整覆蓋。真實 smoke 不注入 XQ 當機或斷網；這些分支只以單元測試建立 interrupted／缺報告證據，結果必須保持 `evidence_insufficient` 且不得推測錯誤碼。報告不唯一與 marker 不符仍沿用 checkpoint 保留契約。

runner 預設每次 XScript 類型分頁、清單模式、列選取、刪除確認與刪除後驗證至少等待 2 秒，案例之間預設等待 5 秒；較慢桌面可用 `--inter-case-seconds` 再提高。禁止密集掃描 XScript 自訂分頁。若 Windows 顯示無回應，或等待 XScript「開啟」對話框逾時，立即停止 UI 輸入，將 UTC 時間、active case／stage、PID 與視窗健康、checkpoint、可見報告及唯讀 recovery-status 寫入私有 manifest 的 `windows_wait_incidents`，並向使用者回報；此事件不是故障注入成功。

2026-07-23 已以 XQ 3.19.03 完成 run `6c85d6c1-c8b2-4ad8-9986-feacd82d4cb5` 的 4／4 真實 smoke，JUnit 為 0 failure／0 error。回測四案完成後，文件清理曾在 3／8 時等待「開啟」對話框逾時；當下 XQ PID 35124、XScript 與 XQ 視窗皆健康，無 checkpoint、無進度窗、無可見報告。事件已保存後，續跑同一 manifest，四個 completed 案未重跑，最終 8／8 文件、4 份報告、暫存、checkpoint 與 manifest 全部清除。由該結果明確建立 `baseline-v1.json`，再次比較為 `unchanged`；baseline 不含 run ID、文件名稱、商品、日期或 handle。

## 函數資料邊界自動化第七階段

runner contract 7／manifest schema v4 將桌面等待與清理復原納入持久契約。可調欄位為 `--ui-action-settle-seconds`、`--ui-poll-initial-seconds`、`--ui-poll-max-seconds`、`--ui-poll-backoff`、`--ui-dialog-late-after-seconds`、`--ui-dialog-timeout-seconds`、`--ui-state-timeout-seconds` 及 `--inter-case-seconds`。輪詢只讀取狀態並自適應退避；相鄰輸入之間一定經過 action settle。續跑會把命令列與 manifest 逐欄取較慢值，不能意外加速舊 run。

Ctrl+O 只送一次。對話框超過 late threshold 才出現或直到 timeout 都未出現時，不再補送 Alt+F／選單點擊；Windows 無回應、`WaitGuiThreadIdle` 或視窗 disabled 超過門檻也採同一規則：立即停止輸入，原子保存 UTC、案例、文件、清理階段、PID、視窗健康、checkpoint、可見報告及當下唯讀 recovery-status。這些事件只代表需要續跑或人工檢視，不是 XQ 錯誤碼或故障注入證據。

每份 manifest 文件有獨立清理狀態：`open_requested`、`identity_readback_verified`、`delete_confirmation_verified`、`absence_verified`、`completed`。名稱、腳本類型及 `自訂/CODEX/` 必須在刪除前讀回；刪除後再以相同名稱／類型精確篩選為零列。續跑可從未完成階段重新讀回，但 `completed` 文件直接跳過；文件原本已不存在時也必須先取得零列證據。清理事件不會讓已完成的回測案例重新建立、編譯或執行。

第六階段差異工具現在另輸出 `*-plan.json`。一般 `regression` 產生 `safe_to_execute: true` 的成對 `--only-pair` 參數；`version_mismatch`、`evidence_insufficient` 不提供可自動執行的增量參數，前者要求完整矩陣。既有 `baseline-v1.json` 仍鎖定 runner contract 6，不因第七階段自動覆寫。

慢速代表 pair 範例：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_boundary_runner.py `
  --config .xq-auto-writer/xq-ui.json `
  --cases .agents/skills/xq-xscript-compiler/references/function-regression/cases-v6.json `
  --only-pair short-history-day-m-default `
  --ui-action-settle-seconds 3 --inter-case-seconds 8 `
  --confirm-historical-backtest
```

2026-07-23 已以 XQ 3.19.03 完成慢速 run `3449ecb6-8822-4ae1-b91e-c6bfa6b73f16`。只執行 `short-history-day-m-default` 一組 pair，control／shortage 皆在第一次 attempt 完成；四份函數／caller 均為 0 錯誤、0 警告，兩份報告均由 XQ 實際回傳成功 0、失敗 1、交易 0、代碼 `1301` 及各自完全相同 marker。JUnit 為 2 tests／0 failure／0 error／0 skipped。四份文件各自走完清理狀態並驗證不存在，報告、checkpoint、manifest 與暫存均清除，`windows_wait_incidents` 為 0。以 runner contract 7 比對 contract 6 的 `baseline-v1.json` 正確得到 `version_mismatch` 與 `full_matrix_required`，沒有安全的自動 `--only-pair` 參數，也未覆寫 baseline。

## 函數資料邊界自動化第八階段

`xq_function_batch_runner.py` 將完整代表矩陣拆成一次一個 pair 的子執行。每個 pair 前後都要求唯讀 recovery-status 為 `safe_to_start`，批次 manifest 保存 caller-stable child run ID、結果 SHA-256、慢速參數、cooldown 與逐 pair 狀態；中斷後只續跑第一個未完成 pair，已完成結果不得重跑或被靜默替換。

聚合前必須驗證所有結果的 suite digest、案例 schema、runner contract 與 XQ 版本完全相同，且每個 pair 恰有一個 control、一個 shortage、四份 CODEX 文件清理完成、無 active case／cleanup、無 `windows_wait_incidents`。缺 pair、重複案例、marker／編譯證據不完整或清理未完成都停止，不產生可供 baseline 使用的 aggregate。

第八階段同時把 XScript 隔離提升為強制前置條件。`xq_prepare_script.py` 必須帶 `--folder CODEX`，並先由校正設定唯一選取類型與 CODEX TreeItem、讀回精確 `自訂/CODEX/`；manifest schema v5 也保存該位置，清理只接受相同位置。若 XQ 沒有穩定可校正選擇器，工具在開啟新增腳本前停止，不得使用 `自訂/`、私人資料夾或幾何猜測。

完整 batch aggregate 產生後，才可用 `xq_function_regression.py` 以 runner contract 7 建立新的 `baseline-v2.json`。必須傳入 `baseline-v1.json` 作 migration diff、指定遞增版本 2 及 `--confirm-baseline-update`；舊 baseline 不可覆寫。2026-07-24 初次只讀探測沒有找到可驗證 CODEX 節點；後續使用者已在當時可見公式分類建立並由唯讀觀察器精確讀回 `自訂/CODEX/`，但函數與自動交易等各類分類選擇器仍未逐類校正。因此目前仍只有離線 batch 計畫與 fail-closed 測試，真實完整矩陣及 baseline-v2 尚未執行，不能宣稱認證完成。

可重用 CLI：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_integration.py `
  --config .xq-auto-writer/xq-ui.json `
  --function-source generated/<function>.xs `
  --function-return-type <number|boolean|string> `
  --function-name <ASCII函數名> `
  --red-source generated/<red-caller>.xs `
  --red-name <ASCII紅燈文件名> `
  --green-source generated/<green-caller>.xs `
  --green-name <ASCII綠燈文件名> `
  --expected-red-marker <唯一大寫ASCII標記> `
  --product <公開商品> --frequency <週期> `
  --start-date <YYYY-MM-DD> --end-date <YYYY-MM-DD> `
  --preload-records <筆數> --initial-capital-wan <萬元> `
  --confirm-historical-backtest
```

未帶 `--confirm-historical-backtest` 時，工具在讀取來源或接觸 XQ 前停止。三種回傳型別都可使用相同編排器，但紅燈與綠燈來源仍須針對自己的公開契約獨立計算 expected。通過結果只證明指定案例；尚未執行的邊界、其他商品／週期及指標、選股、警示呼叫端仍須標為未驗證。

前置檢查只攔截明確的類型標頭、回傳指定及副作用錯誤，不是 XScript parser，也不取代 XQ 編譯器或呼叫端整合測試。

## 跨腳本呼叫矩陣

函數宣告支援指標、選股與警示時，應分別建立最小呼叫端，因為三類文件的輸出契約不同：指標使用 `Plot`，選股使用 `ret` 並可用 `OutputField`，警示使用 `ret`。使用下列工具依序建立並編譯函數及三個新文件：

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_function_caller_matrix.py `
  --config .xq-auto-writer/xq-ui.json `
  --function-source generated/<function>.xs `
  --function-return-type <number|boolean|string> `
  --function-name <ASCII函數名> `
  --indicator-source generated/<indicator-caller>.xs `
  --indicator-name <ASCII指標名> `
  --screener-source generated/<screener-caller>.xs `
  --screener-name <ASCII選股名> `
  --alert-source generated/<alert-caller>.xs `
  --alert-name <ASCII警示名>
```

工具只在四份文件都有當次編譯 `success` 時回傳成功，並固定輸出 `proof_scope: compile_only`、`runtime_result_proven: false`。這只能證明目前編譯器接受函數簽章、參數型別及呼叫運算式；不證明圖表實際繪值、選股實際入選或警示實際觸發。需要執行結果時，必須另用該類型已驗證的執行介面：自動交易使用本指南的紅／綠歷史回測，指標、選股與警示則依下一節逐格驗證。

## 跨腳本執行結果矩陣

若任務要求證明函數在指標、選股與警示三種呼叫端的執行結果，compile-only 矩陣完成後還要逐格執行：

- 指標：讓函數結果控制一個可獨立驗算的 Plot。以 `xq_indicator.py` 擷取 XQ 原生 Excel，完整比較所有列，要求 `mismatch_count = 0` 且書籤復原完成。
- 選股：讓函數結果直接決定 `ret`，並輸出一個可讀回欄位。以 `xq_screener.py` 在公開系統範圍執行，依案例要求非空或空集合，且 `error_count = 0`、啟動／停止控制項已復原。
- 警示：讓同一函數與一個明確的 1／0 測試參數共同決定 `ret`。以 `xq_alert.py` 要求參數 1 有觸發、參數 0 無觸發，且本次兩個策略都精確刪除。

每個回傳型別都要有自己的三格證據；某一格的成功不能代替另一格。呼叫端的 expected 應由常數、原生欄位或獨立運算式計算，不能再次呼叫受測函數。完成後刪除本次建立的 XScript 文件與暫存策略，並關閉不再使用的 XQ 子視窗。

## 來源與驗證狀態

- 類型標頭與參數型態來自本地 `XScript_Preset` 函數樣本的結構觀察；上游內容不併入本專案授權。
- `SetBarMode` 與 `RaiseRunTimeError` 語意於 2026-07-21 由目前 XSHelp 頁面暫時讀取後重新表述，未保存官方正文。
- `SetTotalBar`、`SetBarBack` 與 `GetFieldStartOffset` 於 2026-07-22 由 XSHelp metadata 識別碼 `a29d602abc90eb6cf95f`、`4da4983cacea8c88c445`、`e432a0e685f21cce6630` 的目前頁面暫時讀取後重新表述，未保存官方正文；前兩者適用資料讀取／引用範圍，後者文件明列僅支援選股。
- 2026-07-21 已在目前 XQ 分別建立數值、邏輯值與字串函數文件，使用對應 canonical header 及 `retval` 各編譯一次；三者皆得到 `0項錯誤，0項警告`。這證明最小型別契約可編譯，不證明任意函數內容或呼叫端整合正確。
- 2026-07-22 已用 `xq_function_integration.py` 在目前 XQ 3.19.03 完成數值、邏輯值與字串三種最小整合切片。每一型別的函數及紅／綠呼叫端都以新文件建立並得到 `0項錯誤，0項警告`；每組紅燈皆為成功 0、失敗 1、交易 0，明細為 `1301` 且含唯一預期標記；每組綠燈皆為成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。
- 數值切片以兩個 `NumericSimple` 非對稱編碼並傳入 `NumericSeries` 計算 `Close-Close[1]`；邏輯值切片以兩個 `TrueFalseSimple` 的 `True/False` 順序及 `NumericSeries` 驗證布林回傳；字串切片以兩個 `StringSimple` 的 `"A"/"B"` 順序、字串 `+` 拼接、`=`／`<>` 比較及 `NumericSeries` 分支驗證字串回傳。這些是指定呼叫契約的執行證據，不外推到其他參數型態、邊界、呼叫端、商品或週期。
- 2026-07-22 已完成進階參數切片：函數從兩元素 `NumericArray` 讀取非對稱值，以兩個 `NumericRef` 回寫不同結果，並用 `NumericArrayRef` 將目標最大索引設為 2、回寫兩個不同元素。紅燈為成功 0、失敗 1、交易 0 且取得指定 `1301`；綠燈逐項比對 `retval`、兩個 Ref、陣列大小及兩個元素後為成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。此證據只涵蓋一維、兩元素、索引 1 至 2 的指定案例。
- 同日亦驗證 `SetBarMode(2)` 狀態切片：函數以 `retval[1] + StepSize` 延續前值，兩個呼叫位置分別使用 `(10,3)` 與 `(3,10)`，呼叫端以 `SeedValue + (CurrentBar-1)*StepSize` 逐根獨立比對。第一次綠燈因兩序列在第 2 根合法相交而觸發過強的「不得相等」斷言；修正交點邊界後，V2 紅燈報告取得指定 `1301`，V2 綠燈為成功 1、失敗 0、交易 2，checkpoint 已清除。紅燈完成時間超過原 60 秒監控期限，因此其報告是以新 handle 及精確標記人工關聯後清除 stale checkpoint；不可把這次證據外推成所有狀態模型、呼叫頻率或條件式呼叫都正確。
- 2026-07-22 已用同一數值函數契約完成跨呼叫端矩陣。V1 指標因 `ExpectedValue` 的 `Exp` 保留字前綴編譯失敗；改為 `TargetValue` 後指標成功。V2 選股因 `OutputField` 第 3 參數使用 6 而失敗；改為 4 後，V3 函數、指標、選股與警示四份文件皆得到 `0項錯誤，0項警告`。另以 V4 自動交易呼叫端完成紅燈指定 `1301` 與綠燈成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。前三類僅有編譯相容證據；只有 V4 自動交易具有本次執行結果證據。
- 2026-07-22 已完成邏輯值與字串函數的三呼叫端執行矩陣。兩個函數與六個指標／選股／警示文件都先取得當次 `0項錯誤，0項警告`。兩個指標各由函數契約控制是否輸出 `Close`，XQ 原生匯出各 208 列均與收盤價完全相符、錯配 0，且兩次書籤復原完成；兩個選股在「台灣五十成分股（系統）」各命中 50 檔、執行錯誤 0，並讀回各自的 Close 輸出欄位；兩個警示在台積電單次洗價中皆為參數 1 觸發 1 筆、參數 0 觸發 0 筆，四個暫存策略都已刪除。這只證明 `TrueFalseSimple` 的 `True/False` 契約及 `StringSimple` 的 `"LEFT" + "RIGHT"` 契約在該商品、資料頁與公開範圍的指定案例，不外推至 `TrueFalseSeries`、跨頻率或其他邊界。
- 2026-07-22 已用數值函數驗證 `TrueFalseSeries` 的呼叫端歷史傳遞。呼叫端以 `Mod(CurrentBar, 4)` 產生固定 `TTFF` 序列；函數將當根、前一根、前兩根分別以 1、10、100 編碼，綠燈 expected 則直接由 `CurrentBar` 規則重建，不再次呼叫受測函數。函數、紅燈、綠燈三份文件皆為 `0項錯誤，0項警告`；紅燈為成功 0、失敗 1、交易 0，取得指定 `1301` 與 `CODEX_TRUEFALSE_SERIES_RED_EXPECTED`；綠燈為成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。測試使用台積電、1 分鐘、2026-06-01 至 2026-06-02、預載 5 筆，未選帳號或啟動即時策略。這證明指定三根布林序列案例，不外推至更長索引、條件式呼叫、跨頻率或資料不足邊界，也不等同 `SetBarMode(2)` 狀態驗證。
- 2026-07-22 已完成多維陣列與長度／越界切片。數值函數接受固定 2×3 `NumericArray` 及一維動態 `NumericArray`，六個矩陣元素、維度、長度及首尾值均以安全範圍內的不對稱權重獨立比對。零長度紅燈為成功 0、失敗 1、交易 0，取得 `1301` 與 `CODEX_ARRAY_ZERO_LENGTH`；長度 1 與擴充至 4 的綠燈為成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。最初使用超過 32 位元有號整數範圍的 expected，函數實際值為 `2423456177`，呼叫端目標卻溢位成 `-1871511119`；縮小權重後契約通過。另以長度 2 陣列直接讀取索引 3，函數與呼叫端皆為 `0項錯誤，0項警告`，回測取得 XQ 原生 `1303`「不合法的陣列索引值」。測試使用台積電、1 分鐘、2026-06-01 至 2026-06-02、預載 5 筆；這只證明指定維度、長度與越界案例，不外推到三維以上、零起始索引、其他商品或跨頻率。
- 2026-07-22 已完成函數呼叫函數的巢狀契約切片。先建立並編譯內層數值函數，再讓外層以 `(2,7)` 與 `(7,2)` 兩種順序呼叫內層；內層同時讀取傳入 `NumericSeries` 的當根及 `[1]`，綠燈 caller 則不呼叫任何受測函數，直接展開兩層公式。內層、外層、紅燈及綠燈四份文件皆為 `0項錯誤，0項警告`；紅燈由內層防護拋出，最終報告為成功 0、失敗 1、交易 0，取得 `1301` 與 `CODEX_NESTED_INNER_GUARD`；綠燈為成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。測試使用台積電、1 分鐘、2026-06-01 至 2026-06-02、預載 5 筆，未選帳號或啟動即時策略。這只證明兩層數值函數、指定順序、兩根序列及錯誤傳播，不外推至三層以上、遞迴、不同回傳型別、Ref／ArrayRef 副作用或條件式呼叫。
- 2026-07-22 已完成 `SetBarMode(2)` 條件式呼叫切片。數值函數以 `retval[1] + StepSize` 延續狀態；caller 每根呼叫 `(10,3)`，另一呼叫位置只在第 1 根及偶數根執行 `(100,7)`。診斷在第 4 根取得 `19` 與 `121`，排除依分支進入次數得到的 `114`；這表示受測函數 series 在被條件略過的第 3 根仍延續，而 caller 的 `ConditionalValue` 在第 3 根保持前次 `107`，第 4 根才更新為 `121`。函數與診斷 caller 都得到 `0項錯誤，0項警告`；正式紅燈報告為成功 0、失敗 1、交易 0，取得 `1301` 與 `CODEX_CONDITIONAL_STATE_RED_EXPECTED`；綠燈重跑為成功 1、失敗 0、交易 0，checkpoint 已清除。首次整合綠燈完成瞬間遇到失效進度 handle，依規則保留 checkpoint；唯讀診斷以報告標題及 handle 分辨紅綠結果，明確確認後清除 checkpoint，再聚焦 XScript 單獨重跑綠燈成功。測試使用台積電、1 分鐘、2026-06-01 至 2026-06-02、預載 5 筆，未選帳號或啟動即時策略；只證明這個線性狀態函數、呼叫條件與版本，不外推至區域變數、不同初始化、跨頻率、資料不足或其他 XQ 版本。
- 2026-07-22 已完成 1 分鐘 caller 讀取日頻序列的跨頻率切片。數值函數依 `DataOffset` 回傳 `GetField("Close", "D")` 或其 `[1]`；caller 不呼叫受測函數產生 expected，而是在每次 `Date <> Date[1]` 時以 `Close[1]` 保存前一交易日最後分鐘收盤，並逐分鐘比對當根 Close、前一日目標及 `GetFieldDate("Close", "D")`。V1 caller 因變數以保留字前綴 `Daily` 開頭而編譯失敗；更名為 `XfCurrentValue`、`XfPreviousValue` 等後，V2 函數、紅燈、綠燈皆為 `0項錯誤，0項警告`。紅燈刻意把日頻 `[1]` 當前一分鐘值，最終為成功 0、失敗 1、交易 0，取得 `1301` 與 `CODEX_XF_DAILY_RED_EXPECTED`；綠燈確認當日日頻 Close 隨分鐘 Close 更新、日頻 `[1]` 同日維持前一日收盤、資料日期等於分鐘交易日，最終成功 1、失敗 0、交易 2，兩次 checkpoint 都清除。測試使用台積電、1 分鐘、2026-06-01 至 2026-06-02、預載 5 筆、原始值與預設遞補對位，未選帳號或啟動即時策略；不外推至週／月頻、還原值、絕對對位、其他欄位、資料不足、休市斷層、商品或版本。
- 2026-07-22 已完成資料不足與初始化切片。初始化函數在第一根以 `-999` 明確回傳中性哨兵，第二根後才讀取傳入 `NumericSeries[1]`；函數及 caller 均為 `0項錯誤，0項警告`，以台積電、1 分鐘、2026-06-01 至 2026-06-02 分別使用預載 0、1、5 筆重跑，三次皆成功 1、失敗 0、交易 1。這證明該 `[1]` 案例不以回測預載值作唯一資料來源。另以日頻 100 根回看及 `SetBarBack(101, "D")` 建立足量控制組，無條件路徑哨兵取得 `1301 / CODEX_SUFFICIENT_DAILY_PATH_EXECUTED`；改為固定或動態 10,000 根回看時，兩次報告都為成功 1、失敗 0、交易 0，但無條件哨兵沒有執行。故本版本與案例只能判定正式區間缺少執行證據，不能宣稱超界值為 0、`Default := -999` 已生效或原生 `1401` 已重現。所有函數與 callers 都取得當次 0 錯誤、0 警告；實測未取得任何原生資料不足代碼。
- 2026-07-22 已完成資料不足第三階段。短歷史商品溢泰實業（7818，2026-05-18 掛牌）在日頻 caller、2026-07-20 至 2026-07-21、預載 5 筆下，動態跨頻率序列的已執行上界為日 `[44]`、週 `[9]`、月 `[2]`；各自增加一根後，未指定 Default 的報告皆為成功 1、失敗 0、交易 0且路徑哨兵未執行。較短控制日 `[5]`、週 `[2]`、月 `[1]` 與三個足量上界均取得 `1301` 唯一路徑標記。月 `[3]` 及明顯不足 `[100]` 改用 `GetField("Close", "M", Default := -999)` 後，報告實際取得 `1301 / CODEX_BOUNDARY_M3_DEFAULT_USED` 與 `1301 / CODEX_BOUNDARY_M100_DEFAULT_USED`；相同索引不指定 Default 時沒有執行證據。未出現任何原生資料不足代碼，不能補記 `1401`。
- 同日以長歷史商品台積電（2330）驗證日頻 `[20]`：固定函數與動態 `NumericSeries` 函數都取得 `1301` 路徑哨兵。固定函數使用 `SetBarBack(21, "D")`、單獨 `SetTotalBar(21)`、以及 `SetTotalBar(1)` 搭配 `SetBarBack(21, "D")` 三案皆進入正式路徑。含 `SetTotalBar` 時，XQ 回測視窗停用預先執行筆數欄位；CLI 要求的 5 筆未套用，工具以 `settings_evidence` 明列，而非把預載、`SetTotalBar` 與 `SetBarBack` 視為同一機制。兩個較慢案例先回 `indeterminate_timeout` 並保留 checkpoint，待唯一新報告顯示指定 `1301` marker 後才明確清除；未把 timeout 當成策略結果。
- 目前 XQ 編譯器仍是最終權威。經真實失敗／成功路徑證明的可泛化規則，才可加入 `compiler-lessons.md`。

## 第九階段發布候選閘門

函數矩陣進入發布候選時，先以根目錄 `release/rc-interface-v1.json` 鎖定案例 schema、boundary runner contract、batch contract、baseline／diff schema 及相關 CLI 長選項。`scripts/check_release_candidate.py` 只讀比較，不得因候選程式不同就自動更新契約；任何差異都要先判斷是相容新增、需遷移的契約版本或不相容變更，再人工建立新版凍結檔。

完整矩陣仍只能由第八階段批次 runner 逐 pair 執行。CI、單元測試及 `v0.2.0` 升級／復原演練都不構成函數執行證據；五類所需的 `自訂/CODEX/` 與正式非座標選擇器未全部就緒時，真實 RC 回歸狀態必須是 `blocked`。不得用私人根目錄補跑、不得拆散 pair、不得因任意報告清 checkpoint，也不得把 XQ 未回報的錯誤碼補入 baseline。
