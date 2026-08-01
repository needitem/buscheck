# buscheck — 고속버스/기차 잔여석 텔레그램 알림봇

KOBUS(고속버스)와 코레일(KTX·ITX·무궁화) 잔여석을 폴링해서, 원하는 시간대 차편에
자리가 생기면 텔레그램으로 알려준다. 표준 라이브러리만 사용한다(추가 설치 불필요).

여러 구간을 동시에 감시할 수 있고, 도착지를 여러 곳(예: 청량리 **또는** 서울) 지정할
수 있다. 출발 시간대가 지나면 해당 감시는 자동으로 끝난다.

## 설정

감시 대상은 [config.json](config.json) 에 적는다. ([config.example.json](config.example.json) 참고)

```json
{
  "poll_sec": 30,
  "watches": [
    {
      "name": "안동 16:43 KTX-이음 714",
      "provider": "korail",
      "dep": "안동",
      "arr": ["청량리", "서울"],
      "date": "20260802",
      "start": "16:30",
      "end": "16:50"
    }
  ]
}
```

| 항목 | 설명 |
| --- | --- |
| `provider` | `korail`(기차) 또는 `kobus`(고속버스) |
| `dep` / `arr` | 역·터미널 이름. `arr` 는 배열로 여러 곳 지정 가능 |
| `date` | `YYYYMMDD` (`2026-08-02` 처럼 하이픈을 넣어도 된다) |
| `start` / `end` | 출발 시각 범위 (이 사이에 출발하는 차편만 본다) |
| `poll_sec` | 조회 주기(초). 생략하면 최상위 `poll_sec` |
| `enabled` | `false` 면 건너뛴다 |
| `name` | 로그·알림에 쓸 이름 (생략 가능) |

기차 전용 항목

| 항목 | 설명 |
| --- | --- |
| `train_type` | `all`(기본), `ktx`, `itx-saemaeul`, `mugunghwa`, `itx-cheongchun`, `tonggeun`, `airport` |
| `seat_class` | `any`(기본) / `general`(일반실만) / `special`(특실만) |

고속버스 전용 항목

| 항목 | 설명 |
| --- | --- |
| `bus_class` | `0`(전체, 기본) |
| `premium_discount` | 시외우등 할인 여부 (기본 `false`) |

### 역·터미널 이름 찾기

이름이 정확해야 조회된다. 헷갈리면 검색해서 확인한다.

```bash
python3 buscheck.py stations korail 청량   # -> 청량리
python3 buscheck.py stations kobus 대전     # -> 대전도룡(307), 대전복합(300), 대전청사(샘머리)(305)
```

`청량리역` 처럼 뒤에 "역"을 붙이거나 `대전청사` 처럼 줄여 써도 알아서 맞춰준다.
못 찾거나 여러 개와 겹치면 실행 시점에 후보를 알려주고 멈춘다.

## 동작 방식

- 매 주기마다 시간대 안의 차편을 조회해서 **잔여석이 있는 차편 집합**을 만든다.
- 직전 회차와 비교해 **새로 자리가 생긴** 차편만 알린다(매진→여석 전환 시 1회. 도배 방지).
- 봇에게 메시지를 보낸 사용자의 `chat_id` 를 자동 등록한다.

조회 경로

- 고속버스: `POST /oprninf/alcninqr/readAlcnSrch.ajax` 의 `RMN_SATS_NUM`(잔여석)
- 기차: 코레일 앱 스케줄 API `com.korail.mobile.seatMovie.ScheduleView` 의
  `h_gen_rsv_cd`(일반실) / `h_spe_rsv_cd`(특실). 코드 `11` 이면 예매 가능,
  `13` 이면 매진. 로그인은 필요 없다.
  기차는 한 번에 10대씩 내려주므로 시간대가 넓으면 페이지를 이어서 받는다.

## 텔레그램 토큰 설정 (필수)
토큰은 코드에 넣지 않는다. 둘 중 하나로 준다.
```bash
# 방법 A) 환경변수
export TELEGRAM_TOKEN="123456:ABC..."

# 방법 B) 파일 (gitignore 처리됨)
cp token.txt.example token.txt && echo "123456:ABC..." > token.txt
```
[@BotFather](https://t.me/BotFather) 에서 봇을 만들면 토큰을 받을 수 있다.

## 실행
```bash
# 설정이 맞는지 한 번만 조회 (텔레그램 전송 안 함)
python3 buscheck.py --once

# 포그라운드
python3 buscheck.py

# 백그라운드(tmux 세션, 세션 종료 후에도 유지)
./run.sh                    # 실시간 보기: tmux attach -t buscheck (떼기: Ctrl-b d)
./stop.sh                   # 중지
```

## 텔레그램 연결
봇([@Buscheck_forgf_bot](https://t.me/Buscheck_forgf_bot))에게 아무 메시지나 한 번 보내면
자동으로 등록되고 "연결됨" 메시지가 온다. 여러 명이 보내면 모두에게 알림이 간다.

## 파일
- `buscheck.py` — 메인 루프 / 설정 / 텔레그램
- `providers/kobus.py` — KOBUS 조회
- `providers/korail.py` — 코레일 조회
- `providers/dynapath.py` — 코레일 API 의 anti-bot 헤더 생성
  (MIT 라이선스인 [@nomadamas/k-skill](https://github.com/NomaDamas/k-skill) 의
  `ktx-booking` 헬퍼에서 가져옴)
- `config.json` — 감시 대상 / `config.example.json` — 설정 예시
- `token.txt` — 텔레그램 토큰 (gitignore, 직접 생성)
- `state.json` — chat_id / 텔레그램 offset / 직전 잔여석 상태 (자동 생성, gitignore)
- `run.sh` / `stop.sh` — tmux 백그라운드 실행/중지
- `buscheck.log` — 실행 로그 (gitignore)

## 참고
- 조회 주기를 너무 짧게 잡지 않는다. 기본 30초면 충분하다.
- 이 봇은 **조회·알림만** 한다. 예매는 알림을 받고 직접 한다.
