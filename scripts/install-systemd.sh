#!/bin/bash
# Lotto Auto Purchase - Systemd Timer Installation Script
#
# 스케줄:
#   - 구매: 매주 금요일 22:00 KST (lotto.timer)
#   - 당첨 확인: 매주 토요일 22:00 KST (lotto-check.timer)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "⏰ Lotto Auto Purchase - Systemd Timer Installation"
echo "====================================================="
echo ""
echo "📂 Detected paths:"
echo "   Project directory: $PROJECT_DIR"
echo "   Systemd user dir:  $SYSTEMD_USER_DIR"
echo ""

# Setup systemd
echo "⚙️  Setting up systemd timers..."
mkdir -p "$SYSTEMD_USER_DIR"

# ===== 구매 서비스/타이머 설치 =====
echo ""
echo "📋 [1/4] Creating lotto.service (구매)..."
sed "s|{{PROJECT_ROOT}}|$PROJECT_DIR|g" \
    "$SCRIPT_DIR/systemd/lotto.service" > "$SYSTEMD_USER_DIR/lotto.service"

echo "📋 [2/4] Copying lotto.timer (금요일 22:00)..."
cp "$SCRIPT_DIR/systemd/lotto.timer" "$SYSTEMD_USER_DIR/"

# ===== 당첨 확인 서비스/타이머 설치 =====
echo "📋 [3/4] Creating lotto-check.service (당첨 확인)..."
sed "s|{{PROJECT_ROOT}}|$PROJECT_DIR|g" \
    "$SCRIPT_DIR/systemd/lotto-check.service" > "$SYSTEMD_USER_DIR/lotto-check.service"

echo "📋 [4/4] Copying lotto-check.timer (토요일 22:00)..."
cp "$SCRIPT_DIR/systemd/lotto-check.timer" "$SYSTEMD_USER_DIR/"

echo ""
echo "✅ Systemd files installed:"
echo "   • $SYSTEMD_USER_DIR/lotto.service"
echo "   • $SYSTEMD_USER_DIR/lotto.timer"
echo "   • $SYSTEMD_USER_DIR/lotto-check.service"
echo "   • $SYSTEMD_USER_DIR/lotto-check.timer"
echo ""

# Reload systemd daemon
echo "🔄 Reloading systemd daemon..."
systemctl --user daemon-reload

# Enable and start timers
echo "⏰ Enabling and starting timers..."
systemctl --user enable lotto.timer
systemctl --user start lotto.timer
systemctl --user enable lotto-check.timer
systemctl --user start lotto-check.timer

echo ""
echo "✅ Timer installation completed!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Show status
echo "📊 Timer Status:"
echo ""
echo "🎫 구매 타이머 (금요일 22:00):"
systemctl --user status lotto.timer --no-pager || true
echo ""
echo "🔍 당첨 확인 타이머 (토요일 22:00):"
systemctl --user status lotto-check.timer --no-pager || true

echo ""
echo "📅 Next scheduled runs:"
systemctl --user list-timers lotto.timer lotto-check.timer --no-pager

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 Useful commands:"
echo ""
echo "  📌 구매 (lotto):"
echo "    • Check timer:    systemctl --user status lotto.timer"
echo "    • View logs:      journalctl --user -u lotto.service"
echo "    • Run manually:   systemctl --user start lotto.service"
echo ""
echo "  📌 당첨 확인 (lotto-check):"
echo "    • Check timer:    systemctl --user status lotto-check.timer"
echo "    • View logs:      journalctl --user -u lotto-check.service"
echo "    • Run manually:   systemctl --user start lotto-check.service"
echo ""
echo "  📌 공통:"
echo "    • List timers:    systemctl --user list-timers"
echo "    • Reload:         systemctl --user daemon-reload"
echo ""
