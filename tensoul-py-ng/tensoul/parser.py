from math import ceil
from typing import List

import ms.protocol_pb2 as pb

from .constants import DAISUUSHI, DAISANGEN, YSCORE
from .model import Kyoku, Round, Tile, DiscardSymbol, ChiSymbol, TileType, PonSymbol, DaiminkanSymbol, \
    ZeroSymbol, AnkanSymbol, KakanSymbol, SpecialRyukyoku, Ryukyoku, Agari, SingleAgari, PeSymbol, AgariPoint, Yaku
from .utils import pad_list, relative_seating


class MajsoulPaipuParser:
    def __init__(self, *, tsumoloss_off: bool = False, allow_kigiage: bool = False):
        self.kyokus = []

        self.tsumoloss_off = tsumoloss_off
        self.allow_kigiage = allow_kigiage

        # ---- MJAI direct output (sanma + yonma) ----
        # Emitted in lock-step with the same in-order record walk that builds the
        # tenhou.net/6 kyokus, so it reuses all of this parser's scoring/delta logic
        # (pao, tsumo-loss, multi-ron delta split). Targets the mjai schema consumed
        # by mortal-sanma's libriichi3p (3-seat for sanma, 4-seat for yonma): true
        # NUM_PLAYERS seats, nukidora event, actors bounded to nplayers.
        self.mjai = []
        self._mjai_started = False
        self._mjai_names = None
        self._mjai_aka = True
        self._mjai_kyoku_first = 0
        self._mjai_dora_count = 0
        self._pending_reach = None

    def set_mjai_header(self, names, aka_flag, kyoku_first):
        """Provide game-level info (from record.head) needed for the mjai start_game."""
        self._mjai_names = list(names)
        self._mjai_aka = bool(aka_flag)
        self._mjai_kyoku_first = kyoku_first

    def finalize_mjai(self):
        """Return the full mjai event stream (appends end_game once). Call after feeding all records."""
        if self._mjai_started:
            self.mjai.append({"type": "end_game"})
            self._mjai_started = False  # idempotent: a second call won't re-append
        return self.mjai

    def _me(self, **ev):
        self.mjai.append(ev)

    def _mjai_accept_riichi(self):
        if self._pending_reach is not None:
            self._me(type="reach_accepted", actor=self._pending_reach)
            self._pending_reach = None

    def _mjai_flush_dora(self):
        # emit `dora` events for indicators revealed after the initial one (kan dora).
        # index 0 is the kyoku's initial dora_marker (carried on start_kyoku), not an event.
        while self._mjai_dora_count < len(self.cur.doras):
            self._me(type="dora", dora_marker=self.cur.doras[self._mjai_dora_count].encode_mjai())
            self._mjai_dora_count += 1

    def _mjai_meld(self, log):
        """Resolve (target, called pai, consumed) for chi/pon/daiminkan from `froms`.

        majsoul gives `froms[i]` = seat each tile of `log.tiles` came from; the one
        not from the calling seat is the claimed tile, and its owner is the target."""
        tiles = list(log.tiles)
        froms = list(getattr(log, "froms", []) or [])
        called_idx = next((i for i, fr in enumerate(froms) if fr != log.seat),
                          len(tiles) - 1)
        target = froms[called_idx] if froms else self.ldseat
        pai = Tile.parse(tiles[called_idx]).encode_mjai()
        consumed = [Tile.parse(t).encode_mjai()
                    for i, t in enumerate(tiles) if i != called_idx]
        if log.type != 0:
            # pon / daiminkan: consumed are all the same value; list the aka five last,
            # matching mjai-reviewer's convention (chi keeps majsoul's order).
            consumed.sort(key=lambda s: s.endswith("r"))
        return target, pai, consumed

    def feed(self, log):
        if isinstance(log, pb.RecordNewRound):
            self._handle_new_round(log)
        elif isinstance(log, pb.RecordDiscardTile):
            self._handle_discard_tile(log)
        elif isinstance(log, pb.RecordDealTile):
            self._handle_deal_tile(log)
        elif isinstance(log, pb.RecordChiPengGang):
            self._handle_chi_peng_gang(log)
        elif isinstance(log, pb.RecordAnGangAddGang):
            self._handle_an_gang_add_gang(log)
        elif isinstance(log, pb.RecordBaBei):
            self._handle_ba_bei(log)
        elif isinstance(log, pb.RecordLiuJu):
            self._handle_liu_ju(log)
        elif isinstance(log, pb.RecordNoTile):
            self._handle_no_tile(log)
        elif isinstance(log, pb.RecordHule):
            self._handle_hu_le(log)

    def _handle_new_round(self, log):
        self.cur = Kyoku(nplayers=len(log.scores),
                         round=Round(4 * log.chang + log.ju, log.ben, log.liqibang),
                         initscores=pad_list(list(log.scores), 4, 0),
                         doras=[Tile.parse(log.dora)] if log.dora else [Tile.parse(t) for t in log.doras],
                         draws=[[] for i in range(4)],
                         discards=[[] for i in range(4)],
                         haipais=[[Tile.parse(t) for t in getattr(log, f"tiles{i}")] for i in range(4)]
                         )

        # 转换为庄家摸13张牌的形式
        self.poppedtile = self.cur.haipais[log.ju].pop()
        self.cur.draws[log.ju].append(self.poppedtile)

        # information we need, but can 't expect in every record
        self.dealerseat = log.ju
        self.ldseat = -1  # who dealt the last tile
        self.nriichi = 0  # number of current riichis - needed for scores, abort workaround
        self.priichi = False
        self.nkan = 0  # number of current kans - only for abort workaround

        # 计算包牌
        self.nowinds = [0] * self.cur.nplayers  # counter for each players open wind pons/kans
        self.nodrags = [0] * self.cur.nplayers
        self.paowind = -1  # seat of who dealt the final wind, -1 if no one is responsible
        self.paodrag = -1

        # ---- MJAI: start_game (once) / start_kyoku / dealer's first draw ----
        nplayers = self.cur.nplayers
        if not self._mjai_started:
            names = (self._mjai_names[:nplayers] if self._mjai_names
                     else [f"player{i}" for i in range(nplayers)])
            self._me(type="start_game", kyoku_first=self._mjai_kyoku_first,
                     aka_flag=self._mjai_aka, names=names)
            self._mjai_started = True
        self._me(type="start_kyoku",
                 bakaze="ESWN"[log.chang],
                 dora_marker=self.cur.doras[0].encode_mjai(),
                 kyoku=log.ju + 1,
                 honba=log.ben,
                 kyotaku=log.liqibang,
                 oya=log.ju,
                 scores=list(log.scores)[:nplayers],
                 tehais=[[t.encode_mjai() for t in self.cur.haipais[i]] for i in range(nplayers)])
        self._mjai_dora_count = 1
        self._pending_reach = None
        # dealer was dealt 14 tiles; tensoul popped the 14th into draws[oya] above
        self._me(type="tsumo", actor=log.ju, pai=self.poppedtile.encode_mjai())

    def _handle_discard_tile(self, log):
        tile = Tile.parse(log.tile)

        tsumogiri = log.moqie
        # 特判庄家第一张的手摸切
        if log.seat == self.dealerseat and len(self.cur.discards[log.seat]) == 0 and tile == self.poppedtile:
            tsumogiri = True

        sym = DiscardSymbol(tile, tsumogiri)

        # 立直宣言
        if log.is_liqi:
            self.priichi = True
            sym = DiscardSymbol(sym.tile, sym.tsumogiri, True)

        self.cur.discards[log.seat].append(sym)
        self.ldseat = log.seat

        # 更新dora
        if len(log.doras) > len(self.cur.doras):
            self.cur.doras = [Tile.parse(t) for t in log.doras]

        # ---- MJAI: reach (before discard) / dahai / deferred reach_accepted ----
        if log.is_liqi:
            self._me(type="reach", actor=log.seat)
        self._me(type="dahai", actor=log.seat, pai=tile.encode_mjai(), tsumogiri=tsumogiri)
        if log.is_liqi:
            self._pending_reach = log.seat
        self._mjai_flush_dora()

    def _accept_riichi(self):
        if self.priichi:
            self.priichi = False
            self.nriichi += 1

    def _handle_deal_tile(self, log):
        self._accept_riichi()

        # 更新dora
        if len(log.doras) > len(self.cur.doras):
            self.cur.doras = [Tile.parse(t) for t in log.doras]

        self.cur.draws[log.seat].append(Tile.parse(log.tile))

        # ---- MJAI: reach_accepted (if a riichi is pending) then the draw ----
        # flush dora before tsumo: an ankan's new indicator is revealed on this
        # (rinshan) draw record and must precede the drawn tile in mjai.
        self._mjai_accept_riichi()
        self._mjai_flush_dora()
        self._me(type="tsumo", actor=log.seat, pai=Tile.parse(log.tile).encode_mjai())

    def _countpao(self, tile: Tile, owner: int, feeder: int):
        if tile.type != TileType.Z:
            return

        if 1 <= tile.num <= 4:
            self.nowinds[owner] += 1
            if self.nowinds[owner] == 4:
                self.paowind = feeder
        elif 5 <= tile.num <= 7:
            self.nodrags[owner] += 1
            if self.nodrags[owner] == 3:
                self.paodrag = feeder

    def _handle_chi_peng_gang(self, log):
        self._accept_riichi()

        if log.type == 0:
            # chi
            tiles = [Tile.parse(t) for t in log.tiles]
            self.cur.draws[log.seat].append(ChiSymbol(*tiles))
        elif log.type == 1:
            # pon
            tiles = [Tile.parse(t) for t in log.tiles]
            idx = relative_seating(log.seat, self.ldseat)
            self._countpao(tiles[0], log.seat, self.ldseat)
            self.cur.draws[log.seat].append(PonSymbol(tiles[0], tiles[1], tiles[2], idx))
        elif log.type == 2:
            # daiminkan
            tiles = [Tile.parse(t) for t in log.tiles]
            idx = relative_seating(log.seat, self.ldseat)
            self._countpao(tiles[0], log.seat, self.ldseat)
            self.cur.draws[log.seat].append(DaiminkanSymbol(tiles[0], tiles[1], tiles[2], tiles[3], idx))
            self.cur.discards[log.seat].append(ZeroSymbol())  # tenhou drops a 0 in discards for this
            self.nkan += 1
        else:
            raise RuntimeError(f"invalid RecordChiPengGang.type={log.type}")

        # ---- MJAI: reach_accepted (if pending) then chi/pon/daiminkan ----
        self._mjai_accept_riichi()
        target, pai, consumed = self._mjai_meld(log)
        self._me(type={0: "chi", 1: "pon", 2: "daiminkan"}[log.type],
                 actor=log.seat, target=target, pai=pai, consumed=consumed)
        self._mjai_flush_dora()

    def _handle_an_gang_add_gang(self, log):
        # NOTE: e.tiles here is a single tile; naki is placed in discards
        tile = Tile.parse(log.tiles)
        self.ldseat = log.seat

        if log.type == 3:
            # ankan
            self._countpao(tile, log.seat, -1)  # count the group as visible, but don't set pao
            self.cur.discards[log.seat].append(AnkanSymbol(tile.deaka()))
            self.nkan += 1
            # ---- MJAI: ankan (4 concealed tiles; include the aka five if in play) ----
            base = tile.deaka()
            if self._mjai_aka and base.num == 5 and base.type != TileType.Z:
                consumed = [Tile(0, base.type).encode_mjai()] + [base.encode_mjai()] * 3
            else:
                consumed = [base.encode_mjai()] * 4
            self._me(type="ankan", actor=log.seat, consumed=consumed)
            self._mjai_flush_dora()
        elif log.type == 2:
            # kakan
            # find pon and swap in new symbol
            for sy in self.cur.draws[log.seat]:
                if isinstance(sy, PonSymbol) and (sy.tile.deaka() == tile.deaka()):
                    self.cur.discards[log.seat].append(KakanSymbol(sy.a, sy.b, sy.tile, tile, sy.feeder_relative))
                    self.nkan += 1
                    # ---- MJAI: kakan (added tile + the existing pon's 3 tiles) ----
                    self._me(type="kakan", actor=log.seat, pai=tile.encode_mjai(),
                             consumed=[sy.a.encode_mjai(), sy.b.encode_mjai(),
                                       sy.tile.encode_mjai()])
                    self._mjai_flush_dora()
                    break
        else:
            raise RuntimeError(f"invalid RecordAnGangAddGang.type={log.type}")

    def _handle_ba_bei(self, log):
        # kita - this record (only) gives {seat, moqie}
        self.cur.discards[log.seat].append(PeSymbol())

        # ---- MJAI: nukidora (sanma north-pull bonus dora) ----
        self._me(type="nukidora", actor=log.seat, pai="N")

    def _handle_liu_ju(self, log):
        self._accept_riichi()

        if log.type == 1:
            self.cur.result = SpecialRyukyoku.kyushukyuhai
        elif log.type == 2:
            self.cur.result = SpecialRyukyoku.sufonrenda
        elif self.nriichi == 4:
            self.cur.result = SpecialRyukyoku.suuchariichi
        elif self.nkan == 4 or log.type == 3:
            self.cur.result = SpecialRyukyoku.suukaikan
        else:
            raise RuntimeError(f"invalid RecordLiuJu.type={log.type}")

        # ---- MJAI: abortive draw -> ryukyoku with no point movement ----
        self._mjai_accept_riichi()
        self._me(type="ryukyoku", deltas=[0] * self.cur.nplayers)
        self._me(type="end_kyoku")

        self.kyokus.append(self.cur)
        self.cur = None

    def _handle_no_tile(self, log):
        delta = [0, 0, 0, 0]
        all_noten = False
        all_tempai = False

        if log.scores[0].delta_scores is None:
            all_noten = True

        if log.scores[0].delta_scores is not None and len(log.scores[0].delta_scores) == 0:
            all_tempai = True

        if log.scores[0].delta_scores is not None and len(log.scores[0].delta_scores) != 0:
            for score in log.scores:
                for i, g in enumerate(score.delta_scores):
                    # for the rare case of multiple nagashi, we sum the arrays
                    delta[i] += g

        self.cur.result = Ryukyoku(delta, getattr(log, "liujumanguan", False), all_noten, all_tempai)

        # ---- MJAI: exhaustive draw -> ryukyoku with tenpai/noten deltas ----
        self._me(type="ryukyoku", deltas=delta[:self.cur.nplayers])
        self._me(type="end_kyoku")

        self.kyokus.append(self.cur)
        self.cur = None

    def _tlround(self, x):
        """
        round up to nearest hundred iff TSUMOLOSSOFF == true otherwise return 0
        """
        if self.tsumoloss_off:
            return 100 * ceil(x / 100)
        else:
            return 0

    def _parse_hu_le(self, hule, is_head_bump) -> SingleAgari:
        # tenhou log viewer requires 点, 飜) or 役満) to end strings, rest of scoring string is entirely optional
        delta = []  # we need to compute the delta ourselves to handle double/triple ron
        points = None

        # riichi stick points
        if is_head_bump:
            rp = 1000 * (self.nriichi + self.cur.round.riichi_sticks)
        else:
            rp = 0

        # base honba payment
        if is_head_bump:
            hb = 100 * self.cur.round.honba
        else:
            hb = 0

        # sekinin barai logic
        pao = False
        liableseat = -1
        liablefor = 0

        if hule.yiman:
            # only worth checking yakuman hands
            for e in hule.fans:
                if e.id == DAISUUSHI and self.paowind != -1:
                    pao = True
                    liableseat = self.paowind
                    liablefor += e.val  # realistically can only be liable once
                elif e.id == DAISANGEN and self.paodrag != -1:
                    pao = True
                    liableseat = self.paodrag
                    liablefor += e.val  # realistically can only be liable once

        if hule.zimo:
            # ko-oya payment for non-dealer tsumo
            # delta  = [...new Array(kyoku.nplayers)].map(()=> (-hb - h.point_zimo_xian));
            delta = [-hb - hule.point_zimo_xian - self._tlround((1 / 2) * hule.point_zimo_xian)] * self.cur.nplayers
            if hule.seat == self.dealerseat:  # oya tsumo
                delta[hule.seat] = rp + (self.cur.nplayers - 1) * (hb + hule.point_zimo_xian) + 2 * self._tlround(
                    0.5 * hule.point_zimo_xian)
                points = AgariPoint(tsumo=hule.point_zimo_xian + self._tlround((1 / 2) * hule.point_zimo_xian),
                                    oya=True)
            else:  # ko tsumo
                delta[hule.seat] = rp + hb + hule.point_zimo_qin + (self.cur.nplayers - 2) * (
                        hb + hule.point_zimo_xian) + 2 * self._tlround((1 / 2) * hule.point_zimo_xian)
                delta[self.dealerseat] = -hb - hule.point_zimo_qin - self._tlround((1 / 2) * hule.point_zimo_xian)
                points = AgariPoint(tsumo=hule.point_zimo_xian, tsumo_oya=hule.point_zimo_qin)
        else:
            delta = [0] * self.cur.nplayers
            delta[hule.seat] = rp + (self.cur.nplayers - 1) * hb + hule.point_rong
            delta[self.ldseat] = -(self.cur.nplayers - 1) * hb - hule.point_rong
            points = AgariPoint(ron=hule.point_rong, oya=hule.qinjia)
            self.nriichi = -1  # mark the sticks as taken, in case of double ron

        # sekinin barai payments
        #     treat pao as the liable player paying back the other players - safe for multiple yakuman

        if pao:
            # this is how tenhou does it - doesn't really seem to matter to akochan or tenhou.net/5

            if hule.zimo:  # liable player needs to payback n yakuman tsumo payments
                if hule.qinjia:  # dealer tsumo
                    # should treat tsumo loss as ron, luckily all yakuman values round safely for north bisection
                    delta[liableseat] -= 2 * hb + liablefor * 2 * YSCORE[0][1] + self._tlround(
                        0.5 * liablefor * YSCORE[0][1])
                    for i, e in enumerate(delta):
                        if liableseat != i and hule.seat != i and self.cur.nplayers >= i:
                            delta[i] += hb + liablefor * YSCORE[0][1] + self._tlround(
                                0.5 * liablefor * (YSCORE[0][1]))
                    if self.cur.nplayers == 3:  # dealer should get north's payment from liable
                        delta[hule.seat] += (liablefor * YSCORE[0][1] if not self.tsumoloss_off else 0)
                else:  # non-dealer tsumo
                    delta[liableseat] -= (self.cur.nplayers - 2) * hb + liablefor * (
                            YSCORE[1][0] + YSCORE[1][1]) + self._tlround(
                        0.5 * liablefor * YSCORE[1][1])  # ^^same 1st, but ko
                    for i, e in enumerate(delta):
                        if liableseat != i and hule.seat != i and self.cur.nplayers >= i:
                            if self.dealerseat == i:
                                delta[i] += hb + liablefor * YSCORE[1][0] + self._tlround(
                                    0.5 * liablefor * YSCORE[1][1])  # ^^same 1st
                            else:
                                delta[i] += hb + liablefor * YSCORE[1][1] + self._tlround(
                                    0.5 * liablefor * YSCORE[1][1])  # ^^same 1st
            else:  # ron
                # liable seat pays the deal-in seat 1/2 yakuman + full honba
                delta[liableseat] -= (self.cur.nplayers - 1) * hb + 0.5 * liablefor * \
                                     YSCORE[0 if hule.qinjia else 1][2]
                delta[self.ldseat] += (self.cur.nplayers - 1) * hb + 0.5 * liablefor * \
                                      YSCORE[0 if hule.qinjia else 1][2]

        return SingleAgari(seat=hule.seat, ldseat=hule.seat if hule.zimo else self.ldseat,
                           paoseat=liableseat if pao else hule.seat,
                           han=hule.count, fu=hule.fu, yaku=[Yaku(e.id, e.val) for e in hule.fans],
                           oya=hule.qinjia, tsumo=hule.zimo, yakuman=hule.yiman, point=points, delta=delta)

    def _handle_hu_le(self, log):
        agari = []
        ura = []
        is_head_bump = True

        # take the longest ura list - double ron with riichi + dama
        for f in log.hules:
            if f.li_doras is not None and len(ura) < len(f.li_doras):
                ura = [Tile.parse(t) for t in f.li_doras]
            agari.append(self._parse_hu_le(f, is_head_bump))
            is_head_bump = False

        self.cur.result = Agari(agari=agari, uras=ura, round=self.cur.round)

        # ---- MJAI: one hora per winner (deltas already split for multi-ron) ----
        ura_m = [t.encode_mjai() for t in ura]
        for a in agari:
            self._me(type="hora", actor=a.seat, target=a.ldseat,
                     deltas=list(a.delta)[:self.cur.nplayers], ura_markers=ura_m)
        self._me(type="end_kyoku")

        self.kyokus.append(self.cur)
        self.cur = None

    def getvalue(self) -> List[Kyoku]:
        return self.kyokus
