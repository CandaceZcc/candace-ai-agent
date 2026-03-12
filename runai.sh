#!/usr/bin/env bash
set -u
set -o pipefail

ROOT="$HOME/candace-ai-agent"
VENV="$ROOT/.venv"
BRIDGE_DIR="$ROOT/qq-ai-bridge"
AGENT_DIR="$ROOT/pc-agent"
RUNTIME_DIR="$ROOT/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"

BRIDGE_LOG="$LOG_DIR/bridge.log"
AGENT_LOG="$LOG_DIR/agent.log"
PC_AGENT_PORT="${PC_AGENT_PORT:-5050}"

mkdir -p "$LOG_DIR"

pick_terminal() {
  if command -v gnome-terminal >/dev/null 2>&1; then
    echo "gnome-terminal"
    return 0
  fi
  if command -v x-terminal-emulator >/dev/null 2>&1; then
    echo "x-terminal-emulator"
    return 0
  fi
  if command -v xterm >/dev/null 2>&1; then
    echo "xterm"
    return 0
  fi
  return 1
}

open_terminal_window() {
  local title="$1"
  local cmd="$2"

  local terminal
  terminal="$(pick_terminal)" || {
    echo "未找到可用图形终端（gnome-terminal / x-terminal-emulator / xterm）"
    return 1
  }

  case "$terminal" in
    gnome-terminal)
      gnome-terminal --title="$title" -- bash -lc "$cmd; echo; echo '按回车关闭窗口'; read" >/dev/null 2>&1 &
      ;;
    x-terminal-emulator)
      x-terminal-emulator -T "$title" -e bash -lc "$cmd; echo; echo '按回车关闭窗口'; read" >/dev/null 2>&1 &
      ;;
    xterm)
      xterm -T "$title" -hold -e bash -lc "$cmd" >/dev/null 2>&1 &
      ;;
  esac
}

ensure_env() {
  if [[ ! -f "$VENV/bin/activate" ]]; then
    echo "未找到虚拟环境：$VENV"
    echo "请先执行："
    echo "  cd $ROOT"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install flask numpy requests python-dotenv pillow pyautogui opencv-python pytesseract mss"
    exit 1
  fi
}

run_dev_mode() {
  ensure_env

  echo "开发模式：前台启动 bridge + agent（实时日志）"
  echo "按 Ctrl+C 可停止两个进程。"

  (
    cd "$ROOT" || exit 1
    source "$VENV/bin/activate"
    cd "$BRIDGE_DIR" || exit 1
    export PYTHONUNBUFFERED=1
    python3 -u bridge.py
  ) 2>&1 | sed -u 's/^/[bridge] /' &
  BRIDGE_PID=$!

  (
    cd "$ROOT" || exit 1
    source "$VENV/bin/activate"
    cd "$AGENT_DIR" || exit 1
    export PYTHONUNBUFFERED=1
    exec env PC_AGENT_PORT="$PC_AGENT_PORT" python3 -u agent.py
  ) 2>&1 | sed -u 's/^/[agent] /' &
  AGENT_PID=$!

  cleanup() {
    kill "$BRIDGE_PID" "$AGENT_PID" 2>/dev/null || true
    sleep 0.3
    kill -9 "$BRIDGE_PID" "$AGENT_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" "$AGENT_PID" 2>/dev/null || true
  }

  trap 'echo; echo "[runai] 收到中断，停止中..."; cleanup; exit 130' INT TERM
  trap 'cleanup' EXIT

  while true; do
    if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
      wait "$BRIDGE_PID" 2>/dev/null
      STATUS=$?
      echo "[runai] 检测到 bridge 退出（status=$STATUS），停止 agent..."
      cleanup
      trap - INT TERM EXIT
      exit "$STATUS"
    fi

    if ! kill -0 "$AGENT_PID" 2>/dev/null; then
      wait "$AGENT_PID" 2>/dev/null
      STATUS=$?
      echo "[runai] 检测到 agent 退出（status=$STATUS），停止 bridge..."
      cleanup
      trap - INT TERM EXIT
      exit "$STATUS"
    fi

    sleep 0.2
  done
}

run_window_mode() {
  ensure_env

  local bridge_cmd="
    cd '$ROOT' || exit 1
    source '$VENV/bin/activate'
    cd '$BRIDGE_DIR' || exit 1
    export PYTHONUNBUFFERED=1
    python3 -u bridge.py 2>&1 | tee -a '$BRIDGE_LOG'
  "

  local agent_cmd="
    cd '$ROOT' || exit 1
    source '$VENV/bin/activate'
    cd '$AGENT_DIR' || exit 1
    export PYTHONUNBUFFERED=1
    env PC_AGENT_PORT='$PC_AGENT_PORT' python3 -u agent.py 2>&1 | tee -a '$AGENT_LOG'
  "

  echo "窗口模式：弹出 bridge 与 agent 两个独立终端..."
  open_terminal_window "runai-bridge" "$bridge_cmd" || exit 1
  open_terminal_window "runai-agent" "$agent_cmd" || exit 1
  echo "已打开两个终端窗口。"
}

case "${1:-window}" in
  window)
    run_window_mode
    ;;
  dev)
    run_dev_mode
    ;;
  *)
    echo "用法: $0 [window|dev]"
    exit 1
    ;;
esac
