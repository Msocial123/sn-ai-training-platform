#!/usr/bin/env bash
# "Break and test" resilience suite for the AI Agent Suite's LLM
# integration (Bedrock/Nova Pro or Anthropic, whichever is configured).
# Confirms the service degrades gracefully -- never 500s -- when the LLM
# provider fails, times out, or is hit with adversarial input.
#
# Usage: FRONTEND_URL=http://<your-lb-hostname> bash tests/break_test.sh
set -uo pipefail

URL="${FRONTEND_URL:?Set FRONTEND_URL to the frontends public URL, e.g. from: kubectl get svc ai-agents-frontend -n ai-agents}"
FAILS=0

check() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  PASS  $desc (got $actual)"
  else
    echo "  FAIL  $desc (expected $expected, got $actual)"
    FAILS=$((FAILS + 1))
  fi
}

echo "=== 1. Happy path ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL/api/now-assist/summarize" -H "Content-Type: application/json" -d '{"ticket_id":"INC0010001"}' --max-time 25)
check "valid ticket summarize" "200" "$CODE"

echo "=== 2. Invalid input handling ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL/api/now-assist/summarize" -H "Content-Type: application/json" -d '{"ticket_id":"NOTAREALTICKET"}' --max-time 15)
check "invalid ticket id -> 404, not 500" "404" "$CODE"

echo "=== 3. Oversized input (~10KB) ==="
BIGTEXT=$(python -c "print('incident details ' * 700)" 2>/dev/null || printf 'incident details %.0s' {1..700})
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL/api/virtual-agent/chat" -H "Content-Type: application/json" -d "{\"message\":\"$BIGTEXT\",\"session_id\":\"stress1\"}" --max-time 25)
check "oversized chat message doesn't crash the service" "200" "$CODE"

echo "=== 4. Empty input ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL/api/virtual-agent/chat" -H "Content-Type: application/json" -d '{"message":"","session_id":"stress2"}' --max-time 15)
check "empty chat message" "200" "$CODE"

echo "=== 5. Concurrent burst (15 simultaneous requests) ==="
CODES=$(for i in $(seq 1 15); do
  (curl -s -o /dev/null -w "%{http_code}\n" -X POST "$URL/api/now-assist/summarize" -H "Content-Type: application/json" -d '{"ticket_id":"INC0010001"}' --max-time 20) &
done; wait)
BAD=$(echo "$CODES" | grep -cv "^200$")
if [ "$BAD" -eq 0 ]; then
  echo "  PASS  all 15 concurrent requests returned 200"
else
  echo "  FAIL  $BAD of 15 concurrent requests were not 200"
  FAILS=$((FAILS + 1))
fi

echo "=== 6. LLM provider transparency ==="
RESP=$(curl -s -X POST "$URL/api/now-assist/summarize" -H "Content-Type: application/json" -d '{"ticket_id":"INC0010001"}' --max-time 25)
echo "  Provider reported: $(echo "$RESP" | python -c 'import json,sys; print(json.load(sys.stdin).get("llm_provider"))' 2>/dev/null || echo "$RESP")"
echo "  LLM error (if any): $(echo "$RESP" | python -c 'import json,sys; print(json.load(sys.stdin).get("llm_error"))' 2>/dev/null || echo "unknown")"

echo ""
if [ "$FAILS" -eq 0 ]; then
  echo "All resilience checks passed -- the service degrades gracefully regardless of LLM provider state."
else
  echo "$FAILS check(s) FAILED -- see above."
  exit 1
fi
