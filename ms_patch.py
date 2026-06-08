# -*- coding: utf-8 -*-
"""
ms_patch —— 雀魂 CN 登入/下載的可攜式補丁 (被 git 追蹤，不依賴 gitignored 的
tensoul-py-ng vendored 修改)。

為什麼需要這支
--------------
tensoul-py-ng 久未更新：登入/下載送的 client_version_string 仍是舊格式
"web-{version}" (取自已棄用的 /1/version.json，回 0.11.252.w)。現行雀魂客戶端
已換成 Unity WebGL，伺服器登入/下載改檢查 **resource version**，舊請求一律回
error 151。實測 151 只看 resource version (client_version_string)，package / UA /
tag 不影響。

由於 `tensoul-py-ng/` 在 .gitignore 內 (每位使用者各自 clone)，補丁不能只改 vendored
檔，否則別人重新 clone 又會 151。本模組把修正放在**被追蹤的 repo 程式碼**，於 runtime
套用，使任何使用者只要在 config.env 填帳密即可運作 (毋需瀏覽器、毋需 token、毋需改 tensoul)。

雀魂改版資源後若再現 151：設環境變數 MS_RES_VERSION (或 config.env 內同名)，或改下方
_DEFAULT_RES_VERSION 即可。新值來源：瀏覽器登入雀魂後 localStorage 的 prev_res_version。
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import types
import urllib.request
import uuid

import ms.protocol_pb2 as pb  # 來自 ms-api，與 tensoul 套件無關

# 只有 resource version 會被 151 檢查，故僅此一項開放覆寫；其餘為 CN 固定值
# (專案 CLAUDE.md 已限定 CN-only)。MS_RES_VERSION 於登入時才讀取，使 config.env
# 的覆寫生效 (模組 import 早於 dotenv.load_dotenv)。
_DEFAULT_RES_VERSION = "0.16.230"
_PKG_VERSION = "4.0.44"          # 伺服器不檢查，僅為與真實客戶端一致
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
    若不存在則以 ms_cfg.example.json 為底建立並設成 CN。**必須在 import tensoul 之前呼叫。**"""
    pkg_dir = _tensoul_pkg_dir(tensoul_dir)
    cfg_path = os.path.join(pkg_dir, "ms_cfg.json")
    if os.path.exists(cfg_path):
        return
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
