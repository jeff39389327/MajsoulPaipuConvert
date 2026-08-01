# -*- coding: utf-8 -*-
"""download_recovery —— Stage 2 下載的失敗復原：號池切換 + 斷點記錄（CLI 與 GUI 共用）。

為什麼需要這支
--------------
下載中途可能因 (a) 雀魂資源版本換代（error 151）、(b) 連線中斷、(c) 帳號被限制
而開始整批失敗。本模組提供三件事：

1. ``AccountSession``：包住單一 ``MajsoulPaipuDownloader`` 連線的「帳號會話」。
   失敗時先以**同帳號**重連＋重新登入（涵蓋 151 自動更新資源版本），仍失敗才依序
   切換到號池中的下一個帳號；全部帳號都登入不了才拋 ``AllAccountsFailed``。
   多個並發 worker 共用同一 session 時以 generation 計數防止重複復原。
   另附 keepalive（心跳）：長時間下載中維持會話不被伺服器判定離線。

2. ``Checkpoint``：斷點記錄。成功的牌譜本來就以 ``mahjong_logs/tenhou/`` 既有檔案去重
   （天然斷點），本檔補上「哪些失敗、為什麼、中止時還剩哪些」的持久記錄；下次執行以
   ``merge_checkpoint_ids`` 把 pending／failed 併回工作清單自動續跑（即使 ID 清單已被
   重爬覆蓋或換檔），全部成功時自動刪除。

3. ``download_with_retry``：單一牌譜的下載重試外殼，串起上述兩者的重試節奏，
   並依 ``is_permanent_error`` / ``is_session_error`` 決定「直接放棄／原地重試／
   重建連線／換帳號」。

號池來源：config.ini ``[account]`` 的主帳號（ms_username/ms_password）＋
``account_pool``（JSON 陣列，經 config_store.load_into_env 進到環境變數 ACCOUNT_POOL）。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
from datetime import datetime, timezone


class AllAccountsFailed(RuntimeError):
    """號池中所有帳號皆無法登入（呼叫端應中止並記錄斷點）。"""


# ── 錯誤分類 ──────────────────────────────────────────────────────────────
# 為什麼要分類：舊版對「任何失敗」一律重連＋重登（0.7s 握手＋0.3s 登入＋退避 1~2s），
# 但最常見的失敗是 **1203 牌譜不存在**（爬到的 ID 早已被雀魂清掉），那是伺服器對該 uuid
# 的最終答案——重試、重連、換帳號都不可能變成功，只是把每筆失敗從 0.5s 拖成 2~5s，
# 還連帶反覆重登（徒增被伺服器視為異常的機會）。故：牌譜級錯誤直接放棄，只有連線／
# 會話級錯誤才值得重建連線。
_PERMANENT_CODES = {"1203"}          # 牌譜不存在（伺服器已刪除或 uuid 有誤）
_SESSION_CODES = {"151", "1004"}     # 151=客戶端版本/握手被拒、1004=會話未登入
# 連線層例外（websocket 已死、復原窗口內送出、逾時）——訊息沒有 code 可抓，用特徵字串。
_SESSION_PATTERNS = (
    "nonetype", "connectionclosed", "connection is closed", "no close frame",
    "timeout after", "cannot write to closing", "socket", "winerror", "eof",
)
# 連續失敗達此數量就強制重建一次連線（防「未知原因整批失敗」時我們毫無反應地空轉）。
_RECOVER_AFTER_CONSECUTIVE = 20
# 心跳間隔（秒）。真實客戶端約 5~6s 送一次 .lq.Lobby.heatbeat；長時間只讀不寫的
# 會話會被伺服器判定離線，之後所有請求回 1004。
_KEEPALIVE_INTERVAL = 6.0


def error_code(err) -> str:
    """從錯誤訊息取出雀魂錯誤碼（"error_code: 1203" / "code=151"）；取不到回空字串。"""
    m = re.search(r"code[=:\s]+(\d+)", str(err))
    return m.group(1) if m else ""


def is_permanent_error(err) -> bool:
    """該牌譜本身的最終錯誤（重試/換號都無用）→ 呼叫端應直接記為失敗並跳下一筆。"""
    return error_code(err) in _PERMANENT_CODES


def is_session_error(err) -> bool:
    """連線／會話層錯誤 → 值得重建連線後再試。"""
    if error_code(err) in _SESSION_CODES:
        return True
    text = str(err).lower()
    return any(p in text for p in _SESSION_PATTERNS)


def is_auth_error(err) -> bool:
    """登入失敗是否為「這個帳號本身不能用」（帳密錯/被封）——只有這種才把帳號標記為死。

    網路不通、握手被拒（151）等與帳號無關的失敗若也標記為死，整個號池會在一次網路
    抖動後全滅，讓後續全部牌譜直接中止。"""
    code = error_code(err)
    return code in {"1002", "1003", "1006", "103"}


def load_accounts(params: dict | None = None) -> list[dict]:
    """組出帳號清單：主帳號（params 覆寫 > 環境變數）優先，其後接 ACCOUNT_POOL（JSON）。

    去除空白/不完整/重複（同 username）項；回傳 [{"username", "password"}, ...]。
    """
    params = params or {}
    accounts: list[dict] = []

    def add(username, password) -> None:
        username = (username or "").strip()
        password = (password or "").strip()
        if username and password and not any(a["username"] == username for a in accounts):
            accounts.append({"username": username, "password": password})

    add(params.get("username") or os.getenv("ms_username", ""),
        params.get("password") or os.getenv("ms_password", ""))

    raw = os.getenv("ACCOUNT_POOL", "").strip()
    if raw:
        try:
            pool = json.loads(raw)
        except ValueError:
            pool = []
        if isinstance(pool, list):
            for entry in pool:
                if isinstance(entry, dict):
                    add(entry.get("username"), entry.get("password"))
    return accounts


class AccountSession:
    """共用 downloader 連線的帳號會話：登入、151 自動更新、失敗時重連/換帳號。

    notify(code, msg) 供呼叫端接事件（GUI 轉 bridge.notice、CLI 轉 print）；
    codes: VERSION_AUTO_UPDATING / VERSION_UPDATED / SESSION_RECOVERING /
           ACCOUNT_SWITCHED / ACCOUNT_LOGIN_FAILED。
    """

    def __init__(self, downloader, accounts: list[dict], ini_paths=(), notify=None):
        if not accounts:
            raise ValueError("accounts 不可為空")
        self.downloader = downloader
        self.accounts = list(accounts)
        self.ini_paths = [p for p in ini_paths if p]
        self._notify = notify or (lambda code, msg="": None)
        self._index = 0
        self._generation = 0
        self._dead: set[int] = set()  # 本次執行中登入失敗的帳號（不再嘗試）
        # 151 版本探測結果為全域事實（版本檢查與帳號無關），跨帳號共用已被拒集合，
        # 避免號池中每個帳號都重跑整輪（可達數十次）的候選探測。
        self._rejected_versions: set[str] = set()
        self._lock = asyncio.Lock()
        # 復原柵欄：重建連線（close→重連→重登）期間 clear，其他並發 worker 須等
        # set 後才可發請求。否則會打中半建構的 channel（_ws=None → 'NoneType' has no
        # attribute 'send'）或已連線但未登入的會話（伺服器回 error 1004）。
        self._ready = asyncio.Event()
        self._ready.set()
        self._consecutive_failures = 0
        self._keepalive_task = None

    @property
    def generation(self) -> int:
        """會話世代：每次成功觸發復原即 +1。worker 在下載前記下，失敗後傳回
        recover()，若期間別的 worker 已復原（世代不符）則直接重試、不重複登入。"""
        return self._generation

    @property
    def current_username(self) -> str:
        return self.accounts[self._index]["username"]

    async def ensure_login(self) -> None:
        """初次登入：自第一個帳號起依序嘗試，全滅拋 AllAccountsFailed。"""
        async with self._lock:
            await self._login_any(start_offset=0, reconnect=False)

    async def wait_ready(self) -> None:
        """等待復原完成（無復原進行中時立即返回）。並發 worker 每次下載前應呼叫，
        避免請求落在連線重建的窗口內白白燒掉重試次數。"""
        await self._ready.wait()

    def note_success(self) -> None:
        self._consecutive_failures = 0

    def note_failure(self, permanent: bool = False) -> bool:
        """記一次失敗；回傳「是否該強制重建連線」（連續失敗達門檻時）。

        安全網用途：單筆失敗不值得重連，但如果**連續**幾十筆都失敗，很可能是會話已經
        壞掉，重建一次連線比繼續空轉好。permanent（1203）例外——那是伺服器針對該 uuid
        的明確回答（會話壞掉時給的是 1004/151），整份清單都是死 ID 時不該一直重登。"""
        self._consecutive_failures += 1
        if permanent:
            return False
        return self._consecutive_failures % _RECOVER_AFTER_CONSECUTIVE == 0

    def start_keepalive(self, interval: float = _KEEPALIVE_INTERVAL) -> None:
        """開始送心跳（.lq.Lobby.heatbeat），維持會話存活。

        雀魂會把長時間沒有心跳的會話判定為離線，之後所有請求回 error 1004、必須整條
        重登。真實客戶端在遊戲/大廳中同樣是「下載請求與心跳並存」，故心跳不受「下載
        嚴格串行」限制——它不是下載請求，也不佔用第二個帳號或連線。"""
        if self._keepalive_task is None:
            self._keepalive_task = asyncio.ensure_future(self._keepalive_loop(interval))

    async def stop_keepalive(self) -> None:
        task, self._keepalive_task = self._keepalive_task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 收尾不可再拋
            pass

    async def _keepalive_loop(self, interval: float) -> None:
        import ms.protocol_pb2 as pb

        while True:
            await asyncio.sleep(interval)
            await self._ready.wait()  # 復原期間不送，避免打到半建構的 channel
            try:
                await asyncio.wait_for(
                    self.downloader.lobby.heatbeat(pb.ReqHeatBeat()), timeout=15)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 心跳失敗不自行復原：交給下一筆下載的重試流程
                pass

    async def recover(self, seen_generation: int, force_switch: bool = False, reason: str = "") -> None:
        """下載失敗後的復原。先同帳號重連＋重登（涵蓋 151 版本換代與斷線），
        force_switch=True 時直接從下一個帳號開始輪替。"""
        async with self._lock:
            if self._generation != seen_generation:
                return  # 已有其他 worker 完成復原，呼叫端直接重試即可
            self._generation += 1
            self._notify("SESSION_RECOVERING", reason)
            offset = 1 if (force_switch and len(self.accounts) > 1) else 0
            self._ready.clear()
            try:
                await self._login_any(start_offset=offset, reconnect=True)
            finally:
                # 失敗（含 AllAccountsFailed）也要放行，否則等柵欄的 worker 永久卡死；
                # 放行後它們會自行失敗→recover→收到 AllAccountsFailed 而中止。
                self._ready.set()

    async def _reconnect(self) -> None:
        """關閉並重開 websocket（換帳號或斷線後，舊連線狀態不可信）。"""
        try:
            await self.downloader.close()
        except Exception:  # noqa: BLE001 舊連線已死也照樣重開
            pass
        await self.downloader.start()

    async def _login_any(self, start_offset: int, reconnect: bool) -> None:
        """自目前帳號（加位移）起輪一圈，跳過已死帳號；登入成功即返回。"""
        n = len(self.accounts)
        last_exc: BaseException | None = None
        for k in range(n):
            idx = (self._index + start_offset + k) % n
            if idx in self._dead:
                continue
            acct = self.accounts[idx]
            switched = idx != self._index
            self._index = idx
            try:
                if reconnect:
                    await self._reconnect()
            except Exception as exc:  # noqa: BLE001 重連失敗是網路問題，不算帳號死亡
                last_exc = exc
                print(f"重新連線失敗: {exc}")
                continue
            try:
                await self._login_with_auto_update(acct)
            except Exception as exc:  # noqa: BLE001 換下一個帳號續試
                last_exc = exc
                # 只有「這個帳號本身不能用」（帳密錯/被封）才永久跳過；網路抖動或 151
                # 握手被拒與帳號無關，若也標記為死，一次抖動就會把整個號池打光。
                if is_auth_error(exc):
                    self._dead.add(idx)
                print(f"帳號 {acct['username']} 登入失敗: {exc}")
                self._notify("ACCOUNT_LOGIN_FAILED", acct["username"])
                continue
            if switched:
                print(f"已切換至帳號 {acct['username']}")
                self._notify("ACCOUNT_SWITCHED", acct["username"])
            return
        raise AllAccountsFailed(str(last_exc) if last_exc else "無可用帳號")

    async def _login_with_auto_update(self, acct: dict) -> None:
        """登入單一帳號；遇 error 151（資源版本過期）自動抓最新版本重試並寫回 config.ini。"""
        import ms_patch

        username, password = acct["username"], acct["password"]
        try:
            await ms_patch.login(self.downloader, username, password)
            ms_patch.patch_downloader(self.downloader)
            return
        except Exception as exc:  # noqa: BLE001
            if not ms_patch.is_resource_version_error(exc):
                raise
            last_exc: BaseException = exc

        self._notify("VERSION_AUTO_UPDATING")

        # 以「第一次登入實際使用的版本」＋跨帳號共用的已拒集合為已試集合，避免重試
        # 剛失敗或其他帳號已探測過的版本。候選由 ms_patch 產生：目前版本的 patch 遞增
        # 探測（雀魂 patch 會跳號，span 已放寬）→ minor 換代候選 → version.json → 內建預設。
        original = os.environ.get("MS_RES_VERSION")

        def _restore_env() -> None:
            # 失敗收尾還原環境變數，避免下一輪以「最後一個亂猜的候選」為基準再往上漂；
            # 成功時不還原（新版本就是要留用並寫回 config.ini）。
            if original is None:
                os.environ.pop("MS_RES_VERSION", None)
            else:
                os.environ["MS_RES_VERSION"] = original

        rejected = self._rejected_versions
        rejected.add(ms_patch._res_version())
        for ver in ms_patch.res_version_candidates():
            if not ver or ver in rejected:
                continue
            # _res_version() 於登入時才讀環境變數，直接改 os.environ 即時生效。
            os.environ["MS_RES_VERSION"] = ver
            try:
                await ms_patch.login(self.downloader, username, password)
                ms_patch.patch_downloader(self.downloader)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if ms_patch.is_resource_version_error(exc):
                    rejected.add(ver)
                    await asyncio.sleep(0.25)  # 對伺服器溫和些，探測不必打滿速
                    continue  # 此版本仍被拒，試下一個候選
                _restore_env()
                raise
            self._persist_res_version(ver)
            self._notify("VERSION_UPDATED", ver)
            return
        _restore_env()  # 探測全滅
        raise last_exc

    def _persist_res_version(self, version: str) -> None:
        """把成功登入的資源版本寫回 config.ini（primary＋mirror），下次直接可用。
        寫入失敗不影響本次執行（記憶體中已套用新版本）。"""
        import config_store

        for path in self.ini_paths:
            try:
                config_store.set_value(path, "account", "ms_res_version", version)
            except Exception:  # noqa: BLE001
                pass


class Checkpoint:
    """下載斷點：failed = {uuid: {error, account, ts}}，pending = 中止時尚未處理的 uuid。

    檔案配置（v2，三個檔；``path`` 仍是對外代表路徑）
    ------------------------------------------------
    - ``download_checkpoint.json``        —— 只存小小的摘要（版本、筆數、時間）。
    - ``download_checkpoint_failed.jsonl`` —— 失敗記錄，**每筆一行、append-only**。
    - ``download_checkpoint_pending.txt``  —— 未處理 uuid，一行一個，只在中止/收尾時寫。

    為什麼要拆（v1 的效能地雷）
    ---------------------------
    v1 把 pending 整包塞在同一個 JSON，而 ``record_failure`` 每次失敗都重寫整檔。
    實測使用者的斷點檔 pending 有 228 萬筆＝119 MB，於是**每一筆下載失敗都要序列化並
    寫出 119 MB**（實測 0.66 s，期間 event loop 完全卡死，還連帶狂寫 SSD）。改成
    append 一行後，同樣的動作是 O(1)。舊檔會在載入時自動遷移成新格式。
    """

    def __init__(self, path: str):
        self.path = path
        base = path[:-5] if path.endswith(".json") else path
        self.failed_path = base + "_failed.jsonl"
        self.pending_path = base + "_pending.txt"
        self.data: dict = {"version": 2, "failed": {}, "pending": []}
        self._failed_fh = None      # 追加模式的檔案握把（首次寫入時才開）
        self._appended = 0          # 已追加的行數（用於收尾時判斷要不要壓實）

    # ── 載入 ────────────────────────────────────────────────────────────
    def load(self) -> "Checkpoint":
        legacy = False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # v1：failed/pending 直接內嵌在主檔 → 讀進來後改寫成 v2 格式。
                if data.get("failed") or data.get("pending"):
                    self.data["failed"] = dict(data.get("failed") or {})
                    self.data["pending"] = list(data.get("pending") or [])
                    legacy = True
        except Exception:  # noqa: BLE001 缺檔/壞檔一律視為空斷點
            pass

        try:
            with open(self.pending_path, "r", encoding="utf-8") as f:
                self.data["pending"] = [ln.strip() for ln in f if ln.strip()]
        except OSError:
            pass

        failed = self.data["failed"]
        try:
            with open(self.failed_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue  # 寫到一半被中斷的殘行：跳過
                    uuid = rec.get("uuid")
                    if not uuid:
                        continue
                    if rec.get("cleared"):
                        failed.pop(uuid, None)     # 後來重試成功的墓碑
                    else:
                        failed[uuid] = {k: rec.get(k, "") for k in ("error", "account", "ts")}
        except OSError:
            pass

        if legacy:
            self._rewrite_failed()
            self._write_pending()
            self.save()
        return self

    @property
    def failed(self) -> dict:
        return self.data["failed"]

    @property
    def pending(self) -> list:
        return self.data["pending"]

    # ── 變更（皆為 O(1) 追加，不重寫整檔）────────────────────────────────
    def record_failure(self, uuid: str, error: str, account: str = "") -> None:
        rec = {
            "error": str(error),
            "account": account,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.data["failed"][uuid] = rec
        self._append({"uuid": uuid, **rec})

    def clear_failure(self, uuid: str) -> None:
        if self.data["failed"].pop(uuid, None) is not None:
            self._append({"uuid": uuid, "cleared": True})

    def set_pending(self, uuids) -> None:
        self.data["pending"] = list(uuids)
        self._write_pending()
        self.save()

    def forget_pending(self) -> None:
        """把 pending 從**記憶體**釋放（磁碟檔不動）。

        呼叫端把 pending 併進工作清單後就不再需要這份副本；百萬筆規模下它是好幾百 MB，
        留著只是讓整個下載期間都背著。磁碟上的 _pending.txt 仍是下次續跑的來源，
        只有 set_pending() 會覆寫它。"""
        self.data["pending"] = []

    def save(self) -> None:
        """寫出摘要主檔（小檔，可頻繁呼叫）。"""
        meta = {
            "version": 2,
            "failed_count": len(self.data["failed"]),
            "pending_count": len(self.data["pending"]),
            "failed_file": os.path.basename(self.failed_path),
            "pending_file": os.path.basename(self.pending_path),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._atomic_write(self.path, json.dumps(meta, ensure_ascii=False, indent=2))

    def close(self) -> None:
        """收尾：壓實失敗檔（去掉墓碑與重複行）並關閉握把。呼叫端結束下載時應呼叫。"""
        if self._appended:
            self._rewrite_failed()
        if self._failed_fh is not None:
            try:
                self._failed_fh.close()
            except OSError:
                pass
            self._failed_fh = None

    def delete_if_clean(self) -> None:
        """無失敗且無未處理項時刪除斷點檔（乾淨收尾，避免殘留誤導下次執行）。"""
        if self.data["failed"] or self.data["pending"]:
            return
        self.close()
        for path in (self.path, self.failed_path, self.pending_path):
            try:
                os.remove(path)
            except OSError:
                pass

    # ── 內部 ────────────────────────────────────────────────────────────
    def _append(self, rec: dict) -> None:
        try:
            if self._failed_fh is None:
                os.makedirs(os.path.dirname(self.failed_path) or ".", exist_ok=True)
                self._failed_fh = open(self.failed_path, "a", encoding="utf-8")
            self._failed_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._failed_fh.flush()
            self._appended += 1
        except Exception:  # noqa: BLE001 斷點寫入失敗不可中斷下載主流程
            pass

    def _rewrite_failed(self) -> None:
        """以記憶體中的 failed 重寫失敗檔（載入舊格式或收尾壓實時各一次）。"""
        if self._failed_fh is not None:
            try:
                self._failed_fh.close()
            except OSError:
                pass
            self._failed_fh = None
        self._appended = 0
        if not self.data["failed"]:
            try:
                os.remove(self.failed_path)
            except OSError:
                pass
            return
        lines = "".join(
            json.dumps({"uuid": u, **info}, ensure_ascii=False) + "\n"
            for u, info in self.data["failed"].items()
        )
        self._atomic_write(self.failed_path, lines)

    def _write_pending(self) -> None:
        pending = self.data["pending"]
        if not pending:
            try:
                os.remove(self.pending_path)
            except OSError:
                pass
            return
        self._atomic_write(self.pending_path, "\n".join(pending) + "\n")

    @staticmethod
    def _atomic_write(path: str, text: str) -> None:
        """先寫 .tmp 再 replace，避免中斷時留下寫一半的檔。"""
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001 斷點寫入失敗不可中斷下載主流程
            try:
                os.remove(tmp)
            except OSError:
                pass


def merge_checkpoint_ids(ids, checkpoint: Checkpoint) -> list:
    """把斷點檔的 pending（上次中止未處理）與 failed（上次失敗）併回本次工作清單
    （保序去重：清單在前、斷點項在後）。

    這是斷點真正被「讀取來驅動續跑」的地方——在此之前 pending 只寫不讀，一旦 ID
    清單被重爬覆蓋或換檔，上次中止剩下的項目就默默消失。合併後交給呼叫端既有的
    「tenhou/ 已存在檔案」過濾去掉已完成項。

    以 chain 串接而非先 list 相加：百萬筆規模時，那個中間串接清單本身就是數百 MB。"""
    return list(dict.fromkeys(
        itertools.chain(ids, checkpoint.pending, checkpoint.failed)))


async def download_with_retry(session: AccountSession, download_fn, uuid: str,
                              max_attempts: int = 3, base_delay: float = 1.0,
                              timeout: float = 30.0):
    """下載單一牌譜並在失敗時依錯誤性質決定復原強度：

    - **牌譜級（1203 牌譜不存在）**：伺服器的最終答案，直接放棄——不重試、不重連、
      不換帳號。這是最常見的失敗（爬到的舊 ID 已被雀魂清掉），舊版對它做整套重連重登，
      每筆要 2~5 秒還把帳號輪掉；現在是 ~0.5 秒。
    - **連線／會話級（151、1004、websocket 已死、逾時）**：重連＋重登（涵蓋 151 資源
      版本換代），再失敗才強制換帳號。
    - **其他未知錯誤**：先原地重試一次（短退避、不重連），仍失敗才重建連線。

    另有安全網：連續失敗達 `_RECOVER_AFTER_CONSECUTIVE` 筆時，即使是「不該重連」的錯誤
    也強制重建一次連線（防會話早已壞掉卻整批空轉）。

    download_fn(uuid) 須回傳 (log, timing, full, error_msg)（見 toumajsoul.download_single_log）。
    每次嘗試以 timeout 秒為上限——雀魂 RPC 無自帶逾時，遇到網路黑洞會無限等待，
    故卡住一律視為一次失敗、觸發重試而非凍結整批。
    回傳同形狀 4-tuple；最終失敗時 log 為 None 且 error_msg 非 None。
    號池全滅時 raise AllAccountsFailed（呼叫端應中止並記錄斷點）。
    """
    last_err = "unknown error"
    recovered = False
    for attempt in range(max_attempts):
        await session.wait_ready()  # 復原進行中先等，別把請求打進重建窗口
        gen = session.generation
        try:
            log, timing, full, err = await asyncio.wait_for(download_fn(uuid), timeout=timeout)
        except asyncio.TimeoutError:
            log, timing, full, err = None, None, None, f"timeout after {timeout:.0f}s"
        except Exception as exc:  # noqa: BLE001 連線層例外也視為一次失敗
            log, timing, full, err = None, None, None, str(exc)
        if log is not None:
            session.note_success()
            return log, timing, full, None
        last_err = err or "unknown error"

        if is_permanent_error(last_err):
            break  # 牌譜本身的問題：重試無用
        if attempt + 1 >= max_attempts:
            break
        if is_session_error(last_err) or recovered:
            # 連線/會話壞了（或原地重試過仍失敗）→ 重建連線；已重建過一次就換帳號。
            await session.recover(gen, force_switch=recovered, reason=f"{uuid}: {last_err}")
            recovered = True
            await asyncio.sleep(base_delay * (attempt + 1))
        else:
            await asyncio.sleep(base_delay * 0.5)  # 未知錯誤：先便宜地原地重試

    if session.note_failure(is_permanent_error(last_err)):
        # 連續失敗過多（且不是「牌譜不存在」這種明確答案）：重建一次連線當安全網。
        await session.recover(session.generation, reason=f"連續失敗 {_RECOVER_AFTER_CONSECUTIVE} 筆")
    return None, None, None, last_err
