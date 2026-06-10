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

2. ``Checkpoint``：``download_checkpoint.json`` 斷點檔。成功的牌譜本來就以
   ``mahjong_logs/tenhou/`` 既有檔案去重（天然斷點），本檔補上「哪些失敗、為什麼、
   中止時還剩哪些」的持久記錄；下次執行會自動重試失敗項，全部成功時自動刪除。

3. ``download_with_retry``：單一牌譜的下載重試外殼，串起上述兩者的重試節奏。

號池來源：config.ini ``[account]`` 的主帳號（ms_username/ms_password）＋
``account_pool``（JSON 陣列，經 config_store.load_into_env 進到環境變數 ACCOUNT_POOL）。
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone


class AllAccountsFailed(RuntimeError):
    """號池中所有帳號皆無法登入（呼叫端應中止並記錄斷點）。"""


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
        self._lock = asyncio.Lock()

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

    async def recover(self, seen_generation: int, force_switch: bool = False, reason: str = "") -> None:
        """下載失敗後的復原。先同帳號重連＋重登（涵蓋 151 版本換代與斷線），
        force_switch=True 時直接從下一個帳號開始輪替。"""
        async with self._lock:
            if self._generation != seen_generation:
                return  # 已有其他 worker 完成復原，呼叫端直接重試即可
            self._generation += 1
            self._notify("SESSION_RECOVERING", reason)
            offset = 1 if (force_switch and len(self.accounts) > 1) else 0
            await self._login_any(start_offset=offset, reconnect=True)

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
                await self._login_with_auto_update(acct)
            except Exception as exc:  # noqa: BLE001 換下一個帳號續試
                last_exc = exc
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

        # 以「第一次登入實際使用的版本」為已試集合，避免重試同一個剛失敗的版本。
        # 候選由 ms_patch 產生：目前版本的 patch 遞增探測（雀魂多半只升 patch）→ version.json
        # → 內建預設，能在未更新很久後自癒。
        tried = {ms_patch._res_version()}
        for ver in ms_patch.res_version_candidates():
            if not ver or ver in tried:
                continue
            tried.add(ver)
            # _res_version() 於登入時才讀環境變數，直接改 os.environ 即時生效。
            os.environ["MS_RES_VERSION"] = ver
            try:
                await ms_patch.login(self.downloader, username, password)
                ms_patch.patch_downloader(self.downloader)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if ms_patch.is_resource_version_error(exc):
                    continue  # 此版本仍被拒，試下一個候選
                raise
            self._persist_res_version(ver)
            self._notify("VERSION_UPDATED", ver)
            return
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
    """下載斷點檔（JSON）：failed = {uuid: {error, account, ts}}，pending = 中止時
    尚未處理的 uuid 清單。每次變更即落盤（先寫 .tmp 再 replace，避免寫一半損毀）。"""

    def __init__(self, path: str):
        self.path = path
        self.data: dict = {"version": 1, "failed": {}, "pending": []}

    def load(self) -> "Checkpoint":
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.data["failed"] = dict(data.get("failed") or {})
                self.data["pending"] = list(data.get("pending") or [])
        except Exception:  # noqa: BLE001 缺檔/壞檔一律視為空斷點
            pass
        return self

    @property
    def failed(self) -> dict:
        return self.data["failed"]

    @property
    def pending(self) -> list:
        return self.data["pending"]

    def record_failure(self, uuid: str, error: str, account: str = "") -> None:
        self.data["failed"][uuid] = {
            "error": str(error),
            "account": account,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def clear_failure(self, uuid: str) -> None:
        if uuid in self.data["failed"]:
            del self.data["failed"][uuid]
            self.save()

    def set_pending(self, uuids) -> None:
        self.data["pending"] = list(uuids)
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:  # noqa: BLE001 斷點寫入失敗不可中斷下載主流程
            pass

    def delete_if_clean(self) -> None:
        """無失敗且無未處理項時刪除斷點檔（乾淨收尾，避免殘留誤導下次執行）。"""
        if self.data["failed"] or self.data["pending"]:
            return
        try:
            os.remove(self.path)
        except OSError:
            pass


async def download_with_retry(session: AccountSession, download_fn, uuid: str,
                              max_attempts: int = 3, base_delay: float = 1.0,
                              timeout: float = 60.0):
    """下載單一牌譜並在失敗時走復原節奏：
    第 1 次重試前同帳號重連＋重登（涵蓋 151 版本換代、斷線），第 2 次起強制換帳號。

    download_fn(uuid) 須回傳 (log, timing, full, error_msg)（見 toumajsoul.download_single_log）。
    每次嘗試以 timeout 秒為上限——雀魂 RPC 無自帶逾時，遇到無效 UUID 或網路黑洞會無限等待，
    故卡住一律視為一次失敗、觸發重試而非凍結整批。
    回傳同形狀 4-tuple；最終失敗時 log 為 None 且 error_msg 非 None。
    號池全滅時 raise AllAccountsFailed（呼叫端應中止並記錄斷點）。
    """
    last_err = "unknown error"
    for attempt in range(max_attempts):
        gen = session.generation
        try:
            log, timing, full, err = await asyncio.wait_for(download_fn(uuid), timeout=timeout)
        except asyncio.TimeoutError:
            log, timing, full, err = None, None, None, f"timeout after {timeout:.0f}s"
        except Exception as exc:  # noqa: BLE001 連線層例外也視為一次失敗
            log, timing, full, err = None, None, None, str(exc)
        if log is not None:
            return log, timing, full, None
        last_err = err or "unknown error"
        if attempt + 1 >= max_attempts:
            break
        await session.recover(gen, force_switch=attempt >= 1, reason=f"{uuid}: {last_err}")
        await asyncio.sleep(base_delay * (attempt + 1))
    return None, None, None, last_err
