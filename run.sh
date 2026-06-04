#!/usr/bin/env bash
# tmux 세션에서 백그라운드 실행. 실시간 보기: tmux attach -t buscheck (떼기: Ctrl-b d)
cd "$(dirname "$0")"
SESSION=buscheck
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "이미 실행 중 (tmux '$SESSION'). 보기: tmux attach -t $SESSION"; exit 0
fi
tmux new-session -d -s "$SESSION" "python3 buscheck.py 2>&1 | tee -a buscheck.log"
echo "tmux '$SESSION' 시작됨. 보기: tmux attach -t $SESSION  중지: ./stop.sh"
