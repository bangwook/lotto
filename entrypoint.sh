#!/bin/bash
# 이전 Xvfb 잠금 파일 정리
rm -f /tmp/.X99-lock

# Xvfb 가상 디스플레이 시작
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
sleep 2

# Xvfb 정상 시작 확인
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "⚠️ Xvfb 시작 실패, headless 모드로 전환"
    export FORCE_HEADLESS=1
else
    export DISPLAY=:99
    echo "✅ Xvfb started on display :99"
fi

# 실행
exec python src/purchase_all.py
