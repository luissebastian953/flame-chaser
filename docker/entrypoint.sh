#!/usr/bin/env bash
# Start dawnmaker, wait for its one-line stdout handshake, hand the port and
# token to Vite through the environment (never argv, never a file), then run
# Vite in the foreground. Killing the container takes both down.
set -euo pipefail

PORT="${DAWNMAKER_PORT:-8765}"
mkdir -p "$REAVER_HOME"

# Anything other than the dev stack: `docker compose run dev coreflame status`
if [ "$#" -gt 0 ]; then exec "$@"; fi

cd /app/reaver
# A restarted container keeps /tmp: without this the loop below can read the
# PREVIOUS run's handshake before tee truncates the file, and Vite starts with
# a dead token -- every request 401s and the UI shows "daemon unreachable".
rm -f /tmp/dawnmaker.out
# --host 0.0.0.0 is only accepted together with --dev; the host publishes the
# port on 127.0.0.1 only (compose), so it is still loopback from outside.
python -m dawnmaker --host 0.0.0.0 --port "$PORT" --no-heartbeat --dev \
  > >(tee /tmp/dawnmaker.out) 2>&1 &
DAEMON=$!
trap 'kill $DAEMON 2>/dev/null; wait $DAEMON 2>/dev/null' EXIT INT TERM

for _ in $(seq 1 100); do
  if LINE=$(grep -m1 '^DAWNMAKER_READY ' /tmp/dawnmaker.out 2>/dev/null); then break; fi
  if ! kill -0 $DAEMON 2>/dev/null; then echo "dawnmaker exited before handshake" >&2; exit 1; fi
  sleep 0.1
done
[ -n "${LINE:-}" ] || { echo "no DAWNMAKER_READY within 10s" >&2; exit 1; }

# The browser -- on the host -- talks to the daemon directly at the published port.
export VITE_DAEMON_URL="http://127.0.0.1:${PORT}"
export VITE_DAEMON_TOKEN
VITE_DAEMON_TOKEN=$(printf '%s' "${LINE#DAWNMAKER_READY }" | python -c 'import json,sys;print(json.load(sys.stdin)["token"])')

cd /app
# node_modules are container-only volumes; sync them to pnpm-lock.yaml every
# start so deps added on the host appear here. A no-op when nothing changed.
# stdin is /dev/null on purpose: compose gives this a tty, so any pnpm prompt
# would sit here forever and Vite would never start. Fail loudly instead.
pnpm install --frozen-lockfile --prefer-offline < /dev/null
echo "curio: webview http://localhost:5173  ·  daemon ${VITE_DAEMON_URL}  ·  data ${REAVER_HOME}" >&2
cd /app/deliverer
exec pnpm exec vite --host 0.0.0.0 --port 5173 --strictPort
