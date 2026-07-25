# XQ 自動交易視窗操作知識

本文件記錄在真實 XQ Windows 桌面中，以 UI Automation 驗證過的自動交易入口與安全操作契約。它只保存穩定控制項屬性與重新表述的操作結果，不保存螢幕座標、帳號、策略內容、庫存或委託資料。

商品盤勢與技術分析頁的委託／成交／MIT 交易訊號標記文件模型另見 [XQ 進階應用官方課程蒸餾](advanced-learning-guide.md)。標記只能作為畫面功能知識，不能代替自動交易回測、成交或復原證據；其中的帳號明細、刪單、全部刪單與下單動作均不在 Codex 授權範圍。

## 驗證紀錄

| 項目 | 紀錄 |
| --- | --- |
| 驗證日期 | 2026-07-20（Asia/Taipei） |
| XQ 版本 | 3.19.03（build 260608） |
| XScript 狀態 | 已開啟交易類型腳本；未修改或編譯腳本 |
| 驗證範圍 | XScript 自動交易入口、回測設定、回測進度與完成報告 |
| 安全處理 | 新增策略設定層以「取消」離開；只執行歷史資料回測，未建立策略、未綁定帳號、未啟動策略、未送單 |

2026-07-21 另以不含交易指令的專用交易腳本驗證回測設定自動填入。測試腳本在目前編譯器以 0 錯誤、0 警告通過；所有測試值都完成寫入、讀回及還原，最後按回測設定的「取消」離開。此次沒有按「開始回測」，也沒有產生進度或報告視窗。

## XScript 上方控制列

畫面上看起來像選單的兩個命令，實際位於 XScript 的 `工具列`，不是包含「檔案／編輯／檢視」的 `MenuBar`。

穩定的父層選擇器：

```json
{
  "xscript_window": {"title_re": "^XScript.*", "control_type": "Window"},
  "top_dock": {"auto_id": "59419", "control_type": "Pane", "class_name": "XTPDockBar"},
  "toolbar": {"auto_id": "1604158800", "control_type": "ToolBar", "class_name": "XTPToolBar"}
}
```

兩個按鈕沒有穩定 `auto_id`，UI Automation 回報的原始名稱含前後空白。因此應先限定父層工具列，再以正規表示式比對標題：

| 動作 | 子控制項選擇器 |
| --- | --- |
| 加入自動交易 | `title_re: ^\s*加入自動交易\s*$`、`control_type: Button` |
| 開啟自動交易中心 | `title_re: ^\s*自動交易中心\s*$`、`control_type: Button` |

不得保存或依賴本次量測到的矩形座標。操作前必須確認按鈕 `visible`、`enabled`，並確認目前活動文件是交易類型；本次只驗證交易腳本情境，其他腳本類型是否可用仍屬未驗證。

## 「加入自動交易」流程

在活動交易腳本按下「加入自動交易」後，觀察到以下狀態：

1. 開啟頂層視窗 `自動交易中心 - XQ全球贏家(個人版)`。
2. 自動交易中心主視窗暫時為 disabled，表示前方存在模式化的新增策略設定層。
3. 設定層可辨識的導覽項目為：策略名稱、選擇腳本、執行商品、帳號設定、交易安控、進出場。
4. 設定層有 enabled 的「確認」與「取消」按鈕；兩者沒有觀察到穩定 `auto_id`。
5. 按下「取消」後設定層關閉，主視窗恢復 enabled，沒有建立策略。

安全自動化規則：

- 「加入自動交易」只授權開啟與檢視，不等於授權按「確認」。
- 未取得策略名稱、商品、頻率、部位來源、帳號環境、安控與風險設定前，不得確認建立。
- 學習、探測或測試流程一律以「取消」結束，並驗證主視窗恢復 enabled。
- 不得為了確認 UI 流程而選擇真實帳號、庫存同步或啟動策略。

## 「自動交易中心」入口

獨立按下「自動交易中心」後，觀察到：

- 開啟且只有一個符合 `^自動交易中心 - XQ全球贏家.*` 的可見頂層視窗。
- 視窗 `control_type` 與 `class_name` 均為 `Window`。
- 視窗為 enabled，沒有自動帶出新增策略設定層。
- 此入口與「加入自動交易」的差異，是只開啟管理中心，不預先進入建立策略流程。

主視窗目前可用的穩定按鈕：

| 標題 | `auto_id` | 本次允許範圍 |
| --- | --- | --- |
| 新增 | `NewStrategyButton` | 未操作 |
| 匯入 | `ImportButton` | 未操作 |
| 匯出 | `ExportButton` | 未操作 |
| 腳本編輯器 | `ScriptEditorButton` | 未操作 |
| 幫助 | `HelpButton` | 未操作 |
| 執行總覽 | `ExecutionButton` | 只觀察控制項；未開啟 |
| 關閉視窗 | `CloseButton` | 已用於安全關閉後重測入口 |

`執行總覽` 標題會包含目前執行中數量，例如 `執行總覽(0)`，因此應用 `auto_id: ExecutionButton`，不可用完整動態標題。

## 驗證後狀態

驗證結束時，自動交易中心由獨立入口開啟並保留在畫面上。沒有新增策略設定層，沒有策略建立、啟動、排程、帳號、庫存或委託異動。

## 下一批視窗學習

後續應依使用者逐項授權再探測：

1. 新增策略設定的六個區段及欄位驗證。
2. 回測入口與回測設定。
3. 商品監控與執行紀錄。
4. 排程與執行總覽。

任何「確認」、「啟動策略」、「全部停止」、帳號選擇或庫存同步操作，都必須另行取得明確授權。

## 自動交易回測設定視窗

### 已驗證的開啟與取消流程

在活動交易腳本按下 XScript 工具列的「回測」後，會出現 XScript 內的模式視窗：

```json
{
  "title_re": "^執行回測\\[策略\\]：.*",
  "control_type": "Window",
  "class_name": "#32770"
}
```

視窗開啟時 XScript 主視窗為 disabled。`開始回測`（control ID `2033`）即使可用，也不表示已取得執行授權；學習流程使用 `取消`（control ID `2034`）離開。取消後已驗證：XScript 恢復 enabled、設定視窗消失，而且沒有回測執行狀態或回測報告視窗。

### 基本回測範圍

| 欄位 | 控制項 | 可選內容／單位 | 操作契約 |
| --- | --- | --- | --- |
| 執行頻率 | ComboBox `2091` | 1、2、3、5、10、15、20、30、45、60 分鐘或日 | 必須與腳本、欄位及商品支援頻率一致。 |
| 價格基礎 | RadioButton `2069`／`2070` | 原始值／還原值 | 股票除權息相關回測須明確記錄；不可把目前選取值當通用預設。 |
| 模擬逐筆洗價 | CheckBox `2121` | 開／關 | 影響洗價粒度及成交判斷；不是實際歷史 Tick 完整重播的保證。 |
| 每日部位歸零 | CheckBox `2122` | 開／關 | 只屬回測清倉假設，不等同實盤腳本有收盤平倉保障。 |
| 開始日期 | DateTimePicker `2200` | 日期 | 與結束日期共同定義正式績效區間。 |
| 結束日期 | DateTimePicker `2201` | 日期 | 不得假設包含尚未完成的當日資料。 |
| 預先執行筆數 | Edit `2007` | 非負整數筆數 | 正式區間前的暖機資料，用於指標與狀態初始化，不納入正式績效區間。 |

### 商品與腳本

| 欄位 | 控制項 | 可選內容／結構 | 操作契約 |
| --- | --- | --- | --- |
| 執行商品來源 | ComboBox `2092` | 商品、組合、選股、庫存、檔案 | 選擇來源後仍需使用「設定」核對實際商品集合。 |
| 商品摘要 | Static `2001` | 動態商品或集合名稱 | 屬使用者設定，不得寫入知識庫或日誌。 |
| 商品設定 | Button `2031` | 開啟來源設定 | 本次未開啟子視窗。 |
| 交易腳本 | Group `2222`、Edit `2008` | 動態腳本名稱 | 只確認目前活動交易腳本，不保存名稱或程式內容。 |
| 腳本參數 | ListView `45243` | 兩欄：參數名稱與參數值 | 列數及值由腳本 `input` 動態決定；執行前須逐項核對。 |

### 策略安全設定

| 限制 | CheckBox | 數值 Edit | 驗證規則 |
| --- | --- | --- | --- |
| 單一商品最大限制部位 | `2124` | `2004` | 同時讀取勾選狀態與數值。 |
| 單一商品每日最多進場次數 | `2125` | `2005` | 同時讀取勾選狀態與數值。 |
| 單一商品每分鐘最多交易次數 | `2126` | `2006` | 同時讀取勾選狀態與數值。 |

數值輸入框可能在限制未勾選時仍保持 enabled，因此不能只依輸入框狀態判斷限制是否生效。執行回測前必須分別記錄 checkbox 的 toggle state 與數值；目前畫面值屬使用者策略設定，不得保存為專案預設。

### 未指定委託價格時的模擬設定

| 欄位 | 控制項 | 選項／單位 |
| --- | --- | --- |
| 預設買進價格 | ComboBox `2093` | 觸發價、市價 |
| 買進價位移 | Edit `2009` | `+/-` 檔數 |
| 預設賣出價格 | ComboBox `2094` | 觸發價、市價 |
| 賣出價位移 | Edit `2010` | `+/-` 檔數 |

這一區只有腳本未提供委託價格時才接管價格。實測切換至市價後，檔數輸入框仍保持 enabled，因此自動化不能由 enabled 狀態推定檔數會被採用；應依價格選項決定是否解讀位移值。

### 資金、成交、費用與其他選項

| 欄位 | 控制項 | 單位／影響 |
| --- | --- | --- |
| 初始資金 | Edit `2016` | 萬元；介面標示只用於簡單報酬率計算，不代表資金不足會阻止交易。 |
| 觸發即判斷成交 | CheckBox `2123` | 決定同次觸發是否立即撮合；會改變成交時點與價格。 |
| 股票單邊交易費用 | Edit `2014` | `%`。 |
| 期貨單邊交易費用 | Edit `2015` | 元。 |
| 啟動腳本內 Print | CheckBox `2131` | 可能增加回測時間及產生日誌；不得輸出敏感資訊。 |
| 美股全部時段 | CheckBox `2127` | 盤前、盤中、盤後；僅在相應商品與資料支援下有意義。 |
| 委託直接送出 | CheckBox `2128` | 不檢查漲跌停限制；屬高風險成交假設，預設不得自行啟用。 |

### 自動填入欄位的實測契約

固定欄位已在真實 XQ 完成「寫入 → 讀回 → 還原」驗證。自動化必須依控制項語意操作，不能只輸入後假設成功：

| 控制項 | 寫入方式 | 成功證據 |
| --- | --- | --- |
| ComboBox `2091`、`2093`、`2094` | 先核對 `item_texts`，再依語意選取頻率或價格模式 | `selected_text`／`selected_index` 與要求一致 |
| RadioButton `2069`、`2070` | 點擊目標選項 | 目標為 1、另一選項為 0 |
| 各 CheckBox | 僅在目前狀態不同時點擊 | `get_check_state()` 與要求一致；不能用 enabled 推定勾選狀態 |
| Edit `2004`–`2016` 等數值欄 | `set_edit_text` | 立即讀回的文字與正規化後要求值一致 |
| DateTimePicker `2200`、`2201` | 使用原生日期訊息設定年月日 | `get_time` 與畫面日期都符合，且開始日不晚於結束日 |

價格欄位有相依順序：先設定 `2093`／`2094`。選擇「觸發價」時才填 `2009`／`2010` 的檔數；選擇「市價」後兩個檔數欄會變成 invisible，但仍可能回報 enabled。因此工具必須依價格模式決定是否填值，不得對 invisible 控制項強行操作。

RadioButton 與一般 CheckBox 雖然同為 Win32 `Button`，仍要分開驗證互斥狀態。任何子設定視窗開啟時，回測設定父視窗會 disabled；此時不得繼續操作父視窗，否則 XQ 會提示先關閉尚未關閉的對話窗。

### 執行商品來源的模式視窗

選取 ComboBox `2092` 的任一來源會立即開啟對應模式視窗，即使再次選取目前的「商品」也一樣。父視窗須等子視窗「完成」或「取消」後才能繼續。各來源的穩定結構如下；清單內容、帳號及路徑都是使用者資料，不得記錄：

| 來源 | 已觀察的控制項 | 驗證範圍 |
| --- | --- | --- |
| 商品 | 查詢 Edit `741`、查詢 Button `802`、結果 ListView `782`、加入選取 `803`、已選 ListBox `781`、全部刪除 `805`、完成 `1`、取消 `806` | 已用公開測試商品完成查詢、選取、加入及套用；整個回測視窗最後取消。 |
| 組合 | 搜尋 Edit `741`、分類 ListBox `781`、組合 ListBox `783`、完成 `1`、取消 `2` | 只驗證開啟與取消；沒有讀取或選擇使用者組合。 |
| 選股 | 搜尋 Edit `19901`、分類 TreeView `19902`、清單 ListBox `19903`、完成 `1`、取消 `2` | 只驗證開啟與取消；沒有讀取或選擇私人選股法。 |
| 庫存 | 交易帳號設定 Button `1010`、確認 `1`、取消 `2` | 只驗證開啟與取消；不得讀取、輸出或自行選擇帳號。 |
| 檔案 | 標題 `從檔案匯入`、開啟 `1`、取消 `2` | 只驗證開啟與取消；接受格式仍為 `.txt`／`.csv`，不得自行挑選本機檔案。 |

自動化若要完成組合、選股、庫存或檔案來源，必須取得明確且非敏感的目標識別，選取後再讀回摘要；目前只能把這四條標為「模式視窗可開啟與復原」，不能聲稱完整選擇流程已驗證。

### 動態腳本參數表

腳本參數位於 ListView `45243`，第一欄是腳本提供的顯示名稱，第二欄是目前值。列數與順序會隨活動腳本變化，不能固定用第 N 列代表某一參數。

已用含兩個數值輸入的無交易測試腳本驗證下列流程：

1. 讀取兩欄，依第一欄顯示名稱建立唯一參數對應；名稱缺少或重複時停止，不猜測列號。
2. 從當下 `column_widths()` 與 `get_item_rect(row)` 動態計算第二欄儲存格位置，不能保存固定螢幕座標。
3. 雙擊第二欄後，ListView 內會建立 visible 的 Edit `45041`。
4. 寫入新值並送出 Enter，再從第二欄讀回；本次整數與小數都成功提交及還原。

目前只驗證數值輸入。布林、字串、日期、列舉型參數，以及輸入越界時的 XQ 驗證訊息仍屬未驗證；工具遇到未知編輯器型態時必須停止，不能當成一般文字欄位硬填。

### 建議的完整填入順序與回復

1. 確認活動文件是已編譯成功的交易腳本，開啟唯一回測設定視窗。
2. 先處理商品來源及其模式視窗，完成後確認父視窗重新 enabled。
3. 填頻率、價格基礎、洗價、日期與暖機筆數。
4. 填三項安全限制；分別驗證勾選狀態與數值。
5. 先選買賣價格模式，再依模式決定是否填檔數。
6. 填初始資金、成交判定、交易費用、Print、美股時段及委託限制。
7. 依參數名稱填腳本參數；逐列讀回。
8. 對整份設定建立不含商品、帳號及私人參數值的驗證摘要。未取得「開始回測」授權時，一律按 `2034` 取消。

取消後必須同時驗證：設定視窗消失、XScript 恢復 enabled，而且沒有 `回測執行狀態` 或新回測報告。若中途失敗，先關閉最內層模式視窗，再取消父設定視窗；不能在 disabled 的父視窗繼續點擊。

### 開始回測與進度視窗

取得使用者執行授權並核對設定後，按下 `開始回測`（control ID `2033`）會建立獨立的 `回測執行狀態` 視窗：

```json
{
  "title": "回測執行狀態",
  "control_type": "Window",
  "class_name": "#32770"
}
```

進度視窗每列包含 `啟動時間`、`腳本名稱`、`執行狀態` 與百分比進度。實測到的穩定結構如下：

| 元素 | 控制項／外觀 | 操作契約 |
| --- | --- | --- |
| 執行清單 | `SysListView32`，control ID `3002` | 不得把清單為空當成成功；完成可能非常快，應同時監控報告視窗。 |
| 清單內容區 | `AfxWnd140`，control ID `3001` | 內含每個腳本的動態列，不保存名稱、時間或商品。 |
| 欄位標題 | Static：啟動時間、腳本名稱、執行狀態 | 用標題確認欄位語意，不依賴欄寬或座標。 |
| 進度 | `msctls_progress32` | 同時讀取狀態文字及百分比；僅看到 `100%` 仍不等於報告已成功建立。 |
| 展開 | 每列左側藍色箭頭按鈕 | 用於展開該列細節；本批未展開。 |
| 取消 | 每列右側紅色叉號按鈕 | 會中止進行中的回測；已驗證確認提示、未保留部分結果及介面復原。 |

回測可能在數秒內完成。以高頻輪詢於按下開始後約百毫秒捕捉到進度視窗；完成後該視窗自動隱藏。因此不能用固定等待秒數推定「沒有進度視窗」，也不能只等待它消失就宣稱成功。完成後還必須讀取新報告中的商品執行狀態；報告視窗出現本身不是成功證據。

### 自動啟動與終態判定

2026-07-21 另以公開測試商品、單一交易日及不含交易指令的腳本實測自動啟動。按 `2033` 後設定視窗關閉，會顯示 `回測執行狀態`。摘要進度條可能持續顯示 0，但展開商品明細後可讀到 `執行中`；因此 0% 不能單獨解讀成尚未啟動或失敗。

進度列的兩個圖示按鈕在不同執行中觀察到 control ID 從 `5001` 變成 `5002`，屬動態值，不可寫死。應限定在 visible 的進度視窗內，取得同一列兩個 visible Button，依當下矩形排序：左側是展開、右側是中止。這只是相對控制項幾何，不得保存成螢幕座標。

左側展開後，ListView `3002` 由 hidden 變為 visible；本次商品明細是兩欄，第二欄含執行狀態。列數與商品屬使用者資料，不得保存；判定器只保留正規化狀態，例如 `執行中`、`完成`、`失敗`、`錯誤` 或 `終止`。

自動化必須回傳至少五種結果，不能壓成布林值：

| 結果 | 必要證據 | 禁止的推定 |
| --- | --- | --- |
| `success` | 本次啟動後出現新報告，商品執行狀態至少一筆成功且沒有失敗 | 不能只依報告出現、進度 100%、進度視窗消失或等待結束判成功 |
| `failure` | 新報告的商品執行狀態有失敗且沒有成功，或 XQ 顯示明確錯誤模式窗 | 不能把時間超過門檻或 0% 當失敗 |
| `partial_failure` | 新報告同時有成功與失敗商品 | 不能把有任一成功商品的報告整體標成成功 |
| `indeterminate_timeout` | 超過使用者或工具限制時間，商品仍為 `執行中`，且沒有新報告或錯誤 | 不得自動修改腳本來掩蓋服務、資料或環境等待 |
| `cancelled` | 使用者或工具明確確認中止，且進度視窗不再 visible | hidden 的同名容器不代表仍有可見工作，也不能當成功報告 |

判定器在按開始前須記錄現有頂層視窗 handle；本次報告必須是啟動後新增的可見視窗，避免把舊報告誤認為新結果。報告的實際頂層類別是 `#32770`，內含 `Chrome_WidgetWin_1`，並以 `Chrome_RenderWidgetHostHWND` 承載可存取的 `XS回測報告` Document；不能誤把內層 Chromium 類別當作頂層選擇器。輪詢時同時檢查：visible 進度視窗、展開明細狀態、新模式窗與新的報告候選。

報告上方的商品執行狀態會以可存取的 DataItem／Hyperlink 呈現，例如成功案例的 `1(成功)`，以及失敗案例的 `0(成功)1(失敗)`。解析器應擷取成功與失敗數量；缺少失敗片段時視為零，但缺少全部狀態、數量無法解析或成功與失敗皆為零時，不得判為成功。視窗標題及腳本／商品名稱只在記憶體中比對，不寫入共用知識或日誌。

2026-07-21 重啟 XQ 後，以公開商品及明確進出場腳本重新驗證：進度視窗約兩秒內消失，新報告顯示 `1(成功)`，且總交易次數為 21，故可判為 `success`。同一環境再以可編譯、呼叫 `RaiseRunTimeError` 的安全測試腳本驗證，仍會建立新報告，但商品狀態為 `0(成功)1(失敗)`、總交易次數為 0，故應判為 `failure`；這證明「新報告可見」不足以代表成功。完成測試後，活動 XScript 文件已恢復成明確進出場版本並重新編譯為 0 錯誤、0 警告。

2026-07-22 的資料不足切片另發現：台積電 1 分鐘回測若函數要求日頻 10,000 根歷史，固定索引與動態索引兩案都建立 `1(成功)`、0 交易報告，但 caller 最外層的無條件 `RaiseRunTimeError` 哨兵未執行；相同設定改為日頻 100 根後，哨兵立即以 `1301` 出現在失敗明細。故商品層級成功只表示 XQ 未把商品列為失敗，不證明正式區間至少執行過一根。資料不足、初始化與函數邊界測試必須加入可觀察路徑哨兵及足量控制組；哨兵未執行時不得宣稱函數回傳值、`Default` 行為或原生錯誤代碼已獲證明。

2026-07-22 的第三階段另確認：自動交易腳本含 `SetTotalBar` 時，XQ 3.19.03 會停用回測視窗 Edit `2007`（預先執行筆數）。工具不可對停用控制項呼叫 `set_edit_text`；`xq_backtest.py` 現在略過該欄位並回傳 `settings_evidence.preload_control_enabled`、`preload_records_requested` 與 `preload_records_applied`。`preload_records_applied: false` 必須明確解讀成 CLI 值未套用，不能說它已被 `SetTotalBar` 取代或等價。台積電日頻 `[20]` 實測中，`SetTotalBar(21)` 單獨使用與 `SetTotalBar(1)` 搭配 `SetBarBack(21, "D")` 都取得指定 `1301` 路徑哨兵，但此結果僅涵蓋該固定函數、商品、日期與版本。

### 中止尚未完成的回測

點進度列右側按鈕會出現確認模式窗，文字說明回測尚未完成，並詢問是否停止。穩定控制項如下：

| 控制項 | ID | 契約 |
| --- | --- | --- |
| 顯示已完成結果 | CheckBox `3003` | 本次預設未勾選；是否產生部分報告取決於此狀態，不能自行開啟。 |
| 確定 | Button `1` | 明確中止；按下前應確認這是本次啟動的工作。 |
| 取消 | Button `2` | 返回進度視窗，不中止。 |

確認中止後，`回測執行狀態` 頂層容器可能仍存在但變成 invisible，且其子控制項也不可見。因此活動工作檢查必須要求視窗 `visible = true`；只按標題列舉到 hidden 容器不能判定回測仍在執行。勾選顯示已完成結果只代表提出要求，不保證 XQ 必然建立部分報告；兩者必須分開取證。

2026-07-21 已用 XQ 3.19.03、公開測試商品、1 分鐘頻率及較長歷史區間驗證第一階段的自動中止與復原。工具只鎖定本次啟動後新增的 visible 進度視窗，在 control ID `3001` 的內容區取得同列兩個按鈕並選最右側中止；確認窗出現後，明確把 CheckBox `3003` 維持為未勾選，再按 Button `1`。結果證據為 `confirmation_seen: true`、`partial_results_requested: false`、`progress_closed: true`、`xscript_ready: true`、`partial_report_seen: false`，因此 `recovery_complete: true`。舊報告不算本次部分報告，判定前必須保存既有頂層 handle 並排除。

2026-07-21 第二階段改用多公開商品與事件驅動中止。`--product` 可重複指定，但每筆仍須在查詢結果中唯一完全相符，選取後再核對完整代碼集合；多商品父摘要不保證逐筆列出代碼，因此只用它確認父視窗恢復 enabled 且摘要非空。工具展開 ListView `3002`，只保留匿名化狀態文字；`--cancel-after-completed-products` 僅在完成數達門檻且仍有其他商品未完成時觸發，避免固定秒數猜測。

真實案例曾在 10 商品中觀察到 `1` 筆「完成」與 `9` 筆「執行中」，也在 20 商品中觀察到 `3` 筆「完成」與 `17` 筆「執行中」。CheckBox `3003` 可成功維持勾選，進度視窗關閉且 XScript 恢復 enabled；其中一次新部分報告延遲超過原 10 秒觀察窗後才出現，但其他重複案例即使等待 30 秒仍未建立報告。因此輸出必須分開記錄 `partial_results_requested`、`partial_results_request_succeeded`、`partial_report_seen`、`partial_report_summary_available` 與摘要計數。只有報告實際出現且符合要求時，`recovery_complete` 才能為 true；沒有報告時即使 UI 已復原也維持 false，不能捏造部分績效。

2026-07-21 第三階段以多公開商品、1 分鐘長區間與 `--timeout-seconds 2 --cancel-on-timeout` 驗證真正的逾時接管。監控期限到達時仍有 visible 進度工作，工具才進入中止；結果為 `cancel_reason: timeout`、`timeout_seconds: 2.0`、`confirmation_seen: true`、`partial_results_requested: false`、`progress_closed: true`、`xscript_ready: true`、`partial_report_seen: false` 及 `recovery_complete: true`。監控期限只決定何時停止等待終態，中止後另給 10 秒 UI 復原窗，不能把 2 秒監控期限重複用於確認窗與復原而製造假失敗。若期限到達時沒有唯一 visible 進度視窗，仍須回傳 `indeterminate_timeout`，不得猜測要操作哪個工作。

### 回測報告視窗

完成或執行失敗後都可能開啟獨立報告視窗。標題包含動態腳本名稱、執行時間及是否儲存，不能以完整標題作固定選擇器，也不得把這些動態值寫入知識庫。頂層是 `#32770`，內容由其下的 `Chrome_WidgetWin_1`／`Chrome_RenderWidgetHostHWND` 承載；本次 UI Automation 已可讀到報告內按鈕、DataItem 與 Hyperlink。若可存取樹暫時不完整，應重試並驗證結構，不能退回固定座標或擷取完整 DOM；策略名稱、商品、交易紀錄或績效數字不得保存。

關閉未儲存報告會在 Chromium 內容內顯示「是否要儲存回測報告？」；頂層 `WM_CLOSE` 返回不代表報告已清除。測試 runner 只能對本次 manifest 的精確 handle 操作，動態驗證唯一「不儲存」按鈕後點擊，並等待報告 Document 消失才算完成；候選缺失或不唯一時必須拒絕。

報告固定入口與已驗證選項：

| 入口 | 內容／選項 |
| --- | --- |
| 儲存 | 保存報告；本批未按，不得自行覆寫既有檔案。 |
| 匯出 | `完整匯出`、`僅匯出交易紀錄`；本批只展開確認選項，未產生檔案。 |
| 重新回測 | 返回相同策略的 `執行回測[策略]` 設定視窗；使用者仍須重新核對設定。 |
| 整體統計 | 可切換全部／做多／做空、百分比／金額、最大投入報酬率／時間加權報酬率／淨利。 |
| 每日報表 | 逐日結果頁。 |
| 商品統計表 | 可切換百分比／金額及全部／做多／做空。 |
| 商品分析 | 可切換全部／做多／做空、百分比／金額、報酬指標，以及走勢圖／明細表。 |
| 交易分析 | 可切換全部／賺錢／賠錢。 |
| 腳本資料 | 顯示腳本相關回測資料；不得擷取或保存私人策略內容。 |
| 週期分析 | 可切換日／月／季／年、百分比／金額，並提供日期、星期、平均與總計等檢視。 |

報告上方另有回測資料範圍、執行時間、執行商品狀態及交易設定摘要。商品狀態連結可提供成功／失敗數量；本批已驗證純成功與純失敗兩種摘要。點擊非零的失敗 Hyperlink 後，會開啟報告內的明細層，其 Table 固定以 `商品名稱`、`狀態`、`說明` 三個 Header 開頭，每一列是三個對應 DataItem。明細層以名稱為 `Close` 的 Button 關閉，關閉後返回原報告。

安全 `RaiseRunTimeError` 案例的說明欄包含 `[(1301)RaiseRunTimeError:<自訂訊息>]`，因此解析器應從當次說明欄擷取括號內代碼並保留 XQ 原始說明；沒有符合格式時回傳空代碼，不能查表猜測。逐商品明細只回傳給本次呼叫者，不寫入共用知識或日誌。報告中的績效、商品、參數與交易紀錄均屬本次使用者資料，不可加入共用知識。

### 可復原的設定缺件流程

已安全驗證一條不會進入回測的缺件路徑：將商品來源切換為 `檔案`，尚未提供檔案時按開始，會先開啟標題為 `從檔案匯入` 的系統檔案選擇器，只接受 `文字檔案 (*.txt, *.csv)`。按 `取消`（control ID `2`）會返回 disabled 狀態解除後的回測設定；再按設定視窗的 `取消`（control ID `2034`）即可捨棄暫時選擇。不得替使用者猜測或自行挑選本機檔案。

### 尚未驗證的錯誤與停止路徑

下列狀態需要專門的非交易測試腳本或較長回測才能安全驗證，本批不做推測：

1. 除回測 `1301` 外的腳本執行期錯誤代碼、策略實際執行流程的錯誤明細，以及錯誤後重試行為。
2. 商品資料缺漏、下載失敗或部分商品失敗時的報告呈現。
3. 工具主動中止、未勾選時無部分報告，以及勾選後 XQ 可能延遲或不建立部分報告的條件性行為已驗證；部分報告摘要的同次穩定擷取仍待更多案例驗證。
4. 回測監控逾時後的明確中止與復原已驗證；XQ 行程／視窗故障分類與 checkpoint 已實作，但實際關閉、當機或網路中斷後的復原仍未做故障注入驗證。
5. XQ 原生「儲存／完整匯出／僅匯出交易紀錄」已完成實檔、格式、完成提示及介面復原驗證；同名檔案的 XQ 原生覆寫提示未刻意觸發，工具以唯一檔名與建立前檢查避開，不得自動確認覆寫。

每次真正執行前，仍必須由使用者確認日期、頻率、商品、價格基礎、洗價模式、暖機筆數、腳本參數、三項安全限制、預設委託價、初始資金、成交判定與交易費用。回測完成只證明歷史模擬產生報告，不證明策略獲利、實盤安全或可以啟動自動交易。

### 可重用回測 CLI

`scripts/xq_backtest.py` 已把本章驗證過的單一公開商品流程實作成單一 JSON CLI。它要求活動文件為交易腳本，以控制 ID 填寫並讀回設定；商品查詢必須得到唯一的代碼完全相符列，套用後再由父視窗摘要確認。`--dry-run` 只填入、驗證並取消，正式啟動則在按下開始前記錄所有可見頂層 handle，以排除舊報告。

報告候選必須是新增且可見的頂層 `#32770`，並包含名稱為 `XS回測報告` 的 `Chrome_RenderWidgetHostHWND` Document。工具從 DataItem 優先解析成功／失敗數量及總交易次數，再依本章五態契約分類。只要失敗數大於零，工具會開啟失敗 Hyperlink，依三欄表格輸出 `failure_details`；每列包含商品、狀態、當次畫面擷取的 `error_code` 與完整說明，完成後關閉明細層。若明細擷取失敗，仍保留正確的總體失敗分類，另回傳 `failure_detail_capture_error`，不能捏造代碼。

若只出現明確錯誤模式窗，分類為 `failure`，若逾時則保守回傳 `indeterminate_timeout`。只有明確使用 `--cancel-after-seconds`、`--cancel-after-completed-products` 或 `--cancel-on-timeout` 時，工具才會進入本次新增的進度內容區、選取同列最右側中止按鈕並確認停止。預設不保留部分結果；只有另加 `--show-partial-results-on-cancel` 才勾選。取消結果會輸出確認、實際核取狀態、要求是否成功、匿名進度狀態、進度關閉、XScript 可用、部分報告及可解析摘要；不能只看到 `cancelled` 就宣稱完整復原或報告成功。

`--cancel-on-timeout` 只在期限到達且仍能唯一辨識本次 visible 進度視窗時執行。輸出的 `timeout_seconds` 是監控期限，`cancel_reason: timeout` 是逾時接管證據；後續確認與復原使用獨立安全窗口。沒有可辨識工作時保持 `indeterminate_timeout` 且 `cancelled_by_tool: false`，不能把「沒有看見進度」說成已中止。

### 環境復原第一、二階段

`xq_backtest.py` 已加入不依賴策略內容的 runtime 心跳。每 0.5 秒以 Win32 頂層視窗、原始 XQ PID 與 `IsHungAppWindow` 重新取證，不沿用心跳前的 wrapper 來宣稱環境正常。分類契約如下：

| `failure_kind` | 必要證據 | 不可推定 |
| --- | --- | --- |
| `xq_process_exited` | 開始時記錄的 XQ PID 已不再存活 | 只能證明行程退出，不能自行宣稱是當機或使用者關閉 |
| `xq_unresponsive` | XQ 或 XScript handle 被 Windows 判定 hung | 不能把長回測、0% 或資料等待當成無回應 |
| `xq_window_missing` | 原 PID 仍在，但校正過的 XQ 頂層視窗不存在 | 可能是視窗或版本改變，不能當成網路中斷 |
| `xscript_closed` | XQ PID 仍在且主視窗存在，但 XScript 頂層視窗不存在 | 不代表回測一定已停止 |
| `environment_unknown` | 無法取得可追蹤的 XQ PID | 不猜測成當機、關閉或斷網 |

命中上述證據時輸出 `environment_interruption`、`last_safe_stage` 與當次 runtime snapshot，停止操作失效 handle，且不自動重跑。網路中斷尚未納入此分類；沒有 XQ 錯誤視窗、錯誤代碼或明確故障注入證據時，不能只因進度停滯就標成網路問題。

正式按開始前會在設定檔同目錄原子寫入 `recovery-state.json`。schema v2 只允許：版本、隨機 run ID、`starting`／`running`／`cancelling`／`interrupted` 階段、UTC 時間、XQ PID、XQ／XScript／進度 handle、開始前可見報告 handle 清單，以及「已嘗試開始／已確認中止」布林值。商品、腳本名稱或正文、參數、帳號與績效都不在 schema；未知欄位或損壞 JSON 會以 `checkpoint_invalid` 阻止執行。檔案位於已由 `.gitignore` 排除的 `.xq-auto-writer/`，不得提交。

只有 `success`、`failure`、`partial_failure` 或已確認的 `cancelled` 會自動刪除 checkpoint。`indeterminate_timeout`、環境中斷或開始後的未知自動化例外會保留，以防下次重複建立工作。啟動前若發現 stale checkpoint：有 visible 進度一定阻止；無 visible 進度但舊 PID 仍存活時也保守阻止；舊 PID 已消失且沒有進度才可自動清除。使用者另加 `--acknowledge-stale-checkpoint` 時，可在沒有 visible 進度的前提下明確清除同 PID 狀態，之後仍重新做完整 preflight，不會直接重播原回測。

2026-07-21 已以真實 XQ 3.19.03 驗證健康生命週期：安全回測在 2 秒監控逾時後明確中止，回傳 `recovery_checkpoint_retained: false`，檔案確實移除。另建立不含策略資料的模擬 stale checkpoint；舊 PID 存活且無 visible 進度時，CLI 在開啟設定前回傳 `environment_interruption`／`stale_checkpoint`。加入 `--acknowledge-stale-checkpoint` 後，工具清除測試狀態、重新 preflight，並以 dry-run 填入後取消，回傳 `stale_checkpoint_cleared: true`。實際關閉、強制終止 XQ 或中斷網路可能中斷 Codex 工作階段，因此明確排除於驗證範圍；各故障分類只要求安全的依賴注入與人工 checkpoint 測試證據，不宣稱真實故障注入已驗證。

目前 CLI 限定一至二十個明確公開代碼的「商品」來源及固定欄位；組合、選股、庫存、檔案來源與動態腳本參數尚未納入。特別是庫存與帳號仍屬禁止自動選擇範圍，不能用此工具延伸成實盤啟動授權。

2026-07-21 已以目前 XQ 3.19.03 對 CLI 本身完成真實驗證：同一組公開測試設定先以 `--dry-run` 成功填入、讀回並取消，再正式啟動；工具捕捉到進度視窗，並從新報告回傳成功 1、失敗 0、總交易次數 21。另以 `RaiseRunTimeError` 安全案例驗證失敗路徑，CLI 回傳成功 0、失敗 1、總交易次數 0，且逐商品明細取得 `1301` 與 XQ 原始說明。第一階段另以 `--cancel-after-seconds` 驗證主動中止，取得確認窗、未要求部分結果、進度關閉、XScript 可用及無新增部分報告的完整復原證據。這只驗證 CLI 能正確操作與分類這些安全案例，不代表其他商品、週期、資料範圍、錯誤代碼或策略結果必然相同。

### 唯讀復原診斷與安全決策

第三階段加入 `--recovery-status`。這個模式只讀取本機 checkpoint、XQ 行程／視窗、可見回測進度及已開啟的回測報告摘要，不需要 `--product`、週期或日期，也不會開啟回測設定、點擊控制項、清除 checkpoint、中止工作或啟動回測。它不可與 `--dry-run`、任何中止選項或 `--acknowledge-stale-checkpoint` 併用。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_backtest.py `
  --config .xq-auto-writer/xq-ui.json `
  --recovery-status
```

輸出維持單一 JSON；頂層 `status: success` 只代表唯讀檢查正常完成，不能解讀成允許啟動回測，後續授權只看 `decision`。證據包含 `evaluated_at`、`reason_codes`、`recommended_action`、checkpoint 驗證狀態、saved PID 是否存活、runtime snapshot、可見進度與報告摘要，以及任何 `inspection_errors`。決策契約如下：

| `decision` | 判定 | 允許動作 |
| --- | --- | --- |
| `safe_to_start` | 沒有 checkpoint、沒有進度且 XQ／XScript 健康 | 完整確認新回測設定後才可啟動 |
| `monitor_existing` | 有可見進度且 runtime 證據一致 | 只監控既有工作，不得重複啟動 |
| `safe_to_clear_checkpoint` | 沒有進度，且回測未開始或 saved PID 已不存在 | 仍須明確使用者確認後才可清除 |
| `ui_recovery_required` | XQ 行程仍在，但 XQ 或 XScript 視窗需復原 | 復原 UI 後重新執行唯讀診斷 |
| `manual_review_required` | checkpoint 仍可能存活、證據衝突、格式錯誤或檢查不完整 | 保留現況並人工核對，不得重跑 |

可見報告會讀取 handle、成功／失敗商品數與交易次數，但 checkpoint 為避免保存策略與商品資訊，無法證明既有報告屬於哪一次 run。因此輸出固定揭露 `report_checkpoint_association_proven: false`，不利用報告自行清除 checkpoint；`automatic_replay_allowed` 永遠為 `false`。

第四階段將 checkpoint 提升為 schema v2，新增 `baseline_report_handles`：在按下開始回測前，先列出當時可見的報告 handle 並原子寫入 checkpoint。此欄位只保存正整數 handle，不含標題、商品、腳本、參數或績效。一般 `--recovery-status` 仍沒有案例預期 marker，因此即使看到相對基準的新報告也不得自行清除 checkpoint，`report_checkpoint_association_proven` 仍維持 false。

只有受控的 `xq_function_boundary_runner.py` 同時持有案例的唯一預期 marker。它在逾時後重新列舉報告，排除 checkpoint 基準，並要求候選剛好一份；接著必須從該份報告實際失敗明細讀到完全相同的 marker，才可移除 checkpoint。零份候選、多份候選、marker 不符、明細無法讀取或沒有 XQ 實際代碼時，結果都是 `manual_review_required`，保留 checkpoint 且不重跑。這是案例限定的安全復原，不改變一般唯讀診斷的保守契約。

第五階段加入 manifest 續跑狀態。每案狀態分為 `pending`、`running`、`completed` 或 `failed`，另記錄目前 stage、attempt、開始前報告 baseline、編譯證據及結果；不保存帳號、持倉或策略正文。續跑必須明確傳入同一份 manifest，並驗證案例檔 SHA-256 digest 與逐案契約。`completed` 案永遠跳過；active 案若已開始回測，必須先完成唯一報告＋marker 關聯，不能直接改回 pending。

安全短 timeout 演練使用預期會拋出唯一 marker 的控制案。只有 `xq_backtest.py` 先回傳 `indeterminate_timeout` 且保留 checkpoint，之後新報告相對 baseline 唯一並包含完全相同 marker，才可輸出 `late_recovery_probe.observed: true`。報告在監控期限內正常完成、無報告、兩份以上報告或 marker 不符都不能算演練成功；一般 `--recovery-status` 仍不會自行做案例關聯或重播。

2026-07-23 已以 0.05 秒監控期限在真實 XQ 3.19.03 完成晚到報告演練：runner 先保留 checkpoint，之後只因相對 baseline 唯一新增的 handle 且失敗明細 marker 完全吻合才復原。8 案完成後，唯讀狀態為無 checkpoint、無進度窗、無可見報告；測試報告與文件均依 manifest 名稱、類型及儲存位置讀回後清除。未執行當機或斷網破壞測試，也未由本地資料推測任何 XQ 錯誤碼。

第六階段將回歸比較與 XQ UI 執行分離。`xq_function_regression.py` 只讀 runner JSON，正規化後排除 handle、run ID、文件名稱、商品、日期、時間戳與原始編譯訊息，不開啟或點擊 XQ。XQ、案例 schema 或 runner contract 版本不同時只回報 `version_mismatch`；baseline 更新必須明確確認並寫到新路徑，舊版不可覆寫。只有 boundary runner 會接觸 XQ；`--only-pair` 仍同時包含控制與不足案，manifest schema v3 以選取 pair 集合防止不同子集錯接續跑。

真實 smoke 只使用已知會產生唯一 marker 的代表 pair，使開始後的 timeout 或 handle 失效仍可要求唯一新增報告＋完全相同 marker。模擬 `xq_process_exited`、斷網但無 XQ 錯誤證據、報告不唯一及缺少結果的單元測試，都不得自動重播或產生錯誤碼；後三者保持 `manual_review_required` 或 `evidence_insufficient`。不得為驗證回歸工具而實際終止 XQ、停用網路或破壞目前工作階段。

XQ UI 操作必須節流：函數 boundary runner 的單一步驟至少等待 2 秒，案例間預設等待 5 秒，慢速桌面可提高 `--inter-case-seconds`。不得用密集點擊掃描 XScript 自訂類型分頁。Windows 無回應或 XScript「開啟」對話框 timeout 時，停止後續輸入並將時間、active case／stage、PID、視窗健康、checkpoint、可見報告與唯讀 recovery-status 寫入 `windows_wait_incidents`，向使用者回報後才可評估續跑。

2026-07-23 的第六階段 run `6c85d6c1-c8b2-4ad8-9986-feacd82d4cb5` 完成 4／4 回測後，清理在 3／8 文件時發生一次「開啟」對話框 timeout。當下 recovery-status 為 `safe_to_start`，無 checkpoint、進度窗或可見報告；安全續跑同一 manifest 時沒有重跑 completed 案，最後 8／8 文件與 4 份報告均清除，manifest 與暫存目錄移除。這是實際等待事件，不是破壞性故障注入。

第七階段把慢速桌面行為改為 manifest contract。action settle、初始／最大輪詢間隔、退避倍數、對話框 late threshold／timeout、一般狀態 timeout 及案例間隔全部可調，續跑只能維持或增加等待。輪詢期間不產生鍵盤或滑鼠輸入；Ctrl+O 只送一次，對話框晚到或 timeout 都立即停止，不再用選單作第二次輸入。視窗暫時 disabled 可在正常門檻內只讀等待；超過 late threshold、`WaitGuiThreadIdle` 或 Windows hung 便保存事件。

事件記錄除了 UTC、案例與階段，也包含正在清理的文件名稱／類型及狀態、XQ PID、XQ／XScript visible／enabled／hung 健康、checkpoint、可見報告和完整唯讀 recovery-status。一般 recovery-status 不做 marker 關聯，仍不得因看到報告而清 checkpoint。

XQ 文件清理逐件記錄 `open_requested`、名稱／類型／`自訂/CODEX/` 讀回、刪除確認、刪除後同類型同名零列及 `completed`。若中途停止，續跑先看該狀態；已 `completed` 文件不再開啟或刪除，尚未完成者重新以唯讀識別與不存在檢查起步。這使刪除確認已送出但結果未知時，不會盲目再送 Delete。completed 回測案例與已驗證清理文件都不重跑。

第六階段 baseline 差異會另輸出機器可讀增量計畫。只有同版本 contract 的 `regression` 才可把受影響 pair 轉成 `--only-pair`；版本不一致固定要求完整矩陣，不自動執行部分 pair 或覆寫 baseline。真實 smoke 仍只跑一組代表 pair，且禁止終止 XQ 或斷網作故障注入。

2026-07-23 的第七階段慢速 run `3449ecb6-8822-4ae1-b91e-c6bfa6b73f16` 在 XQ 3.19.03 執行一組 pair／兩案，兩案均第一次完成，四份文件均 0 錯誤、0 警告；兩份報告皆實際取得各自 `1301` marker。逐文件清理的四個狀態全部完成，最後 recovery-status 為 `safe_to_start`、無 checkpoint、進度或報告，私有 manifest 與暫存已移除，等待事件為 0。未注入當機或斷網。

第八階段由 `xq_function_batch_runner.py` 將完整矩陣限制為一次一個 pair。每批前後都以本節的唯讀 recovery-status 閘門要求 `safe_to_start`，pair 之間使用持久 cooldown；任何 child failure、Windows wait incident、版本／digest 不一致或清理不完整都停止後續 pair。續跑以 caller-stable child run ID 找回唯一 boundary manifest，completed pair 的結果則以 SHA-256 固定並跳過。

XScript 建檔與清理現在只接受經校正、唯一讀回的 `自訂/CODEX/`。2026-07-24 初次只讀 TreeView 探測沒有 CODEX 節點；後續使用者在當時可見公式分類手動建立並重新命名，唯讀觀察器已精確讀回 `自訂 > CODEX (0)`，並證明內容選單是標準 `#32768` 且含「新增資料夾」。這只證明該次可見分類，不代表自動交易或其餘四類選擇器完成；第八階段真實矩陣仍依憲法停在建檔前，未建立測試文件、未啟動回測，也不把 `自訂/` 根目錄視為替代。等各類型 CODEX 資料夾及穩定選擇器逐類校正後，才可逐 pair 執行並由完整 contract 7 aggregate 明確建立 baseline-v2。

2026-07-21 已在真實 XQ 3.19.03 執行健康狀態唯讀檢查，得到 `safe_to_start`、`runtime_healthy`、無 checkpoint、無 visible 進度、無可見報告與空白 `inspection_errors`。依使用者安全邊界，真實 XQ 當機、強制關閉及實際斷網不列入驗證範圍；相關分支只以依賴注入及人工 checkpoint 組合測試，不以破壞目前 XQ 或 Codex 工作階段的方式驗證。

### 結構化報告擷取、儲存與匯出

`scripts/xq_report.py` 只處理目前已經可見的回測報告，不會開啟回測設定或啟動新工作。先以 `--list-reports` 唯讀列舉 handle、分類、成功／失敗商品數及總交易次數；沒有報告時回傳 `no_report`，多個報告則必須用正整數 `--report-handle` 明確指定，不用標題或顯示順序猜測。

```powershell
python .agents/skills/xq-xscript-compiler/scripts/xq_report.py `
  --config .xq-auto-writer/xq-ui.json `
  --list-reports

python .agents/skills/xq-xscript-compiler/scripts/xq_report.py `
  --config .xq-auto-writer/xq-ui.json `
  --report-handle <handle> `
  --export-format json

python .agents/skills/xq-xscript-compiler/scripts/xq_report.py `
  --config .xq-auto-writer/xq-ui.json `
  --report-handle <handle> `
  --export-format csv
```

schema 只保存擷取時間、來源、報告 handle、終態分類、成功／失敗數量、總交易次數，以及使用者明確要求時的失敗商品、狀態、錯誤代碼與 XQ 說明。視窗標題、腳本名稱、腳本正文、參數、帳號、raw DOM 與完整 accessibility tree 明確排除。CSV 的文字欄位若以 `=`、`+`、`-` 或 `@` 開頭，會加上單引號以避免試算表公式注入。

預設輸出只能位於已由 Git 排除的 `.xq-auto-writer/reports/`，檔名包含 UTC 時間與報告 handle。每次以同目錄暫存檔建立，再以不覆寫的原子連結發布；目標已存在時停止，絕不覆寫。成功 JSON 回傳絕對路徑、byte count 與 SHA-256，讓後續流程能驗證檔案未改變。輸出標記 `contains_user_report_data: true`，不得提交或蒸餾進共用知識。

預設摘要擷取不改變報告 UI。`--include-failure-details` 會依已驗證流程短暫開啟失敗商品 Hyperlink、讀取三欄明細並關閉 overlay；若細節擷取失敗，仍保留總體摘要並寫入 `failure_detail_capture_error`，不能猜測錯誤代碼。既有報告仍固定揭露 `report_checkpoint_association_proven: false`。

此功能是專案自有 schema 的 JSON／CSV 匯出，不宣稱與 XQ 原生格式相容。後續已另以使用者明確授權的安全歷史回測產生報告，完成三種 XQ 原生檔案的真實驗證。

### XQ 原生儲存與匯出

原生輸出屬交易者可直接使用的檔案，目的地不能沿用 XQ 上次存檔資料夾，也不能由代理靜默決定。`xq_report.py --native-action <save|complete|trades>` 第一次呼叫時若沒有 `--confirm-output-directory`，只解析 Windows special-folder Desktop，回傳 `confirmation_required`、`proposed_output_directory`、`xq_touched: false` 與 `file_created: false`。代理必須把完整路徑呈現給使用者並詢問；使用者可接受桌面或指定另一個已存在資料夾。

取得同一次工作的明確確認後，才可加入：

```powershell
--output-directory '<已確認資料夾>' --confirm-output-directory
```

三種動作與實際格式如下：

| `--native-action` | XQ 入口 | XQ 存檔類型 | 驗證 |
| --- | --- | --- | --- |
| `save` | 儲存 | `XS回測資料格式(*.BTReport)` | 檔頭為 `SQLite format 3`，可供 XQ 保存／重開報告資料 |
| `complete` | 匯出 → 完整匯出 | `Excel 活頁簿(*.xlsx)` | ZIP/XLSX 簽章 `PK` |
| `trades` | 匯出 → 僅匯出交易紀錄 | `回測交易記錄 csv 檔(*.csv)` | 實測為 CP950，解析列數及欄數 |

報告工具列的「儲存」是名稱以圖示字元開頭、文字以「儲存」結尾的 Button；「匯出」是 `automation_id: appDropdownButton` 的 MenuItem，展開後以完整選項文字唯一比對。三種動作都開啟 Windows Save dialog，穩定控制項為 filename Edit `1001`、file-type ComboBox `FileTypeControlHost`、Save Button `1` 與 Cancel Button `2`。工具先核對存檔類型，再寫入使用者確認資料夾下的唯一檔名並讀回；若目標已存在則停止，不觸發或確認覆寫。

完成後，報告 Document 內會出現另一個空名稱 Document，包含 `Close` 與「關閉」Button。工具只在該內層 Document 點「關閉」，不能誤按報告頂層關閉鈕；之後須重新看到 `appDropdownButton` 才算 UI 復原。成功 JSON 同時回傳絕對路徑、格式、byte count、SHA-256、`completion_dialog_seen: true`、`report_restored: true` 及 `existing_file_overwritten: false`。

2026-07-21 以當次新建並編譯的 `Codex原生匯出驗證` 交易腳本、公開商品 2330、1 分鐘、2026-06-01 至 2026-06-02 進行安全歷史回測；編譯為 0 錯誤、0 警告，報告為成功 1、失敗 0、總交易 2。使用者先確認 Windows 桌面 `D:\User(重要勿刪)\Desktop`，再實際驗證：`.BTReport` 65,536 bytes、SQLite `quick_check: ok`、7 個資料表；完整 `.xlsx` 約 324 KB、ZIP 無損壞成員、10 張工作表；交易 `.csv` 386 bytes／CP950／3 列／17 欄。CLI 未帶確認旗標時先得到 `confirmation_required` 且沒有操作 XQ；帶確認後三種動作均建立唯一檔、未覆寫、完成提示關閉且報告控制項恢復。第一次手動探測曾因命令列中文字面值轉碼造成 XQ 顯示「檔案名稱無效」，XQ 沒有建立檔案；正式工具改由 Windows Unicode special-folder API 取得桌面路徑並完成驗證。

## 第九階段發布候選與維護模式

發布候選的離線閘門由根目錄 `scripts/check_release_candidate.py` 與 `scripts/rehearse_upgrade_rollback.py` 負責；前者凍結 recovery／report schema 與回測、boundary、batch、regression CLI，後者只在臨時目錄驗證 `v0.2.0` 至候選 Skill 的升級及 byte-level 復原。兩者都不開啟 XQ、不建立報告、不清 checkpoint，也不能取代本節的真實 recovery-status 或回測證據。

維護模式期間若真實 XQ 前置條件未滿足，保持本機狀態 active 並報告 `blocked`。只有五類 `自訂/CODEX/` 都能唯一讀回、離線完整回歸通過且 recovery-status 是 `safe_to_start`，才可慢速執行代表 smoke 與逐 pair 完整矩陣。任何 Windows 無回應、晚到對話框、timeout、非唯一報告或 marker 不符，立即停止輸入並保留 incident／checkpoint；不可把 CI Passed 解讀為 XQ UI 已驗證。
