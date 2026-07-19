# 更新紀錄

本文件記錄 XQ Auto Writer Skill 的重要變更。版本號遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### 新增

### 變更

### 修正

### 安全性

## [0.1.0] - 2026-07-19

### 新增

- 支援指標、選股、警示、數值／邏輯值／字串函數及自動交易腳本。
- 加入 XQ XScript 建檔、編譯、錯誤擷取與最多十次的修正閉環。
- 加入 `XScript_Preset` 與 `XQStrategy` 上游 submodule。
- 加入 48 個分類、1,459 筆文件的 XSHelp metadata-only 索引及按需暫時讀取。
- 加入 Windows UI 控制項探測、校正範本與校正指南。
- 加入版本中繼資料驗證、人工發布程序及 GitHub 協作模板。

### 安全性

- 排除本機 UI 設定、使用者生成策略、快取、秘密與未授權網站正文。
- 明確區分本專案 MIT License 與第三方 submodule／官方資料的權利範圍。
