# -*- coding: utf-8 -*-
"""코레일(KTX/ITX/무궁화) 잔여석 조회.

코레일 앱이 쓰는 스케줄 조회 API 를 그대로 호출한다. 로그인은 필요 없고,
앱이 아닌 클라이언트를 막는 anti-bot 헤더(x-dynapath-m-token)만 붙이면 된다.

- 잔여석 조회: POST /classes/com.korail.mobile.seatMovie.ScheduleView
- 역 목록:     POST https://www.korail.com/com/talkLiteStationInfo.do
"""

import random
import string
import time
import urllib.parse

from . import ProviderError, TTLCache, hhmm_to_min, http_json, trip
from .dynapath import DynaPathEngine

NAME = "기차"
BOOK_URL = "https://www.korail.com"

SCHEDULE_URL = ("https://smart.letskorail.com/classes/"
                "com.korail.mobile.seatMovie.ScheduleView")
STATIONS_URL = "https://www.korail.com/com/talkLiteStationInfo.do"
APP_VERSION = "250601002"
DEVICE = "AD"
DEVICE_ID = "558a4f02041657ea"
APP_UA = "Dalvik/2.1.0 (Linux; U; Android 13; SM-S928N Build/TQ3A)"
WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 열차그룹 코드. 'all' 이면 모든 열차를 본다.
TRAIN_TYPES = {
    "ktx": "100", "ktx-sancheon": "100", "ktx-eum": "100", "ktx-cheongryong": "100",
    "saemaeul": "101", "itx-saemaeul": "101",
    "mugunghwa": "102", "nuriro": "102", "itx-maeum": "102",
    "tonggeun": "103",
    "itx-cheongchun": "104",
    "airport": "105",
    "all": "109",
}

# 예약 상태 코드. '11' 만 지금 잡을 수 있는 상태다('좌석많음'~'매진임박').
AVAILABLE = "11"
NOT_SOLD = "00"

MAX_PAGES = 12          # 한 회차에 넘길 최대 페이지 수 (열차 10대/페이지)
PAGE_PAUSE_SEC = 1.0    # 연속 조회 사이 간격

_engine = DynaPathEngine()
_stations = TTLCache(24 * 3600)


def _auth_headers():
    ts = int(time.time() * 1000)
    nonce = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return {
        "x-dynapath-m-token": _engine.generate_token(DEVICE_ID, ts, nonce),
        "User-Agent": APP_UA,
    }


def _load_stations():
    data = http_json(STATIONS_URL, data=b"", headers={
        "User-Agent": WEB_UA,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    rows = (((data.get("s_data") or {}).get("stns") or {}).get("stn")) or []
    names = [s["stn_nm"] for s in rows if s.get("stn_nm")]
    if not names:
        raise ProviderError("코레일 역 목록을 받지 못했습니다.")
    return sorted(set(names))


def stations():
    return _stations.get(_load_stations)


def search_stations(query=""):
    """이름으로 역 찾기. [(None, 역이름), ...] — 코드는 쓰지 않는다."""
    try:
        names = stations()
    except Exception as e:
        raise ProviderError(f"코레일 역 목록 조회 실패: {e}")
    if not query:
        return [(None, n) for n in names]
    q = query.replace(" ", "")
    return [(None, n) for n in names if q in n]


def _resolve_station(text, kind):
    """'청량리역' 처럼 조금 다르게 써도 실제 역 이름으로 맞춰준다."""
    text = str(text).strip()
    try:
        names = stations()
    except Exception:
        return text            # 역 목록을 못 받으면 검증 없이 그대로 쓴다
    if text in names:
        return text
    stripped = text[:-1] if text.endswith("역") and len(text) > 1 else text
    if stripped in names:
        return stripped
    hits = [n for n in names if stripped in n]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ProviderError(f"{kind} 역을 찾을 수 없습니다: {text!r}")
    raise ProviderError(
        f"{kind} 역 {text!r} 이(가) 여러 개와 맞습니다. 정확히 골라주세요: "
        + ", ".join(hits[:12]))


def resolve(w):
    dep = _resolve_station(w["dep"], "출발")
    arrivals = w["arr"] if isinstance(w["arr"], list) else [w["arr"]]
    arrs = [_resolve_station(a, "도착") for a in arrivals]

    train_type = str(w.get("train_type", "all")).lower()
    if train_type not in TRAIN_TYPES:
        raise ProviderError(
            f"train_type 이 잘못됐습니다: {train_type!r} "
            f"(쓸 수 있는 값: {', '.join(sorted(TRAIN_TYPES))})")

    seat_class = str(w.get("seat_class", "any")).lower()
    if seat_class not in ("any", "general", "special"):
        raise ProviderError(
            f"seat_class 는 any/general/special 중 하나여야 합니다: {seat_class!r}")

    w["_dep"] = dep
    w["_arrs"] = arrs
    w["_train_gp"] = TRAIN_TYPES[train_type]
    w["_seat_class"] = seat_class
    w["route_desc"] = f"{dep} → {' / '.join(arrs)}"
    return w


def _query(dep, arr, date, hour, train_gp):
    params = {
        "Device": DEVICE, "Version": APP_VERSION,
        "radJobId": "1", "txtMenuId": "11", "txtJobDv": "", "txtGdNo": "",
        "selGoTrain": train_gp, "txtTrnGpCd": train_gp,
        "txtGoAbrdDt": date, "txtGoHour": hour,
        "txtGoStart": dep, "txtGoEnd": arr,
        "txtCardPsgCnt": "0",
        "txtPsgFlg_1": "1", "txtPsgFlg_2": "0", "txtPsgFlg_3": "0",
        "txtPsgFlg_4": "0", "txtPsgFlg_5": "0", "txtPsgFlg_8": "0",
        "txtSeatAttCd_2": "000", "txtSeatAttCd_3": "000", "txtSeatAttCd_4": "015",
    }
    url = SCHEDULE_URL + "?" + urllib.parse.urlencode(params)
    return http_json(url, data=b"", headers=_auth_headers())


def _rows(data):
    rows = (data.get("trn_infos") or {}).get("trn_info") or []
    return [rows] if isinstance(rows, dict) else rows


def _to_trip(r, seat_class):
    gen_cd, gen_nm = r.get("h_gen_rsv_cd", ""), (r.get("h_gen_rsv_nm") or "").strip()
    spe_cd, spe_nm = r.get("h_spe_rsv_cd", ""), (r.get("h_spe_rsv_nm") or "").strip()

    if seat_class == "general":
        available = gen_cd == AVAILABLE
    elif seat_class == "special":
        available = spe_cd == AVAILABLE
    else:
        available = AVAILABLE in (gen_cd, spe_cd)

    parts = []
    if gen_cd != NOT_SOLD:
        parts.append(f"일반실 {gen_nm}")
    if spe_cd != NOT_SOLD:
        parts.append(f"특실 {spe_nm}")

    waiting = int(r.get("h_rsv_wait_ps_cnt") or 0)
    dep_tm, arr_tm = r["h_dpt_tm"], r["h_arv_tm"]
    trn_no = r["h_trn_no"].lstrip("0") or r["h_trn_no"]

    return trip(
        key=f"{r['h_arv_rs_stn_nm']}|{r['h_trn_no']}|{dep_tm}",
        time_str=f"{dep_tm[:2]}:{dep_tm[2:4]}",
        arr_time=f"{arr_tm[:2]}:{arr_tm[2:4]}",
        label=f"{r.get('h_trn_clsf_nm', '열차')} {trn_no}",
        route=f"{r['h_dpt_rs_stn_nm']} → {r['h_arv_rs_stn_nm']}",
        available=available,
        status=", ".join(parts) or "판매 정보 없음",
        fare=int(r.get("h_rcvd_amt") or 0),
        note=f"예약대기 {waiting}명" if waiting else "",
    )


def fetch(w, log):
    """시간대 안의 열차 목록. 조회 실패 시 None."""
    win_s, win_e = w["_win"]
    found = {}

    for arr in w["_arrs"]:
        hour = f"{win_s // 60:02d}{win_s % 60:02d}00"
        for page in range(MAX_PAGES):
            if page:
                time.sleep(PAGE_PAUSE_SEC)
            try:
                data = _query(w["_dep"], arr, w["date"], hour, w["_train_gp"])
            except Exception as e:
                log(f"코레일 조회 실패({w['_dep']}→{arr}): {e}")
                return None

            if data.get("strResult") != "SUCC":
                msg = (data.get("h_msg_txt") or data.get("h_msg_cd") or "").strip()
                # 그 날짜에 열차가 아예 없거나 아직 발매 전인 경우는 정상 상황이다.
                log(f"코레일 응답({w['_dep']}→{arr}): {msg}")
                break

            rows = _rows(data)
            if not rows:
                break

            for r in rows:
                if r.get("h_dpt_rs_stn_nm") != w["_dep"]:
                    continue
                if r.get("h_arv_rs_stn_nm") != arr:
                    continue
                if not (win_s <= hhmm_to_min(r["h_dpt_tm"][:4]) <= win_e):
                    continue
                t = _to_trip(r, w["_seat_class"])
                found[t["key"]] = t

            last = rows[-1]["h_dpt_tm"]
            if hhmm_to_min(last[:4]) > win_e:
                break
            hour = f"{int(last) + 1:06d}"

    return sorted(found.values(), key=lambda x: (x["time"], x["route"]))
