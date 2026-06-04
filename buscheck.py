#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
buscheck — KOBUS 고속버스 잔여석 텔레그램 알림봇

서울경부(010) -> 대전청사(305), 2026-06-05, 16:00~18:00 출발 차편 중
잔여석이 생기면 텔레그램으로 알려준다.

표준 라이브러리만 사용 (urllib). 외부 패키지 불필요.
"""

import json
import os
import ssl
import time
import http.cookiejar
import urllib.parse
import urllib.request
from datetime import datetime

# KOBUS 서버는 구형 TLS cipher를 써서 파이썬 기본 컨텍스트로는 핸드셰이크가 막힌다.
# SECLEVEL을 1로 낮추되 인증서 검증은 그대로 유지한다.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.set_ciphers("DEFAULT@SECLEVEL=1")

# ───────────────────────── 설정 ─────────────────────────
def _load_token():
    """텔레그램 봇 토큰을 환경변수(TELEGRAM_TOKEN) 또는 token.txt 에서 읽는다.
    (토큰은 절대 코드/깃에 커밋하지 않는다.)"""
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if tok:
        return tok
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        raise SystemExit(
            "텔레그램 토큰이 없습니다. 환경변수 TELEGRAM_TOKEN 을 설정하거나 "
            "token.txt 파일에 토큰을 넣어주세요. (token.txt.example 참고)")


TELEGRAM_TOKEN = _load_token()

DEPR_CD, DEPR_NM = "010", "서울경부"
ARVL_CD, ARVL_NM = "305", "대전청사"
DATE = "20260605"          # 2026-06-05 (6.5일)
WIN_START = "16:00"        # 출발 시간대 (이상)
WIN_END   = "18:00"        # 출발 시간대 (이하)
POLL_SEC  = 30             # 조회 주기(초)

KOBUS_PAGE = "https://www.kobus.co.kr/oprninf/alcninqr/oprnAlcnPage.do"
KOBUS_AJAX = "https://www.kobus.co.kr/oprninf/alcninqr/readAlcnSrch.ajax"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
# ────────────────────────────────────────────────────────


def hhmm_to_min(s):
    s = s.replace(" ", "")
    return int(s[:2]) * 60 + int(s[3:5])


WIN_S = hhmm_to_min(WIN_START)
WIN_E = hhmm_to_min(WIN_END)


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ───────────────────── 상태 저장/복원 ─────────────────────
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"chat_ids": [], "tg_offset": 0, "available": [], "started": False}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ───────────────────────── 텔레그램 ──────────────────────
def tg_call(method, params=None, timeout=20):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    data = urllib.parse.urlencode(params or {}).encode() if params else None
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def tg_send(chat_id, text):
    try:
        tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
        return True
    except Exception as e:
        log(f"텔레그램 전송 실패(chat={chat_id}): {e}")
        return False


def tg_discover_chats(st):
    """봇에게 메시지를 보낸 사용자의 chat_id를 학습한다."""
    try:
        res = tg_call("getUpdates", {"offset": st["tg_offset"], "timeout": 0})
    except Exception as e:
        log(f"getUpdates 실패: {e}")
        return
    new_chat = None
    for upd in res.get("result", []):
        st["tg_offset"] = upd["update_id"] + 1
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid and cid not in st["chat_ids"]:
            st["chat_ids"].append(cid)
            new_chat = cid
            log(f"새 chat_id 등록: {cid} ({chat.get('first_name','')} {chat.get('username','')})")
    if new_chat is not None:
        tg_send(new_chat,
                f"✅ <b>buscheck 봇 연결됨</b>\n"
                f"{DEPR_NM} → {ARVL_NM} ({DATE[:4]}-{DATE[4:6]}-{DATE[6:]})\n"
                f"{WIN_START}~{WIN_END} 출발 차편 잔여석이 생기면 알려드릴게요.\n"
                f"(조회 주기: {POLL_SEC}초)")


# ───────────────────────── KOBUS ────────────────────────
_opener = None


def kobus_opener(fresh=False):
    global _opener
    if _opener is None or fresh:
        cj = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_SSL_CTX),
            urllib.request.HTTPCookieProcessor(cj),
        )
        _opener.addheaders = [("User-Agent", UA)]
        # 세션 쿠키 확보용 워밍업
        try:
            _opener.open(KOBUS_PAGE, timeout=20).read()
        except Exception as e:
            log(f"KOBUS 워밍업 실패: {e}")
    return _opener


def kobus_query():
    """16:00~18:00 출발 + 잔여석>0 차편 리스트를 반환. 실패 시 None."""
    params = {
        "deprCd": DEPR_CD, "deprNm": DEPR_NM,
        "arvlCd": ARVL_CD, "arvlNm": ARVL_NM,
        "crchDeprArvlYn": "N", "deprDtm": DATE,
        "busClsCd": "0", "prmmDcYn": "N",
    }
    data = urllib.parse.urlencode(params).encode()
    for attempt in (1, 2):
        op = kobus_opener(fresh=(attempt == 2))
        req = urllib.request.Request(KOBUS_AJAX, data=data, headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": KOBUS_PAGE,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        })
        try:
            with op.open(req, timeout=25) as r:
                d = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:
            log(f"KOBUS 조회 실패(시도 {attempt}): {e}")
            if attempt == 2:
                return None
            time.sleep(2)
    else:
        return None

    if d.get("rotVldChc") == "N":
        return []

    out = []
    for r in d.get("alcnAllList") or []:
        t = r.get("DEPR_TIME_DVS", "").replace(" ", "")
        if len(t) < 5:
            continue
        m = hhmm_to_min(t)
        if not (WIN_S <= m <= WIN_E):
            continue
        rmn = int(r.get("RMN_SATS_NUM", 0) or 0)
        out.append({
            "time": t,
            "grade": r.get("BUS_CLS_NM", ""),
            "company": r.get("CACM_MN", ""),
            "rmn": rmn,
            "tot": int(r.get("TOT_SATS_NUM", 0) or 0),
            "fare": int(r.get("ADLT_FEE", 0) or 0),
        })
    out.sort(key=lambda x: x["time"])
    return out


def bus_key(b):
    return f"{b['time']}|{b['grade']}|{b['company']}"


# ───────────────────────── 메인 루프 ─────────────────────
def main():
    log(f"buscheck 시작 — {DEPR_NM}→{ARVL_NM} {DATE} {WIN_START}~{WIN_END}, 주기 {POLL_SEC}s")
    st = load_state()

    # 시작 알림(최초 1회) — 등록된 chat이 있으면
    tg_discover_chats(st)
    if not st.get("started") and st["chat_ids"]:
        for cid in st["chat_ids"]:
            tg_send(cid,
                    f"🚌 <b>buscheck 모니터링 시작</b>\n"
                    f"{DEPR_NM} → {ARVL_NM} ({DATE[:4]}-{DATE[4:6]}-{DATE[6:]})\n"
                    f"{WIN_START}~{WIN_END} 출발 차편 잔여석을 {POLL_SEC}초마다 확인합니다.")
        st["started"] = True
    save_state(st)

    prev_avail = set(st.get("available", []))

    while True:
        # 새 사용자 등록 체크
        tg_discover_chats(st)

        buses = kobus_query()
        if buses is None:
            save_state(st)
            time.sleep(POLL_SEC)
            continue

        avail = {bus_key(b): b for b in buses if b["rmn"] > 0}
        cur_keys = set(avail.keys())
        new_keys = cur_keys - prev_avail

        if new_keys and st["chat_ids"]:
            lines = ["🎫 <b>잔여석 발생!</b>",
                     f"{DEPR_NM} → {ARVL_NM} ({DATE[:4]}-{DATE[4:6]}-{DATE[6:]})", ""]
            for k in sorted(new_keys, key=lambda k: avail[k]["time"]):
                b = avail[k]
                lines.append(
                    f"🕘 <b>{b['time']}</b> · {b['grade']} · {b['company']}\n"
                    f"   잔여 <b>{b['rmn']}</b>/{b['tot']}석 · {b['fare']:,}원")
            lines.append("")
            lines.append("👉 https://www.kobus.co.kr 에서 예매하세요")
            text = "\n".join(lines)
            for cid in st["chat_ids"]:
                tg_send(cid, text)
            log(f"알림 전송: {len(new_keys)}건 -> {st['chat_ids']}")

        # 로그(현황)
        status = ", ".join(f"{b['time']}={b['rmn']}/{b['tot']}" for b in buses) or "배차없음"
        log(f"조회 OK | 창내 {len(buses)}대 | 잔여>0 {len(cur_keys)}대 | {status}")

        prev_avail = cur_keys
        st["available"] = sorted(cur_keys)
        save_state(st)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("종료")
