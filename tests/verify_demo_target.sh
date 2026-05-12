#!/usr/bin/env bash
# =============================================================================
# verify_demo_target.sh
# Acceptance test suite for the demo-vulnerable-target Docker service.
#
# Spec reference: sdd/vulnerable-target-container/spec
# Requirements:
#   - Demo profile-gated availability (starts only with --profile demo)
#   - Internal-only network isolation (no host ports by default)
#   - Predictable emulated scan surface (ports 22/80/21/3306 + fake banners)
#   - Safety and non-production guarantee
#
# Strict TDD: this script was written BEFORE the Docker infrastructure exists.
# It will FAIL (RED) until Phase 2 implementation is complete.
# =============================================================================
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# --- Counters ---
PASS=0
FAIL=0

log_pass() {
  echo -e "  ${GREEN}[PASS]${NC} $1"
  PASS=$((PASS + 1))
}
log_fail() {
  echo -e "  ${RED}[FAIL]${NC} $1"
  FAIL=$((FAIL + 1))
}
log_info() { echo -e "  ${YELLOW}[INFO]${NC} $1"; }

# Derived from the directory name — compose auto-detects this
PROJECT_NAME="soc360-pymes"
COMPOSE_FILE="docker-compose.yml"
PROFILE="demo"
SERVICE="vulnerable-target"
NETWORK="${PROJECT_NAME}_demo_network"

# ---------------------------------------------------------------------------
# Cleanup: ensure demo stack is fully torn down after test run
# ---------------------------------------------------------------------------
cleanup() {
  echo ""
  log_info "Tearing down demo stack..."
  docker compose --profile "$PROFILE" down -v --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Pre-flight: ensure we are in the project root (where docker-compose.yml lives)
# ---------------------------------------------------------------------------
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo -e "${RED}[ABORT]${NC} $COMPOSE_FILE not found. Run this script from the project root."
  exit 1
fi

echo ""
echo -e "${BOLD}=== verify_demo_target.sh ===${NC}"
echo -e "${BOLD}Spec: sdd/vulnerable-target-container/spec${NC}"
echo ""

# ===========================================================================
# TEST 1 — Container is absent WITHOUT the demo profile
# Requirement: Demo profile-gated availability
# Scenario:   Demo target stays absent by default
# ===========================================================================
echo -e "${BOLD}--- Test 1: Profile-gated absence (no --profile demo) ---${NC}"

# Start the platform WITHOUT the demo profile (default services only)
docker compose up -d 2>/dev/null || true
sleep 2

# Verify the vulnerable-target container does NOT exist
if docker compose ps --format 'table {{.Name}}' 2>/dev/null | grep -q "${SERVICE}"; then
  log_fail "vulnerable-target container found when it should NOT be running (demo profile NOT enabled)"
else
  log_pass "vulnerable-target is NOT running without --profile demo"
fi

# Tear down default services
docker compose down 2>/dev/null || true

# ===========================================================================
# TEST 2 — Container starts WITH the demo profile
# Requirement: Demo profile-gated availability
# Scenario:   Demo target starts when explicitly requested
# ===========================================================================
echo ""
echo -e "${BOLD}--- Test 2: Profile-gated availability (--profile demo) ---${NC}"

# Start WITH the demo profile
docker compose --profile "$PROFILE" up -d 2>/dev/null
# Give the container a moment to initialize
sleep 3

# Verify the container exists and is running
CONTAINER_ID=$(docker compose ps -q "$SERVICE" 2>/dev/null || echo "")
if [[ -z "$CONTAINER_ID" ]]; then
  log_fail "vulnerable-target container did NOT start with --profile demo"
else
  STATUS=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_ID" 2>/dev/null || echo "unknown")
  if [[ "$STATUS" == "running" ]]; then
    log_pass "vulnerable-target container is running with --profile demo (status: $STATUS)"
  else
    log_fail "vulnerable-target container exists but status is '$STATUS' (expected 'running')"
  fi
fi

# ===========================================================================
# TEST 3 — Expected ports respond within the demo network
# Requirement: Predictable emulated scan surface
# Scenario:   Scanner sees expected ports and banners
# ===========================================================================
echo ""
echo -e "${BOLD}--- Test 3: Emulated ports respond on demo network ---${NC}"

EXPECTED_PORTS=(22 80 21 3306)
PORT_NAMES=("SSH (22)" "HTTP (80)" "FTP (21)" "MySQL (3306)")

# Use a temporary busybox container attached to the demo network to probe each port
for i in "${!EXPECTED_PORTS[@]}"; do
  PORT="${EXPECTED_PORTS[$i]}"
  NAME="${PORT_NAMES[$i]}"

  # Use nc (netcat) from a temporary container on the same network
  RESULT=$(docker run --rm --network "$NETWORK" alpine:3.20 \
    sh -c "apk add --quiet netcat-openbsd 2>/dev/null; echo 'QUIT' | timeout 5 nc -w 3 ${SERVICE} ${PORT} 2>&1" || echo "TIMEOUT_OR_ERROR")

  if echo "$RESULT" | grep -q "TIMEOUT_OR_ERROR"; then
    log_fail "$NAME port did NOT respond within timeout"
  elif [[ -z "$(echo "$RESULT" | tr -d '[:space:]')" ]]; then
    log_fail "$NAME port connected but returned EMPTY response (expected banner text)"
  else
    BANNER_PREVIEW=$(echo "$RESULT" | head -1 | cut -c1-60)
    log_pass "$NAME responded: '${BANNER_PREVIEW}...'"
  fi
done

# ===========================================================================
# TEST 4 — No host ports exposed by default
# Requirement: Internal-only network isolation
# Scenario:   Host cannot reach the target by default
# ===========================================================================
echo ""
echo -e "${BOLD}--- Test 4: No host port exposure ---${NC}"

for PORT in 22 80 21 3306; do
  HOST_MAPPING=$(docker compose port "$SERVICE" "$PORT" 2>&1 || true)
  # Strip compose warning lines (e.g., missing env var warnings)
  CLEAN_MAPPING=$(echo "$HOST_MAPPING" | grep -v "level=warning" | grep -v "^$" | tail -1)

  if [[ -z "$CLEAN_MAPPING" ]]; then
    log_pass "Port $PORT has NO host mapping"
  elif [[ "$CLEAN_MAPPING" == ":0" ]]; then
    # Port is EXPOSEd in Dockerfile but NOT published to host.
    # This is the expected demo posture — internal network only.
    log_pass "Port $PORT is EXPOSEd but NOT published to host (internal network only)"
  elif echo "$CLEAN_MAPPING" | grep -qi "error\|no port\|not published\|no container"; then
    log_pass "Port $PORT is NOT published to host"
  else
    # A real host mapping was returned (e.g., "0.0.0.0:8080") — unwelcome
    log_fail "Port $PORT IS published to host: $CLEAN_MAPPING"
  fi
done

# ===========================================================================
# TEST 5 — Container is labeled as demo/simulated (safety check)
# Requirement: Safety and non-production guarantee
# Scenario:   Demo target is identified as simulated
# ===========================================================================
echo ""
echo -e "${BOLD}--- Test 5: Demo/simulation labeling ---${NC}"

if [[ -n "$CONTAINER_ID" ]]; then
  LABELS=$(docker inspect -f '{{range $k,$v := .Config.Labels}}{{$k}}={{$v}} {{end}}' "$CONTAINER_ID" 2>/dev/null || echo "")
  if echo "$LABELS" | grep -qi "demo\|simulated"; then
    log_pass "Container has demo/simulated label: $(echo "$LABELS" | grep -oi 'demo[^ ]*\|simulated[^ ]*')"
  else
    log_fail "Container lacks demo/simulated label — safety labeling missing"
  fi
else
  log_fail "Cannot verify labels — container not running"
fi

# ===========================================================================
# SUMMARY
# ===========================================================================
echo ""
echo -e "${BOLD}========================================${NC}"
echo -e "${BOLD}  RESULTS${NC}"
echo -e "${BOLD}========================================${NC}"
echo -e "  ${GREEN}Passed:${NC} $PASS"
echo -e "  ${RED}Failed:${NC} $FAIL"
echo ""

if [[ "$FAIL" -gt 0 ]]; then
  echo -e "${RED}[VERDICT] Some tests FAILED.${NC}"
  exit 1
else
  echo -e "${GREEN}[VERDICT] All tests PASSED.${NC}"
  exit 0
fi
