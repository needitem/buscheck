#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
buscheck — 고속버스/기차 잔여석 텔레그램 알림봇

config.json 에 적어둔 구간·날짜·시간대를 주기적으로 조회해서, 매진이던 차편에
자리가 생기면 텔레그램으로 알려준다. KOBUS(고속버스)와 코레일(KTX/ITX/무궁화)을
같은 방식으로 감시한다.

표준 라이브러리만 사용 (urllib). 외부 패키지 불필요.

    python3 buscheck.py                     # 감시 시작
    python3 buscheck.py --once              # 한 번만 조회해서 출력
    python3 buscheck.py stations korail 안동  # 역/터미널 이름 찾기
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

import providers
from providers import ProviderError, hhmm_to_min

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")
DEFAULT_CONFIG = os.path.join(BASE_DIR, "config.json")

DEFAULT_POLL_SEC = 30
MAX_SLEEP_SEC = 60          # 만기 확인을 위해 이보다 오래는 자지 않는다
ICON = {"kobus": "🚌", "korail": "🚄"}


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ───────────────────────── 설정 ─────────────────────────
def load_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise SystemExit(
            f"설정 파일이 없습니다: {path}\n"
            f"config.example.json 을 복사해서 만들어주세요.")
    except json.JSONDecodeError as e:
        raise SystemExit(f"설정 파일 JSON 오류: {path}\n  {e}")

    watches = cfg.get("watches")
    if not watches:
        raise SystemExit(f"{path} 에 watches 가 비어 있습니다.")

    default_poll = int(cfg.get("poll_sec", DEFAULT_POLL_SEC))
    out = []
    for i, w in enumerate(watches):
        if not w.get("enabled", True):
            continue
        try:
            out.append(prepare_watch(w, default_poll))
        except (ProviderError, KeyError, ValueError) as e:
            name = w.get("name") or f"watches[{i}]"
            raise SystemExit(f"설정 오류 ({name}): {e}")

    if not out:
        raise SystemExit(f"{path} 에 켜져 있는 watch 가 없습니다.")
    return out


def prepare_watch(w, default_poll):
    """설정 한 건을 검증하고 조회에 필요한 값들을 채워 넣는다."""
    w = dict(w)
    for field in ("provider", "dep", "arr", "date", "start", "end"):
        if not w.get(field):
            raise ProviderError(f"{field} 항목이 필요합니다.")

    w["date"] = str(w["date"]).replace("-", "")
    if len(w["date"]) != 8 or not w["date"].isdigit():
        raise ProviderError(f"date 는 YYYYMMDD 형식이어야 합니다: {w['date']!r}")

    win = (hhmm_to_min(w["start"]), hhmm_to_min(w["end"]))
    if win[0] > win[1]:
        raise ProviderError(f"start 가 end 보다 늦습니다: {w['start']} ~ {w['end']}")
    w["_win"] = win

    module = providers.get(w["provider"])
    w["_module"] = module
    w["_icon"] = ICON.get(w["provider"], "🎫")
    w["_poll"] = int(w.get("poll_sec", default_poll))
    module.resolve(w)

    w.setdefault("name", f"{w['route_desc']} {fmt_date(w['date'])}")
    w["_id"] = f"{w['provider']}|{w['route_desc']}|{w['date']}|{w['start']}-{w['end']}"
    # 출발 시간대가 끝나면 더 볼 이유가 없다.
    w["_deadline"] = (datetime.strptime(w["date"], "%Y%m%d")
                      + timedelta(minutes=win[1]))
    w["_next_run"] = 0.0
    return w


def fmt_date(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def watch_header(w):
    return (f"{w['_icon']} <b>{w['route_desc']}</b>\n"
            f"{fmt_date(w['date'])} {w['start']}~{w['end']} 출발")


# ───────────────────── 상태 저장/복원 ─────────────────────
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, json.JSONDecodeError):
        st = {}
    st.setdefault("chat_ids", [])
    st.setdefault("tg_offset", 0)
    st.setdefault("announced", "")
    st.setdefault("watches", {})
    st.pop("available", None)   # 단일 노선만 보던 시절의 키
    st.pop("started", None)
    return st


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


# ───────────────────────── 텔레그램 ──────────────────────
_token = None


def telegram_token():
    """봇 토큰을 환경변수(TELEGRAM_TOKEN) 또는 token.txt 에서 읽는다.
    (토큰은 절대 코드/깃에 커밋하지 않는다.)"""
    global _token
    if _token:
        return _token
    _token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not _token:
        try:
            with open(os.path.join(BASE_DIR, "token.txt"), encoding="utf-8") as f:
                _token = f.read().strip()
        except OSError:
            raise SystemExit(
                "텔레그램 토큰이 없습니다. 환경변수 TELEGRAM_TOKEN 을 설정하거나 "
                "token.txt 파일에 토큰을 넣어주세요. (token.txt.example 참고)")
    return _token


def tg_call(method, params=None, timeout=20):
    import urllib.parse
    import urllib.request

    url = f"https://api.telegram.org/bot{telegram_token()}/{method}"
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


def tg_broadcast(st, text):
    for cid in st["chat_ids"]:
        tg_send(cid, text)


def tg_discover_chats(st, watches):
    """봇에게 메시지를 보낸 사용자의 chat_id를 학습한다."""
    try:
        res = tg_call("getUpdates", {"offset": st["tg_offset"], "timeout": 0})
    except Exception as e:
        log(f"getUpdates 실패: {e}")
        return
    new_chats = []
    for upd in res.get("result", []):
        st["tg_offset"] = upd["update_id"] + 1
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid and cid not in st["chat_ids"]:
            st["chat_ids"].append(cid)
            new_chats.append(cid)
            log(f"새 chat_id 등록: {cid} "
                f"({chat.get('first_name','')} {chat.get('username','')})")
    for cid in new_chats:
        tg_send(cid, "✅ <b>buscheck 봇 연결됨</b>\n\n" + watch_summary(watches))


def watch_summary(watches):
    lines = []
    for w in watches:
        lines.append(watch_header(w) + f"  ·  {w['_poll']}초마다 확인")
    return "\n\n".join(lines)


# ───────────────────────── 알림 ──────────────────────────
def trip_line(w, t):
    when = t["time"] + (f" → {t['arr_time']}" if t["arr_time"] else "")
    line = f"{w['_icon']} <b>{when}</b> · {t['label']}\n   {t['route']}\n   {t['status']}"
    if t["fare"]:
        line += f" · {t['fare']:,}원"
    if t["note"]:
        line += f"\n   {t['note']}"
    return line


def alert_text(w, trips):
    body = "\n\n".join(trip_line(w, t) for t in trips)
    return (f"🎫 <b>잔여석 발생!</b>\n{watch_header(w)}\n\n{body}\n\n"
            f"👉 {w['_module'].BOOK_URL} 에서 예매하세요")


# ───────────────────────── 조회 한 회차 ───────────────────
def run_watch(w, st, notify):
    """한 watch 를 한 번 조회하고, 새로 열린 자리가 있으면 알린다."""
    trips = w["_module"].fetch(w, log)
    if trips is None:
        return

    avail = {t["key"]: t for t in trips if t["available"]}
    entry = st["watches"].setdefault(w["_id"], {})
    prev = set(entry.get("available", []))
    new_keys = set(avail) - prev

    if new_keys and notify and st["chat_ids"]:
        fresh = sorted((avail[k] for k in new_keys), key=lambda t: t["time"])
        tg_broadcast(st, alert_text(w, fresh))
        log(f"[{w['name']}] 알림 전송: {len(fresh)}건 -> {st['chat_ids']}")

    entry["available"] = sorted(avail)
    status = " | ".join(
        f"{t['time']} {t['label']}>{t['route'].split('→')[-1].strip()} {t['status']}"
        for t in trips) or "배차없음"
    log(f"[{w['name']}] 조회 OK | 창내 {len(trips)}대 | 여석 {len(avail)}대 | {status}")


def expire_watches(watches, st, notify, now=None):
    """출발 시간대가 지난 watch 를 정리한다. 남은 watch 목록을 돌려준다."""
    now = now or datetime.now()
    alive = []
    for w in watches:
        if now <= w["_deadline"]:
            alive.append(w)
            continue
        log(f"[{w['name']}] 출발 시간대가 지나 감시를 종료합니다.")
        if notify and st["chat_ids"]:
            tg_broadcast(st, "🏁 <b>감시 종료</b>\n" + watch_header(w)
                         + "\n출발 시간대가 지났습니다.")
        st["watches"].pop(w["_id"], None)
    return alive


# ───────────────────────── 메인 루프 ─────────────────────
def cmd_run(args):
    watches = load_config(args.config)
    st = load_state()

    log(f"buscheck 시작 — watch {len(watches)}건")
    for w in watches:
        log(f"  · [{w['provider']}] {w['route_desc']} {fmt_date(w['date'])} "
            f"{w['start']}~{w['end']} / {w['_poll']}초")

    watches = expire_watches(watches, st, notify=False)
    if not watches:
        raise SystemExit("감시할 차편이 없습니다. 날짜/시간대가 이미 지났습니다.")

    if args.once:
        for w in watches:
            run_watch(w, st, notify=False)
        return

    tg_discover_chats(st, watches)
    signature = "\n".join(sorted(w["_id"] for w in watches))
    if st["announced"] != signature and st["chat_ids"]:
        tg_broadcast(st, "🔔 <b>buscheck 모니터링 시작</b>\n\n" + watch_summary(watches))
        st["announced"] = signature
    save_state(st)

    while True:
        tg_discover_chats(st, watches)

        now = time.monotonic()
        for w in watches:
            if now >= w["_next_run"]:
                run_watch(w, st, notify=True)
                w["_next_run"] = time.monotonic() + w["_poll"]

        watches = expire_watches(watches, st, notify=True)
        save_state(st)
        if not watches:
            log("모든 watch 가 끝났습니다. 종료합니다.")
            return

        wait = min(w["_next_run"] for w in watches) - time.monotonic()
        time.sleep(max(1.0, min(wait, MAX_SLEEP_SEC)))


# ───────────────────── 역/터미널 찾기 ────────────────────
def cmd_stations(args):
    module = providers.get(args.provider)
    try:
        hits = module.search_stations(args.query or "")
    except ProviderError as e:
        raise SystemExit(str(e))
    if not hits:
        raise SystemExit(f"{module.NAME}: {args.query!r} 와(과) 맞는 곳이 없습니다.")
    for code, name in hits:
        print(f"{name}  ({code})" if code else name)
    print(f"\n{len(hits)}곳", file=sys.stderr)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        argv = ["run"] + argv

    parser = argparse.ArgumentParser(
        prog="buscheck", description="고속버스/기차 잔여석 텔레그램 알림봇")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="설정한 구간을 감시한다 (기본)")
    p_run.add_argument("--config", default=DEFAULT_CONFIG, help="설정 파일 경로")
    p_run.add_argument("--once", action="store_true",
                       help="한 번만 조회해서 출력하고 끝낸다 (텔레그램 전송 안 함)")
    p_run.set_defaults(func=cmd_run)

    p_stn = sub.add_parser("stations", help="역/터미널 이름을 찾는다")
    p_stn.add_argument("provider", choices=["kobus", "korail", "bus", "ktx"])
    p_stn.add_argument("query", nargs="?", default="")
    p_stn.set_defaults(func=cmd_stations)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("종료")
