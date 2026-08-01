# -*- coding: utf-8 -*-
"""KOBUS(고속버스) 잔여석 조회.

- 노선/터미널 목록: POST /oprninf/alcninqr/oprnAlcnInqr.ajax
- 잔여석 조회:      POST /oprninf/alcninqr/readAlcnSrch.ajax
"""

import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

from . import LEGACY_TLS_CTX, ProviderError, TTLCache, hhmm_to_min, http_json, trip

NAME = "고속버스"
BOOK_URL = "https://www.kobus.co.kr"

PAGE = "https://www.kobus.co.kr/oprninf/alcninqr/oprnAlcnPage.do"
AJAX_SEARCH = "https://www.kobus.co.kr/oprninf/alcninqr/readAlcnSrch.ajax"
AJAX_ROUTES = "https://www.kobus.co.kr/oprninf/alcninqr/oprnAlcnInqr.ajax"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_opener = None
_routes = TTLCache(12 * 3600)


def _get_opener(fresh=False):
    """세션 쿠키를 물고 있는 opener. 조회가 막히면 fresh=True 로 새로 만든다."""
    global _opener
    if _opener is None or fresh:
        cj = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=LEGACY_TLS_CTX),
            urllib.request.HTTPCookieProcessor(cj),
        )
        _opener.addheaders = [("User-Agent", UA)]
        try:  # 세션 쿠키 확보용 워밍업
            _opener.open(PAGE, timeout=20).read()
        except Exception:
            pass
    return _opener


def _load_routes():
    """전체 노선 목록. [{deprCd, deprNm, arvlCd, arvlNm, ...}, ...]"""
    data = http_json(AJAX_ROUTES, data=b"", opener=_get_opener(), headers={
        "X-Requested-With": "XMLHttpRequest",
        "Referer": PAGE,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    rows = data.get("rotInfList") or []
    if not rows:
        raise ProviderError("KOBUS 노선 목록을 받지 못했습니다.")
    return rows


def routes():
    return _routes.get(_load_routes)


def terminals():
    """{코드: 이름} 전체 터미널."""
    out = {}
    for r in routes():
        out[r["deprCd"]] = r["deprNm"]
        out[r["arvlCd"]] = r["arvlNm"]
    return out


def search_stations(query=""):
    """이름/코드로 터미널 찾기. [(코드, 이름), ...]"""
    items = sorted(terminals().items(), key=lambda kv: kv[1])
    if not query:
        return items
    q = query.replace(" ", "")
    return [(c, n) for c, n in items if q in n.replace(" ", "") or q == c]


def _resolve_terminal(text, kind):
    """'대전청사' 또는 '305' -> ('305', '대전청사(샘머리)')."""
    text = str(text).strip()
    table = terminals()
    if text in table:                      # 코드로 준 경우
        return text, table[text]
    exact = [(c, n) for c, n in table.items() if n == text]
    if len(exact) == 1:
        return exact[0]
    hits = search_stations(text)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ProviderError(f"{kind} 터미널을 찾을 수 없습니다: {text!r}")
    listed = ", ".join(f"{n}({c})" for c, n in hits[:12])
    raise ProviderError(
        f"{kind} 터미널 {text!r} 이(가) 여러 개와 맞습니다. 정확히 골라주세요: {listed}")


def resolve(w):
    """감시 설정 검증/정규화. 잘못된 터미널은 여기서 걸린다."""
    dep_cd, dep_nm = _resolve_terminal(w["dep"], "출발")
    arrivals = w["arr"] if isinstance(w["arr"], list) else [w["arr"]]
    resolved = [_resolve_terminal(a, "도착") for a in arrivals]

    known = {(r["deprCd"], r["arvlCd"]) for r in routes()}
    for arr_cd, arr_nm in resolved:
        if (dep_cd, arr_cd) not in known:
            raise ProviderError(f"KOBUS 에 {dep_nm} → {arr_nm} 직통 노선이 없습니다.")

    w["_dep"] = (dep_cd, dep_nm)
    w["_arrs"] = resolved
    w["route_desc"] = f"{dep_nm} → {' / '.join(n for _, n in resolved)}"
    return w


def _query(dep, arr, date, bus_class, premium_discount):
    params = {
        "deprCd": dep[0], "deprNm": dep[1],
        "arvlCd": arr[0], "arvlNm": arr[1],
        "crchDeprArvlYn": "N", "deprDtm": date,
        "busClsCd": bus_class, "prmmDcYn": "Y" if premium_discount else "N",
    }
    body = urllib.parse.urlencode(params).encode()
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": PAGE,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    last = None
    for attempt in (1, 2):
        try:
            return http_json(AJAX_SEARCH, data=body, headers=headers,
                             opener=_get_opener(fresh=(attempt == 2)))
        except Exception as e:
            last = e
            if attempt == 1:
                time.sleep(2)
    raise last


def fetch(w, log):
    """시간대 안의 차편 목록. 조회 실패 시 None."""
    win_s, win_e = w["_win"]
    out = []
    for arr in w["_arrs"]:
        try:
            d = _query(w["_dep"], arr, w["date"],
                       w.get("bus_class", "0"), w.get("premium_discount", False))
        except Exception as e:
            log(f"KOBUS 조회 실패({w['_dep'][1]}→{arr[1]}): {e}")
            return None

        if d.get("rotVldChc") == "N":      # 해당 날짜 배차 없음
            continue

        for r in d.get("alcnAllList") or []:
            t = (r.get("DEPR_TIME_DVS") or "").replace(" ", "")
            if len(t) < 5:
                continue
            if not (win_s <= hhmm_to_min(t) <= win_e):
                continue
            remain = int(r.get("RMN_SATS_NUM", 0) or 0)
            total = int(r.get("TOT_SATS_NUM", 0) or 0)
            grade = r.get("BUS_CLS_NM", "")
            company = r.get("CACM_MN", "")
            out.append(trip(
                key=f"{arr[0]}|{t}|{grade}|{company}",
                time_str=t,
                label=" · ".join(x for x in (grade, company) if x),
                route=f"{w['_dep'][1]} → {arr[1]}",
                available=remain > 0,
                status=f"잔여 {remain}/{total}석",
                fare=int(r.get("ADLT_FEE", 0) or 0),
                remain=remain,
                total=total,
            ))
    out.sort(key=lambda x: (x["time"], x["route"]))
    return out
