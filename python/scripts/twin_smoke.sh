#!/usr/bin/env bash
# Prove non-Python clients work against the twin: curl (signed REST) and
# mosquitto_sub (MQTT over TLS). Run from python/: bash scripts/twin_smoke.sh
set -euo pipefail
STATE=$(mktemp -d)
uv run ecoflow-twin serve --recording tests/recordings/synthetic/recording.json \
  --rest-port 18443 --mqtt-port 18883 --speed 20 --state-dir "$STATE" \
  > "$STATE/endpoints.json" &
TWIN=$!
trap 'kill "$TWIN" 2>/dev/null || true' EXIT
for _ in $(seq 100); do [ -s "$STATE/endpoints.json" ] && break; sleep 0.2; done
[ -s "$STATE/endpoints.json" ] || { echo "twin did not start"; exit 1; }

AK=twin-access-key
SK=twin-secret-key
NONCE=123456
TS=$(date +%s%3N)
SIGN=$(printf 'accessKey=%s&nonce=%s&timestamp=%s' "$AK" "$NONCE" "$TS" \
  | openssl dgst -sha256 -hmac "$SK" | awk '{print $NF}')
curl -sf --ssl-no-revoke --cacert "$STATE/ca.pem" \
  -H "accessKey: $AK" -H "nonce: $NONCE" -H "timestamp: $TS" -H "sign: $SIGN" \
  https://127.0.0.1:18443/iot-open/sign/device/list > "$STATE/list.json"
uv run python -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['code']=='0', d" "$STATE/list.json"
SN=$(uv run python -c "import json,sys; print(json.load(open(sys.argv[1]))['data'][0]['sn'])" "$STATE/list.json")

mosquitto_sub -h 127.0.0.1 -p 18883 --cafile "$STATE/ca.pem" \
  -u open-twin -P twin-mqtt-password -i twin-smoke \
  -t "/open/open-twin/$SN/quota" -C 2 -W 20
echo "twin smoke: curl + mosquitto_sub OK"
