# 更新紀錄

本文件記錄 XQ Auto Writer Skill 的重要變更。版本號遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### 新增

### 變更

### 修正

### 安全性

## [0.2.0] - 2026-07-19

### 新增

- 加入唯讀的 Windows GitHub Actions CI，在 Pull Request、`main` push 與人工觸發時驗證版本 metadata、儲存庫衛生、單元測試、Python 語法及 submodule 狀態。
- 加入單人維護流程與可重現的公開儲存庫檢查器。

### 變更

- 將專案治理預設調整為單人維護：PR 不要求第二人核准，但仍須通過 CI 才能合併。

### 修正

- 修正全新 Windows Python 環境缺少 IANA 時區資料，導致 XSHelp 同步無法解析 `Asia/Taipei` 的問題。

### 安全性

- CI 使用唯讀 GitHub 權限、不保存 checkout 憑證、不使用 secrets，且官方 Actions 固定至完整 commit SHA。
- 啟用 `main` Ruleset，要求 Pull Request 與 `verify` check，並禁止刪除及 force push。
- 啟用 `v*` Tag Ruleset，允許建立新版本 tag，但禁止更新或刪除既有 tag。

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
