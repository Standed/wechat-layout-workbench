#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8765}"
LOG_FILE="${ROOT}/output/wechat-layout-workbench.log"
PID_FILE="${ROOT}/output/wechat-layout-workbench.pid"
SESSION_NAME="wechat-layout-workbench"

mkdir -p "${ROOT}/output"

if command -v lsof >/dev/null 2>&1; then
  old_pids="$(lsof -ti tcp:"${PORT}" || true)"
  if [[ -n "${old_pids}" ]]; then
    kill ${old_pids} 2>/dev/null || true
    sleep 0.3
  fi
fi

cd "${ROOT}"

if command -v screen >/dev/null 2>&1; then
  screen -S "${SESSION_NAME}" -X quit >/dev/null 2>&1 || true
  screen -dmS "${SESSION_NAME}" bash -lc "cd '${ROOT}' && exec python3 web/server.py '${PORT}' >'${LOG_FILE}' 2>&1"
  sleep 0.5
  pid="$(lsof -ti tcp:"${PORT}" | head -1 || true)"
else
  nohup python3 web/server.py "${PORT}" >"${LOG_FILE}" 2>&1 &
  pid="$!"
fi
echo "${pid}" >"${PID_FILE}"

sleep 1

pid="$(lsof -ti tcp:"${PORT}" | head -1 || true)"
echo "${pid}" >"${PID_FILE}"

if curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null; then
  echo "已启动：http://127.0.0.1:${PORT}/"
  echo "PID: ${pid}"
  if command -v screen >/dev/null 2>&1; then
    echo "screen 会话：${SESSION_NAME}"
  fi
  echo "日志：${LOG_FILE}"
else
  echo "进程已启动但页面暂时不可访问，日志如下："
  tail -60 "${LOG_FILE}" || true
  exit 1
fi
