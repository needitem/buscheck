#!/usr/bin/env bash
SESSION=buscheck
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION" && echo "tmux '$SESSION' 중지됨"
else
  pkill -f "python3 buscheck.py" && echo "중지됨" || echo "실행 중인 프로세스 없음"
fi
