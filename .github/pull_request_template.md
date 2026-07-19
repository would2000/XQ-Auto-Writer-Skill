## 變更摘要

- （請填寫）

## 原因與影響

- （請填寫）

## 變更類型

- [ ] `feat`：相容的新功能
- [ ] `fix`：錯誤修正
- [ ] `docs`：文件
- [ ] `test`：測試
- [ ] `chore`：維護或發布
- [ ] 不相容變更（已提供升級步驟）

## 版本與更新紀錄

- [ ] 已更新 `CHANGELOG.md` 的 `[Unreleased]`，或此變更不需要更新並已說明原因
- [ ] 若變更 `VERSION`，CHANGELOG 有完全一致的版本與 ISO 日期
- [ ] 未移動或重用已公開的 Git tag

## 驗證

- [ ] `python scripts/check_release_metadata.py`
- [ ] `python -W error::ResourceWarning -m unittest discover -s tests -v`
- [ ] Python 語法檢查
- [ ] 秘密、本機路徑與第三方內容範圍檢查

XQ UI 驗證狀態：

- [ ] Passed
- [ ] Partially Passed
- [ ] Failed
- [ ] Unable to Test／本次不影響 XQ UI

## 已知限制與回復方式

- （請填寫）
