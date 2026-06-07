"""GUI 後端橋接層 (Electron <-> 既有 Python pipeline)。

此套件不重寫 Stage 1 / Stage 2 的核心邏輯，而是把它們包成統一的 runner，
並以 NDJSON 事件 (見 bridge.emit) 對 stdout 輸出結構化進度，供 Electron 解析。
"""
