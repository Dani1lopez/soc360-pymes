#!/bin/sh
# =============================================================================
# entrypoint.sh — Demo Vulnerable Target for SOC360 Pymes
# Binds ports 22 (SSH), 80 (HTTP), 21 (FTP), 3306(MySQL) and serves static fake banners.
#
# SAFETY: This is a SIMULATED target. No real services. No real vulnerabilities.
# =============================================================================
set -e

echo "================================================"
echo "  SOC360 Pymes — Demo Vulnerable Target"
echo "  [SIMULATED — for walkthroughs and demos only]"
echo "================================================"
echo ""
echo "Exposing demo ports: 22 (SSH), 80 (HTTP), 21 (FTP), 3306(MySQL)"
echo "Banners are static, fake, and clearly labeled."
echo ""

# Start banner listeners in background.
# Each listener loops: accepts one connection, sends the banner, then restarts.
#
# netcat-openbsd behavior:
#   nc -l -p PORT < /banners/FILE.banner
#   → listens on PORT, sends file content to the first connecting client, exits.
#   The while loop restarts the listener immediately after the connection ends.

while true; do
  nc -l -p 22 </banners/ssh.banner 2>/dev/null || true
done &

while true; do
  nc -l -p 80 </banners/http.banner 2>/dev/null || true
done &

while true; do
  nc -l -p 21 </banners/ftp.banner 2>/dev/null || true
done &

while true; do
  nc -l -p 3306 </banners/mysql.banner 2>/dev/null || true
done &

echo "[vulnerable-target] All listeners started on ports 22, 80, 21, 3306."
echo "[vulnerable-target] Container ready for demo scans."

# Keep the container alive — wait for any child process to exit
wait
