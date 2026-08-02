# -*- coding: utf-8 -*-
"""
ms_patch —— 雀魂 CN 登入/下載的可攜式補丁 (被 git 追蹤，不依賴 gitignored 的
tensoul-py-ng vendored 修改)。

為什麼需要這支
--------------
tensoul-py-ng 久未更新：登入/下載送的 client_version_string 仍是舊格式
"web-{version}" (取自已棄用的 /1/version.json，回 0.11.252.w)。現行雀魂客戶端
已換成 Unity WebGL，伺服器登入/下載改檢查 **resource version**，舊請求一律回
error 151。2026-06 實測：151 只看 resource version (client_version_string)，package / UA /
tag 不影響。

**2026-07 起 151 有第二個來源：連線握手** (見 `patch_route_connect`)。雀魂把客戶端合法性
檢查前移到 `.lq.Route.requestConnection`，該請求要帶 ms-api protobuf 沒有的第 6 欄 "Web"；
少了它，之後不論送什麼 resource version 都回 151 (連不存在的帳號也是 151)。兩個來源要一起
修才會通。

由於 `tensoul-py-ng/` 在 .gitignore 內 (每位使用者各自 clone)，補丁不能只改 vendored
檔，否則別人重新 clone 又會 151。本模組把修正放在**被追蹤的 repo 程式碼**，於 runtime
套用，使任何使用者只要在 config.env 填帳密即可運作 (毋需瀏覽器、毋需 token、毋需改 tensoul)。

雀魂改版資源後若再現 151：設環境變數 MS_RES_VERSION (或 config.env 內同名)，或改下方
_DEFAULT_RES_VERSION 即可 (`download_recovery` 亦會自動探測並寫回 config.ini)。新值來源：
開啟 https://game.maj-soul.com/1/ 後標題畫面右下角的版本號 (如 v0.16.257.W.4.0.45 → 取
0.16.257，**免登入**)，或 localStorage 的 prev_res_version。若連正確版本都 151，代表又是
握手/請求格式被改：用瀏覽器攔 WebSocket (hook window.WebSocket 錄 frame) 比對真實封包。
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import time
import types
import urllib.request
import uuid

import ms.protocol_pb2 as pb  # 來自 ms-api，與 tensoul 套件無關

# 只有 resource version 會被 151 檢查，故僅此一項開放覆寫；其餘為 CN 固定值
# (專案 CLAUDE.md 已限定 CN-only)。MS_RES_VERSION 於登入時才讀取，使 config.env
# 的覆寫生效 (模組 import 早於 dotenv.load_dotenv)。
_DEFAULT_RES_VERSION = "0.16.257"   # 2026-07-26 實機標題畫面 v0.16.257.W.4.0.45
_PKG_VERSION = "4.0.45"          # 伺服器不檢查，僅為與真實客戶端一致
_LOGIN_TAG = "cn"                # CN-only
_CONNECT_REGION = 1              # CN-only (config.json gateways 第 1 區)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

# 雀魂 CN web 客戶端的版本資訊端點；error 151 時用來自動抓取最新資源版本。
# 可用 MS_VERSION_URL 覆寫 (例如雀魂改了路徑)。
_VERSION_JSON_URL = os.getenv(
    "MS_VERSION_URL", "https://game.maj-soul.com/1/version.json"
)
# 雀魂版本字串尾端帶伺服器代碼後綴 (CN web 為 ".w")；resource 版本不含此後綴。
_VERSION_SUFFIXES = (".w", ".x", ".t")


def _res_version() -> str:
    # 注意：GUI 在使用者留空「資源版本」欄位時會寫入 MS_RES_VERSION= (空字串)，
    # 而 os.getenv 對「存在但為空」的鍵不會回退預設，導致送出 version_str="WebGL_2022-"
    # 而被伺服器以 error 151 拒絕。故此處將空字串一律視為「未設定」，回退預設值。
    return os.getenv("MS_RES_VERSION", "").strip() or _DEFAULT_RES_VERSION


def _client_version_string() -> str:
    return f"WebGL_2022-{_res_version()}"


def _tensoul_pkg_dir(tensoul_dir: str) -> str:
    """回傳 tensoul 套件實際所在目錄 (cfg.py 用 __file__.parent 讀 ms_cfg.json)。

    優先用 find_spec 定位 (不會執行套件程式碼，故安全於 import tensoul 之前)，
    使開發版 (tensoul-py-ng/tensoul) 與 PyInstaller 打包版 (_internal/tensoul) 都正確；
    找不到才退回相對路徑。"""
    try:
        spec = importlib.util.find_spec("tensoul")
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        if spec.submodule_search_locations:
            return list(spec.submodule_search_locations)[0]
        if spec.origin:  # 退而求其次：以 __init__ 之父目錄為套件目錄
            return os.path.dirname(spec.origin)
    return os.path.join(tensoul_dir, "tensoul")


def ensure_ms_cfg(tensoul_dir: str = "tensoul-py-ng") -> None:
    """tensoul 的 cfg.py 於 import 時即讀 ms_cfg.json，缺檔會 import 失敗。
    若不存在則以 ms_cfg.example.json 為底建立並設成 CN。**必須在 import tensoul 之前呼叫。**

    建好設定檔後順手套用 `patch_route_connect()`（此時 import tensoul 已安全），
    使所有入口點（toumajsoul / majsoul_get / GUI / 測試腳本）都自動拿到握手補丁。"""
    pkg_dir = _tensoul_pkg_dir(tensoul_dir)
    cfg_path = os.path.join(pkg_dir, "ms_cfg.json")
    if not os.path.exists(cfg_path):
        example = os.path.join(pkg_dir, "ms_cfg.example.json")
        if os.path.exists(example):
            with open(example, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
        data["connect_region_number"] = _CONNECT_REGION  # tensoul 下載路徑唯一會讀的鍵
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    patch_route_connect()
    patch_ws_keepalive()


# ReqRequestConnection 的第 6 欄 (string) = 平台字串 "Web"。ms-api 的 protocol_pb2 沒有這欄
# (只有 2:type / 3:route_id / 4:timestamp)，無法用欄位賦值，故以 protobuf wire format 直接
# 附加：tag = (6 << 3) | 2 (length-delimited) = 0x32，長度 3，內容 "Web"。
_CONN_PLATFORM_FIELD = b"\x32\x03Web"


def patch_route_connect() -> None:
    """替換 tensoul 的 route_connect，讓 ReqRequestConnection 帶上平台欄位 "Web"。

    為什麼需要這支 (2026-07 實測)
    -----------------------------
    雀魂把「客戶端合法性」檢查從登入本體前移到**連線握手**：握手若少了第 6 欄 "Web"，
    之後 ReqLogin 一律回 **error 151**——與 resource version 對不對無關，連不存在的帳號
    也回 151 (2026-06 時回 1002)，因此舊的「遞增探測資源版本」永遠探不到出口。
    實測 (res 0.16.257)：握手帶 "Web" → 登入成功；不帶 → 151。type (1/3) 與 timestamp
    (秒/毫秒) 都不影響，但此處仍照真實 Unity 客戶端送 type=1 + 秒級 timestamp。

    真實客戶端封包 (2026-07-26 於 game.maj-soul.com/1/ 攔 WebSocket 取得)：
        .lq.Route.requestConnection {type: 1, route_id: "route-5", timestamp: 1785075645, 6: "Web"}

    直接改 class method，故所有既有 instance 與後續重連 (AccountSession._reconnect →
    downloader.start()) 都吃得到；重複呼叫為 no-op。"""
    try:
        from tensoul.downloader import MajsoulPaipuDownloader
    except Exception:  # noqa: BLE001 tensoul 尚未可 import 時交由呼叫端稍後再套
        return
    if getattr(MajsoulPaipuDownloader.route_connect, "_ms_patched", False):
        return

    async def patched_route_connect(self, channel, route, route_id):
        req = pb.ReqRequestConnection()
        req.type = 1
        req.route_id = route_id
        req.timestamp = int(time.time())
        await channel.connect(self.MS_HOST)
        # 繞過 Route stub 直接送序列化位元組——stub 只吃 message 物件，塞不進 proto 沒有的欄位。
        res = pb.ResRequestConnection()
        res.ParseFromString(
            await channel.send_request(
                ".lq.Route.requestConnection", req.SerializeToString() + _CONN_PLATFORM_FIELD
            )
        )
        if int(res.error.ByteSize()) > 0:
            await channel.close()
            raise RuntimeError("request connection for route {} failed: error {}".format(
                route_id, res.error.code))

    patched_route_connect._ms_patched = True
    MajsoulPaipuDownloader.route_connect = patched_route_connect


# websockets 客戶端 keepalive 的預設值 (12.0)：每 20s 送一次 ping，20s 內收不到 pong 就
# 自行把連線關掉 (close code 1011 "keepalive ping timeout")。實測長時間批次下載會踩到——
# 台灣→CN 的線路偶爾卡個 20 幾秒、或本機被背景解析/寫檔搶滿 CPU 導致 pong 沒被及時處理，
# 都會讓一條其實還活著的連線被我們自己砍掉，然後整套重連＋重登 (2~5s) 白跑一次。
# 放寬 pong 等待上限即可：會話存活本來就靠應用層心跳 (.lq.Lobby.heatbeat, 6s 一次) 維持，
# 而真的死掉的連線另有下載端 45s 逾時會抓到，不必靠 ws ping 這麼急著判死。
_WS_PING_INTERVAL = float(os.getenv("MS_WS_PING_INTERVAL", "") or 20)
_WS_PING_TIMEOUT = float(os.getenv("MS_WS_PING_TIMEOUT", "") or 90)
# 單一訊息上限。websockets 預設 1 MiB，牌譜回應多半 100~300 KB，但長半莊/大量副露的
# GameDetailRecords 可能逼近上限；超過會被關連線 (1009)，故給足餘裕。
_WS_MAX_SIZE = 32 * 1024 * 1024


def patch_ws_keepalive() -> None:
    """放寬 ms-api MSRPCChannel 建立 websocket 時的 keepalive 參數，並在連線斷掉時
    立刻喚醒等待回應的請求。重複呼叫為 no-op。

    第二件事的理由：ms-api 的 `send_request` 送完封包後 `await evt.wait()`，而負責收訊息
    的 `dispatch_msg` 在連線斷掉時會拋 ConnectionClosed 直接結束——沒有人再去 set 那個
    event，於是「連線斷掉當下正在飛的那一筆」會一路卡到上層 45s 逾時才被判定失敗。
    連線既然已經死了，就該當場失敗、當場進復原流程。"""
    from ms.base import MSRPCChannel  # ms-api；此處才 import 以免影響模組載入順序

    if getattr(MSRPCChannel.connect, "_ms_patched", False):
        return

    import asyncio

    import websockets

    async def _dispatch_and_wake(channel) -> None:
        try:
            await channel.dispatch_msg()
        except Exception:  # noqa: BLE001 連線斷掉就是這個 task 的正常結局；吞掉以免 asyncio
            pass           # 印出整段 "Task exception was never retrieved"（真正的失敗會由
                           # 下面被喚醒的那筆請求回報出來）。
        finally:
            # 喚醒所有還在等回應的請求：send_request 會因 idx 不在 _res 而回傳 None，
            # 上層隨即以「連線層錯誤」失敗 → download_with_retry 判為 session error → 重連。
            for evt in list(channel._req_events.values()):
                evt.set()

    async def patched_connect(self, ms_host):
        self._ws = await websockets.connect(
            self._endpoint, origin=ms_host,
            ping_interval=_WS_PING_INTERVAL, ping_timeout=_WS_PING_TIMEOUT,
            close_timeout=5, max_size=_WS_MAX_SIZE)
        self._msg_dispatcher = asyncio.create_task(_dispatch_and_wake(self))

    patched_connect._ms_patched = True
    MSRPCChannel.connect = patched_connect


def build_login_req(account: str, password: str) -> pb.ReqLogin:
    """建立與現行 web 客戶端一致的完整 ReqLogin (繞過 error 151)。"""
    req = pb.ReqLogin()
    req.account = account
    req.password = hmac.new(b"lailai", password.encode(), hashlib.sha256).hexdigest()
    d = req.device
    d.platform = "pc"
    d.hardware = "pc"
    d.os = "windows"
    d.os_version = "win10"
    d.is_browser = True
    d.software = "Chrome"
    d.sale_platform = "web"
    d.screen_width = 2560
    d.screen_height = 1440
    d.user_agent = _USER_AGENT
    d.screen_type = 2
    req.random_key = str(uuid.uuid4())
    req.client_version.resource = _res_version()
    req.client_version.package = _PKG_VERSION
    req.gen_access_token = True
    for cp in (1, 2, 5, 6, 8, 10, 11):
        req.currency_platforms.append(cp)
    req.client_version_string = _client_version_string()
    req.tag = _LOGIN_TAG
    return req


def build_game_record_req(record_uuid: str) -> pb.ReqGameRecord:
    """下載牌譜的 ReqGameRecord；登入與下載共用同一正確版本字串，避免漂移。"""
    req = pb.ReqGameRecord()
    req.game_uuid = record_uuid
    req.client_version_string = _client_version_string()
    return req


async def login(dl, account: str, password: str) -> str:
    """純 API 登入 (取代 tensoul 舊的 downloader.login)。成功回 access_token，失敗 raise。"""
    res = await dl.lobby.login(build_login_req(account, password))
    if res.error.code or not res.access_token:
        raise RuntimeError(f"登入失敗 code={res.error.code} json={res.error.json_param}")
    await dl.lobby.login_success(pb.ReqCommon())
    beat = pb.ReqLoginBeat()
    beat.contract = dl.MS_LOGIN_BEAT_CONTRACT_UUID
    await dl.lobby.login_beat(beat)
    dl.token = res.access_token
    return res.access_token


def fetch_latest_res_version(timeout: float = 10.0) -> str | None:
    """向雀魂 CN 取得目前資源版本 (version.json 的 version 去掉伺服器後綴，如 0.16.230.w -> 0.16.230)。

    供 error 151 (資源版本過期) 時自動更新使用。網路失敗或格式不符回 None。"""
    try:
        req = urllib.request.Request(_VERSION_JSON_URL, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 網路/解析任何失敗都當作取不到，交由呼叫端回退
        return None
    ver = str(data.get("version") or "").strip()
    for suffix in _VERSION_SUFFIXES:
        if ver.endswith(suffix):
            ver = ver[: -len(suffix)]
            break
    return ver or None


def _parse_ver(v: str) -> list[int] | None:
    try:
        return [int(p) for p in v.strip().split(".")]
    except (ValueError, AttributeError):
        return None


def res_version_candidates(current: str | None = None, span: int = 60,
                           minor_span: int = 15) -> list[str]:
    """產生 error 151 復原時要嘗試的資源版本候選（去重、依優先序）。

    雀魂 patch 號會跳號（實測 2026-06 的 0.16.232 一個月後即 0.16.251，+19），舊的
    span=10 探測不到就整批失敗，故 patch 探測放寬到 +span（預設 60，約數月的改版量）；
    其後補上 minor 換代候選（0.{m+1}.0..minor_span、0.{m+2}.0..minor_span//2，涵蓋
    minor 進位後 patch 重新起算的情境），再接 version.json 抓到的版本（CN web 仍回舊
    Laya 版會被自然濾掉），最後墊上內建預設值。

    注意：fetch_latest_res_version 取自舊 Laya /1/version.json，回的版本（0.11.x）比現行
    Unity WebGL 資源版本（0.16.x）舊，單靠它無法復原——遞增探測才是主要手段。實測
    伺服器對不存在的帳號回 1002 而非 151（帳號檢查先於版本檢查，無法用假帳號探測）——
    這反過來是個好用的判斷：**假帳號若回 151 而不是 1002，就不是資源版本問題**，而是握手/
    請求格式又被改（見 `patch_route_connect`），此時整輪探測必然全滅、只是白燒登入請求；
    探測皆以正確帳密進行，不會累積密碼錯誤。另實測伺服器接受的是「最低可接受版本」
    以上的區間（如最新 0.16.251 時 0.16.250 也可登入），探測會停在第一個被接受的版本。
    探測全滅時，正確版本可從瀏覽器登入雀魂後標題畫面右下角讀得（如 v0.16.251.W…，
    取 0.16.251），或 localStorage 的 prev_res_version。"""
    current = current or _res_version()
    out: list[str] = []
    base = _parse_ver(current)
    if base and len(base) >= 3:
        for inc in range(1, span + 1):
            out.append(".".join(str(n) for n in (base[:2] + [base[2] + inc] + base[3:])))
        for minor_inc, patches in ((1, minor_span), (2, minor_span // 2)):
            for patch in range(patches + 1):
                out.append(".".join(str(n) for n in ([base[0], base[1] + minor_inc, patch] + base[3:])))
    fetched = fetch_latest_res_version()
    if fetched:
        out.append(fetched)
    out.append(_DEFAULT_RES_VERSION)

    seen: set[str] = set()
    uniq: list[str] = []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def is_resource_version_error(exc: BaseException) -> bool:
    """判斷例外是否為雀魂 error 151 (client_version_string 不符 / 資源版本過期)。"""
    return "code=151" in str(exc)


def patch_downloader(dl) -> None:
    """覆寫 downloader.download 的版本字串 (舊 web-{ver} 下載也回 151)；
    僅換掉請求建構，回應處理仍重用原本的 _handle_game_record / make_error_message。"""

    async def patched_download(self, record_uuid, lobby_id=0):
        res = await self.lobby.fetch_game_record(build_game_record_req(record_uuid))
        if res.error.code:
            return self.make_error_message("error_code: %s" % res.error.code)
        return {"is_error": False, "log": self._handle_game_record(res, lobby_id)}

    dl.download = types.MethodType(patched_download, dl)
