# buscheck — 고속버스 잔여석 텔레그램 알림봇

KOBUS(고속버스) 실시간 잔여석을 폴링해서, 원하는 시간대 차편에 자리가 생기면
텔레그램으로 알려준다. 표준 라이브러리만 사용한다(추가 설치 불필요).

## 현재 설정
- 노선: **서울경부(010) → 대전청사(305)**
- 날짜: **2026-06-05**
- 시간대: **16:00 ~ 18:00** 출발
- 조건: 잔여석 > 0 인 차편이 새로 생기면 알림
- 조회 주기: **30초**
- 텔레그램 봇: [@Buscheck_forgf_bot](https://t.me/Buscheck_forgf_bot)

설정은 [buscheck.py](buscheck.py) 상단 상수에서 바꾼다.

## 동작 방식
- KOBUS 잔여석 조회 API `POST /oprninf/alcninqr/readAlcnSrch.ajax` 를 호출한다.
- 응답의 `alcnAllList[]` 에서 출발시각·등급·요금·잔여석(`RMN_SATS_NUM`)을 읽는다.
- 16:00~18:00 출발 + 잔여석>0 차편 집합을 매 주기 비교해, **새로 자리가 생긴** 차편만 알린다
  (매진→여석 전환 시 1회 알림. 도배 방지).
- 봇에게 메시지를 보낸 사용자의 `chat_id` 를 자동 등록한다.

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
- `buscheck.py` — 봇 본체
- `token.txt` — 텔레그램 토큰 (gitignore, 직접 생성)
- `token.txt.example` — 토큰 파일 예시
- `state.json` — chat_id / 텔레그램 offset / 직전 잔여석 상태 (자동 생성, gitignore)
- `run.sh` / `stop.sh` — tmux 백그라운드 실행/중지
- `buscheck.log` — 실행 로그 (gitignore)
