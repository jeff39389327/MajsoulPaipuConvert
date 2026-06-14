import asyncio
import hashlib
import hmac
import random
import uuid

import aiohttp
import ms.protocol_pb2 as pb
from ms.base import MSRPCChannel
from ms.rpc import Lobby
from ms.rpc import Route

try:
    from websockets import State
except ImportError:
    from websockets.protocol import State

from websockets.exceptions import ConnectionClosedError
from datetime import datetime, timezone

from .cfg import cfg, ms_cfg
from .constants import RUNES, JPNAME
from .parser import MajsoulPaipuParser


class MajsoulLoginError(BaseException):
    ...


class MajsoulDownloadError(BaseException):
    def __init__(self, code: int):
        self.code = code


class MajsoulPaipuDownloader:
    MS_HOST = "https://game.maj-soul.com"
    MS_LOGIN_BEAT_CONTRACT_UUID = "DF2vkXCnfeXp4WoGSBGNcJBufZiMN3UP"

    def __init__(self, with_http_server=False, tensoul_version="0.0.0"):
        self.tensoul_version = tensoul_version
        self.with_http_server = with_http_server

    async def start(self):
        await self._connect()

    async def close(self):
        try:
            # getattr: a failed first _connect() leaves the instance with no channel at all
            channel = getattr(self, "channel", None)
            if channel:
                await channel.close()
        except ConnectionClosedError:
            pass

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _connect(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("{}/1/version.json".format(self.MS_HOST)) as res:
                version_res = await res.json()
                self.version = version_res["version"]
                self.version_to_force = self.version.replace(".w", "")

            async with session.get("{}/1/v{}/config.json".format(self.MS_HOST, self.version)) as res:
                config = await res.json()
                default_gate = 1
                regions = config["ip"][0]["gateways"]
                config_region_index = ms_cfg['connect_region_number'] - 1
                region_index = config_region_index if len(regions) > config_region_index else default_gate
                url = regions[region_index]["url"]

            async with session.get("{}/api/clientgate/routes?platform=Web&version={}".format(url, self.version)) as res:
               routes = await res.json()
               if "routes" in routes['data']:
                   routes = routes['data']["routes"]
                   server = random.choice(routes)
                   self.endpoint = "wss://{}/gateway".format(server['domain'])
                   self.route_id = str(server['id']).strip()
               else:
                   raise RuntimeError("Cannot detect endpoint. Response: " + await res.text())

        channel = MSRPCChannel(self.endpoint)
        lobby = Lobby(channel)
        route = Route(channel)
        await self.route_connect(channel=channel, route=route, route_id=self.route_id)
        # publish only after the websocket is fully connected — concurrent callers
        # otherwise hit a half-built channel (_ws is still None -> AttributeError on send)
        self.channel = channel
        self.lobby = lobby
        self.route = route
        if self.with_http_server:
            asyncio.create_task(self.sustain(route=self.route))

    async def route_connect(self, channel, route, route_id):
        await channel.connect(self.MS_HOST)
        utc_now = int(datetime.now(timezone.utc).timestamp() * 1000)
        req_connection = pb.ReqRequestConnection()
        req_connection.type = 3
        req_connection.route_id = route_id
        req_connection.timestamp = utc_now
        req_connection_result = await route.request_connection(req_connection)
        if int(req_connection_result.error.ByteSize()) > 0:
            await channel.close()
            raise RuntimeError("request connection for route {} failed".format(route_id))

    def is_channel_connection_open(self, channel) -> bool:
        return channel._ws.state == State.OPEN

    async def sustain(self, route, ping_interval=4):
        '''
        Looping coroutine that keeps the connection to the server alive.
        '''
        try:
            while self.is_channel_connection_open(self.channel):
                # first ping ws socket
                await self.channel._ws.ping()
                # second call in-game heartbeat
                req_heartbeat = pb.ReqHeartbeat()
                req_heartbeat.delay = 0
                req_heartbeat.no_operation_counter = 0
                req_heartbeat.platform = 11
                req_heartbeat.network_quality = 0
                res_heatbeat = await route.heartbeat(req_heartbeat)
                if int(res_heatbeat.error.ByteSize()) > 0:
                    await self.channel.close()
                await asyncio.sleep(ping_interval)
        except asyncio.CancelledError:
            print("`sustain` task cancelled")
        except Exception as e:
            print(f"Exception occurred in `sustain` task: {e}")

    async def login(self, username, password):
        uuid_key = str(uuid.uuid1())

        req = pb.ReqLogin()
        req.account = username
        req.password = hmac.new(b"lailai", password.encode(), hashlib.sha256).hexdigest()
        req.device.is_browser = True
        req.random_key = uuid_key
        req.gen_access_token = True
        req.client_version_string = f"web-{self.version_to_force}"
        req.currency_platforms.append(2)

        res = await self.lobby.login(req)
        token = res.access_token
        if not token:
            raise MajsoulLoginError(res)

        req_login_success = pb.ReqCommon()
        await self.lobby.login_success(req_login_success)
        req_login_beat = pb.ReqLoginBeat()
        req_login_beat.contract = self.MS_LOGIN_BEAT_CONTRACT_UUID
        await self.lobby.login_beat(req_login_beat)
        self.token = token

    def make_error_message(self, error_msg):
        return {"is_error": True, "error_msg": error_msg}

    def start_server(self, host, port):
        from flask import Flask, request
        from tornado.wsgi import WSGIContainer
        from tornado.httpserver import HTTPServer
        from tornado.ioloop import IOLoop
        import ujson as json

        app = Flask(__name__)
        app_token = ms_cfg['app_token']
        is_token_auth = ms_cfg['is_token_auth']
        downloader = self

        def check_token(request):
            if is_token_auth:
                request_token = request.args.get('app_token')
                return app_token == request_token
            return True

        def make_json_response(data):
            return app.response_class(response=json.dumps(data),
                                      mimetype='application/json')

        def prepare_lobby_id(lobby_id):
            if not lobby_id:
                lobby_id = 0
            else:
                lobby_id = int(lobby_id)
                if lobby_id < 0:
                    lobby_id = 0
            return lobby_id

        @app.route("/status/", methods=['GET'])
        def status():
            return make_json_response({'version': self.tensoul_version})

        @app.route("/health/", methods=['GET'])
        def health():
            status = 'OK' if self.is_channel_connection_open(self.channel) else 'ERROR'
            return make_json_response({'status': status})

        @app.route("/convert/", methods=['GET'])
        def convert():
            if not check_token(request):
                return make_json_response(self.make_error_message("app_token not valid!"))
            id = request.args.get('id')
            lobby_id = prepare_lobby_id(request.args.get('lobby_id'))
            if id:
                response = asyncio.run(downloader.download(id, lobby_id))
                return make_json_response(response)
            return make_json_response(self.make_error_message("replay id required!"))

        http_server = HTTPServer(WSGIContainer(app))
        http_server.listen(port, host)
        print("==== server start at %s:%s ====" % (host, port))
        if is_token_auth:
            print("The API is GET /convert?id={mahjong_soul_log_id}&app_token={app_token}")
        else:
            print("The API is GET /convert?id={mahjong_soul_log_id}")
        IOLoop.instance().start()

    async def download(self, record_uuid: str, lobby_id: int = 0):
        req = pb.ReqGameRecord()
        req.game_uuid = record_uuid
        req.client_version_string = f'web-{self.version_to_force}'
        res = await self.lobby.fetch_game_record(req)

        if res.error.code:
            return self.make_error_message("error_code: %s" % res.error.code)

        return {"is_error": False, "log": self._handle_game_record(res, lobby_id)}

    def _handle_game_record(self, record, lobby_id):
        res = {}
        ruledisp = ""
        lobby = ""  # usually 0, is the custom lobby number
        nplayers = len(record.head.result.players)
        nakas = nplayers - 1  # default
        tsumoloss_off = False

        res["ver"] = "2.3"  # mlog version number
        res["ref"] = record.head.uuid  # game id - copy and paste into "other" on the log page to view

        # PF4 is yonma, PF3 is sanma
        res["ratingc"] = f"PF{nplayers}"

        # rule display
        if nplayers == 3:
            ruledisp += RUNES["sanma"][JPNAME]
        if record.head.config.meta.mode_id:  # ranked or casual
            ruledisp += cfg["desktop"]["matchmode"]["map_"][str(record.head.config.meta.mode_id)]["room_name_jp"]
        elif record.head.config.meta.room_id:  # friendly
            lobby = f": {record.head.config.meta.room_id}"  # can set room number as lobby number
            ruledisp += RUNES["friendly"][JPNAME]  # "Friendly"
            nakas = record.head.config.mode.detail_rule.dora_count
            tsumoloss_off = nplayers == 3 and not record.head.config.mode.detail_rule.have_zimosun
        elif record.head.config.meta.contest_uid:  # tourney
            lobby = f": {record.head.config.meta.contest_uid}"
            ruledisp += RUNES["tournament"][JPNAME]  # "Tournament"
            nakas = record.head.config.mode.detail_rule.dora_count
            tsumoloss_off = nplayers == 3 and not record.head.config.mode.detail_rule.have_zimosun

        if record.head.config.mode.mode == 1:
            ruledisp += RUNES["tonpuu"][JPNAME]  # " East"
        elif record.head.config.mode.mode == 2:
            ruledisp += RUNES["hanchan"][JPNAME]

        if record.head.config.meta.mode_id == 0 and record.head.config.mode.detail_rule.dora_count == 0:
            res["rule"] = {"disp": ruledisp, "aka53": 0, "aka52": 0, "aka51": 0}
        else:
            res["rule"] = {"disp": ruledisp, "aka53": 1, "aka52": 2 if nakas == 4 else 1,
                           "aka51": 1 if nplayers == 4 else 0}

        # tenhou custom lobby - could be tourney id or friendly room for mjs. appending to title instead to avoid 3->C etc. in tenhou.net/5
        room_id = int(record.head.config.meta.room_id)
        if room_id > 0:
            res["lobby"] = room_id
        else:
            res["lobby"] = lobby_id

        # autism to fix logs with AI
        # ranks
        res["dan"] = [""] * nplayers
        for e in record.head.accounts:
            res["dan"][e.seat] = cfg["level_definition"]["level_definition"]["map_"][str(e.level.id)]["full_name_jp"]

        # level score, no real analog to rate
        res["rate"] = [0] * nplayers
        for e in record.head.accounts:
            res["rate"][e.seat] = e.level.score if e.level.score else 0  # level score, closest thing to rate

        # sex
        res["sx"] = ['C'] * nplayers

        # >names
        res["name"] = ["AI"] * nplayers
        for e in record.head.accounts:
            res["name"][e.seat] = e.nickname

        # scores
        scores = [[e.seat, e.part_point_1, e.total_point / 1000] for e in record.head.result.players]
        res["sc"] = [0] * nplayers * 2
        for i, e in enumerate(scores):
            res["sc"][2 * e[0]] = e[1]
            res["sc"][2 * e[0] + 1] = e[2]

        # optional title - why not give the room and put the timestamp here
        res["title"] = [ruledisp + lobby, record.head.end_time]

        wrapper = pb.Wrapper()
        wrapper.ParseFromString(record.data)

        details = pb.GameDetailRecords()
        details.ParseFromString(wrapper.data)

        converter = MajsoulPaipuParser(tsumoloss_off=tsumoloss_off)
        # mjai needs game-level info from the head: player names (per seat), whether
        # aka fives are in play, and tonpuu(4)/hanchan(0) for kyoku_first.
        aka_flag = bool(res["rule"].get("aka51") or res["rule"].get("aka52")
                        or res["rule"].get("aka53"))
        kyoku_first = 4 if record.head.config.mode.mode == 1 else 0
        converter.set_mjai_header(res["name"], aka_flag, kyoku_first)
        if details.version < 210715 and len(details.records) > 0:
            for rec in details.records:
                round_record_wrapper = pb.Wrapper()
                round_record_wrapper.ParseFromString(rec)

                log = getattr(pb, round_record_wrapper.name[len(".lq."):])()
                log.ParseFromString(round_record_wrapper.data)
                converter.feed(log)

                res["log"] = [e.dump() for e in converter.getvalue()]
        else:
            for act in details.actions:
                if len(act.result) != 0:
                    round_record_wrapper = pb.Wrapper()
                    round_record_wrapper.ParseFromString(act.result)

                    log = getattr(pb, round_record_wrapper.name[len(".lq."):])()
                    log.ParseFromString(round_record_wrapper.data)
                    converter.feed(log)

                    res["log"] = [e.dump() for e in converter.getvalue()]

        # mjai event stream (sanma 3-seat / yonma 4-seat), built in lock-step above.
        res["mjai"] = converter.finalize_mjai()

        res["playerMapping"] = self._preparePlayerMapping(record)

        return res

    def _preparePlayerMapping(self, record):
        seatPlayerMapping = {}
        botsMapping = {
            0: {'nickname': 'AI1', 'account_id': -1001},
            1: {'nickname': 'AI2', 'account_id': -1002},
            2: {'nickname': 'AI3', 'account_id': -1003},
            3: {'nickname': 'AI4', 'account_id': -1004}
        }
        for account in record.head.accounts:
            current_seat = int(account.seat)
            if current_seat in botsMapping:
                del botsMapping[current_seat]
            seatPlayerMapping[current_seat] = {'nickname': account.nickname, 'account_id': account.account_id}

        # normalize AI name and id for pantheon
        bot_index = 1
        bot_account_id = -1001
        for key, value in botsMapping.items():
            value['nickname'] = "AI%d" % bot_index
            value['account_id'] = bot_account_id
            seatPlayerMapping[int(key)] = value
            bot_index = bot_index + 1
            bot_account_id = bot_account_id - 1

        playerMapping = []
        for result_seat in range(len(record.head.result.players)):
            playerMapping.append(seatPlayerMapping[int(result_seat)])
        return playerMapping
