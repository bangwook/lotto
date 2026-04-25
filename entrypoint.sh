#!/bin/bash
# Xvfb 가상 디스플레이 시작
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 2
export DISPLAY=:99

# 실행
exec python src/purchase_all.py
