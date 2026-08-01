# -*- coding: utf-8 -*-
"""잔여석 조회 프로바이더 공통부.

각 프로바이더는 아래 두 가지를 제공한다.

    resolve(watch)  -> 감시 설정을 검증/정규화한다. 잘못된 역·터미널 이름은
                       여기서 CommonError 로 걸러 루프가 돌기 전에 알려준다.
    fetch(watch)    -> Trip 리스트를 돌려준다. 조회 실패는 None(= 이번 회차 건너뜀).

Trip 은 프로바이더가 달라도 같은 모양이라, 메인 루프는 버스인지 기차인지
몰라도 된다.
"""

import ssl
import time
import urllib.error
import urllib.request


class ProviderError(Exception):
    """설정 오류처럼 루프를 돌기 전에 사용자에게 알려야 하는 문제."""


def hhmm_to_min(s):
    """'16:43' 또는 '1643' -> 1003(분)."""
    s = s.replace(" ", "").replace(":", "")
    if len(s) < 4 or not s[:4].isdigit():
        raise ProviderError(f"시각 형식이 잘못됐습니다: {s!r} (예: '16:43')")
    return int(s[:2]) * 60 + int(s[2:4])


def min_to_hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def trip(key, time_str, label, *, available, status,
         arr_time="", route="", fare=0, remain=None, total=None, note=""):
    """프로바이더 공통 차편 표현."""
    return {
        "key": key,              # 같은 차편을 회차 간 이어보기 위한 고유 키
        "time": time_str,        # 출발 시각 'HH:MM'
        "arr_time": arr_time,    # 도착 시각 'HH:MM' (없으면 빈 문자열)
        "label": label,          # 'KTX-이음 714' / '우등'
        "route": route,          # '안동 → 청량리'
        "available": available,  # 지금 잡을 수 있는가
        "status": status,        # '좌석많음' / '매진' 처럼 사람이 읽는 상태
        "fare": fare,
        "remain": remain,        # 잔여 좌석 수 (모르면 None)
        "total": total,
        "note": note,            # '예약대기 31명' 같은 참고 정보
    }


def http_json(url, *, data=None, headers=None, context=None, opener=None, timeout=25):
    """POST/GET 후 JSON 을 돌려준다. 실패는 예외를 그대로 올린다."""
    import json

    req = urllib.request.Request(url, data=data, headers=headers or {})
    if opener is not None:
        resp = opener.open(req, timeout=timeout)
    else:
        resp = urllib.request.urlopen(req, timeout=timeout, context=context)
    with resp as r:
        return json.loads(r.read().decode("utf-8"))


class TTLCache:
    """터미널/역 목록처럼 하루에 한 번만 받아오면 되는 값용."""

    def __init__(self, ttl_sec):
        self.ttl = ttl_sec
        self._value = None
        self._at = 0.0

    def get(self, loader):
        now = time.time()
        if self._value is None or now - self._at > self.ttl:
            self._value = loader()
            self._at = now
        return self._value


def get(name):
    """프로바이더 이름 -> 모듈."""
    from . import kobus, korail

    table = {
        "kobus": kobus,
        "korail": korail,
        "ktx": korail,   # 별칭
        "bus": kobus,    # 별칭
    }
    try:
        return table[name]
    except KeyError:
        raise ProviderError(
            f"알 수 없는 provider: {name!r} (쓸 수 있는 값: kobus, korail)")


# KOBUS 서버는 구형 TLS cipher 를 써서 파이썬 기본 컨텍스트로는 핸드셰이크가 막힌다.
# SECLEVEL 을 1로 낮추되 인증서 검증은 그대로 유지한다.
LEGACY_TLS_CTX = ssl.create_default_context()
LEGACY_TLS_CTX.set_ciphers("DEFAULT@SECLEVEL=1")
