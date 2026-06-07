# -*- coding: utf-8 -*-
"""
ms_patch —— 雀魂 CN 登入/下載的可攜式補丁 (被 git 追蹤，不依賴 gitignored 的
tensoul-py-ng vendored 修改)。

為什麼需要這支
--------------
tensoul-py-ng 久未更新：登入/下載送的 client_version_string 仍是舊格式
"web-{version}" (取自已棄用的 /1/version.json，回 0.11.252.w)。現行雀魂客戶端
已換成 Unity WebGL，伺服器登入/下載改檢查 **resource version**，舊請求一律回
error 151。實測 151 檢查 resource version (client_version_string)，package 不影響。

由於 `tensoul-py-ng/` 在 .gitignore 內 (每位使用者各自 clone)，補丁不能只改 vendored
檔，否則別人重新 clone 又會 151。本模組把修正放在**被追蹤的 repo 程式碼**，於 runtime
套用，使任何使用者只要在 config.env 填帳密即可運作 (毋需手動改 tensoul、毋需 token)。

雀魂改版資源後若再現 151：更新 MS_RES_VERSION (環境變數或下方預設) 即可。
新值來源：瀏覽器登入後 localStorage 的 prev_res_version。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import types
import uuid

import ms.protocol_pb2 as pb  # 來自 ms-api，與 tensoul 套件無關

# === 現行雀魂 CN web 客戶端版本 (env 可覆寫) ===
MS_RES_VERSION = os.getenv("MS_RES_VERSION", "0.16.230")
MS_PKG_VERSION = os.getenv("MS_PKG_VERSION", "4.0.44")
MS_CLIENT_VERSION_STRING = os.getenv("MS_CLIENT_VERSION_STRING", f"WebGL_2022-{MS_RES_VERSION}")
MS_LOGIN_TAG = os.getenv("MS_TAG", "cn")
MS_USER_AGENT = os.getenv(
    "MS_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
)
# CN 服為 region 1
MS_CONNECT_REGION = int(os.getenv("MS_CONNECT_REGION", "1"))


def ensure_ms_cfg(tensoul_dir: str = "tensoul-py-ng") -> None:
    """tensoul 的 cfg.py 在 import 時就讀 ms_cfg.json，缺檔會 import 失敗。
    若不存在則自動建立 (CN, region=1)。**必須在 import tensoul 之前呼叫。**"""
    cfg_path = os.path.join(tensoul_dir, "tensoul", "ms_cfg.json")
    if os.path.exists(cfg_path):
        return
    example = os.path.join(tensoul_dir, "tensoul", "ms_cfg.example.json")
    data = {
        "app_token": "token",
        "is_token_auth": False,
        "ms_username": "user",
        "ms_password": "password",
        "server_host": "127.0.0.1",
        "server_port": "8080",
    }
    if os.path.exists(example):
        try:
            with open(example, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["connect_region_number"] = MS_CONNECT_REGION
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def build_login_req(account: str, password: str) -> "pb.ReqLogin":
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
    d.user_agent = MS_USER_AGENT
    d.screen_type = 2
    req.random_key = str(uuid.uuid4())
    req.client_version.resource = MS_RES_VERSION
    req.client_version.package = MS_PKG_VERSION
    req.gen_access_token = True
    for cp in (1, 2, 5, 6, 8, 10, 11):
        req.currency_platforms.append(cp)
    req.client_version_string = MS_CLIENT_VERSION_STRING
    req.tag = MS_LOGIN_TAG
    return req


async def login(dl, account: str, password: str) -> str:
    """純 API 登入 (取代 tensoul 舊的 downloader.login)。成功回 access_token，失敗 raise。"""
    res = await dl.lobby.login(build_login_req(account, password))
    if res.error.code:
        raise RuntimeError(f"登入失敗 code={res.error.code} json={res.error.json_param}")
    if not res.access_token:
        raise RuntimeError(f"登入無 token: {res}")
    await dl.lobby.login_success(pb.ReqCommon())
    beat = pb.ReqLoginBeat()
    beat.contract = dl.MS_LOGIN_BEAT_CONTRACT_UUID
    await dl.lobby.login_beat(beat)
    dl.token = res.access_token
    return res.access_token


def patch_downloader(dl) -> None:
    """覆寫 downloader.download 的 client_version_string (舊 web-{ver} 下載也會回 151)。"""

    async def patched_download(self, record_uuid, lobby_id=0):
        req = pb.ReqGameRecord()
        req.game_uuid = record_uuid
        req.client_version_string = MS_CLIENT_VERSION_STRING
        res = await self.lobby.fetch_game_record(req)
        if res.error.code:
            return self.make_error_message("error_code: %s" % res.error.code)
        return {"is_error": False, "log": self._handle_game_record(res, lobby_id)}

    dl.download = types.MethodType(patched_download, dl)
