#!/usr/bin/env bash
set -u
set -o pipefail

ROOT="$HOME/candace-ai-agent"
BRIDGE_DIR="$ROOT/qq-ai-bridge"
AGENT_DIR="$ROOT/pc-agent"

RUNTIME_DIR="$ROOT/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"

BRIDGE_PID_FILE="$PID_DIR/bridge.pid"
AGENT_PID_FILE="$PID_DIR/agent.pid"

BRIDGE_LOG="$LOG_DIR/bridge.log"
AGENT_LOG="$LOG_DIR/agent.log"

BRIDGE_PORT="${BRIDGE_PORT:-8000}"
PC_AGENT_PORT="${PC_AGENT_PORT:-5050}"

mkdir -p "$LOG_DIR" "$PID_DIR"

is_running() {
  local pid="$1"
  [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local file="$1"
  [[ -f "$file" ]] && cat "$file"
}

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

agent_activate_cmd() {
  if [[ -f "$AGENT_DIR/venv/bin/activate" ]]; then
    echo "source venv/bin/activate"
    return 0
  fi
  if [[ -f "$AGENT_DIR/.venv/bin/activate" ]]; then
    echo "source .venv/bin/activate"
    return 0
  fi
  return 1
}

python_cmd_in_env() {
  local py=""
  py="$(command -v python 2>/dev/null || true)"
  if [[ -n "$py" ]]; then
    echo "$py"
    return 0
  fi
  py="$(command -v python3 2>/dev/null || true)"
  if [[ -n "$py" ]]; then
    echo "$py"
    return 0
  fi
  return 1
}

open_terminal_window() {
  local title="$1"
  local cmd="$2"

  local terminal
  terminal="$(pick_terminal)" || {
    echo "未找到可用终端（gnome-terminal/x-terminal-emulator/xterm）"
    return 1
  }

  case "$terminal" in
    gnome-terminal)
      gnome-terminal --title="$title" -- bash -lc "$cmd; exec bash" >/dev/null 2>&1 &
      ;;
    x-terminal-emulator)
      x-terminal-emulator -T "$title" -e bash -lc "$cmd; exec bash" >/dev/null 2>&1 &
      ;;
    xterm)
      xterm -T "$title" -hold -e bash -lc "$cmd" >/dev/null 2>&1 &
      ;;
  esac
}

open_gui_windows() {
  local bridge_activate="source venv/bin/activate"
  local agent_activate
  agent_activate="$(agent_activate_cmd)" || {
    echo "agent 缺少虚拟环境：$AGENT_DIR/venv 或 $AGENT_DIR/.venv"
    return 1
  }

  local bridge_cmd="cd '$BRIDGE_DIR' && $bridge_activate && export PYTHONUNBUFFERED=1 && PY_CMD=\"\$(command -v python || command -v python3 || true)\" && [[ -n \"\$PY_CMD\" ]] && exec \"\$PY_CMD\" -u bridge.py || echo 'bridge venv 内未找到 python/python3'"
  local agent_cmd="cd '$AGENT_DIR' && $agent_activate && export PYTHONUNBUFFERED=1 && PY_CMD=\"\$(command -v python || command -v python3 || true)\" && [[ -n \"\$PY_CMD\" ]] && exec env PC_AGENT_PORT=$PC_AGENT_PORT \"\$PY_CMD\" -u agent.py || echo 'agent venv 内未找到 python/python3'"

  echo "GUI 模式：打开两个前台终端窗口..."
  open_terminal_window "runai-bridge" "$bridge_cmd" || return 1
  open_terminal_window "runai-agent" "$agent_cmd" || return 1
  echo "已打开 bridge 与 agent 终端窗口。"
}

DEV_PIDS=()

cleanup_dev() {
  local pid
  for pid in "${DEV_PIDS[@]:-}"; do
    if is_running "$pid"; then
      kill "$pid" 2>/dev/null || true
    fi
  done

  sleep 0.5
  for pid in "${DEV_PIDS[@]:-}"; do
    if is_running "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done

  wait 2>/dev/null || true
}

start_dev_bridge() {
  if [[ ! -f "$BRIDGE_DIR/venv/bin/activate" ]]; then
    echo "bridge 缺少虚拟环境：$BRIDGE_DIR/venv"
    return 1
  fi

  (
    cd "$BRIDGE_DIR" || exit 1
    source venv/bin/activate
    export PYTHONUNBUFFERED=1
    PY_CMD="$(python_cmd_in_env || true)"
    if [[ -z "$PY_CMD" ]]; then
      echo "bridge venv 内未找到 python/python3"
      exit 127
    fi
    exec "$PY_CMD" -u bridge.py
  ) 2>&1 | sed -u 's/^/[bridge] /' &

  DEV_PIDS+=("$!")
}

start_dev_agent() {
  local activate
  activate="$(agent_activate_cmd)" || {
    echo "agent 缺少虚拟环境：$AGENT_DIR/venv 或 $AGENT_DIR/.venv"
    return 1
  }

  (
    cd "$AGENT_DIR" || exit 1
    eval "$activate"
    export PYTHONUNBUFFERED=1
    PY_CMD="$(python_cmd_in_env || true)"
    if [[ -z "$PY_CMD" ]]; then
      echo "agent venv 内未找到 python/python3"
      exit 127
    fi
    exec env PC_AGENT_PORT="$PC_AGENT_PORT" "$PY_CMD" -u agent.py
  ) 2>&1 | sed -u 's/^/[agent] /' &

  DEV_PIDS+=("$!")
}

wait_for_dev_exit() {
  while true; do
    local idx
    for idx in 0 1; do
      local pid="${DEV_PIDS[$idx]}"
      if ! is_running "$pid"; then
        wait "$pid" 2>/dev/null
        return $?
      fi
    done
    sleep 0.2
  done
}

run_dev_mode() {
  echo "开发模式：前台启动 bridge + agent（实时日志）"

  DEV_PIDS=()
  start_dev_bridge || return 1
  start_dev_agent || {
    cleanup_dev
    return 1
  }

  echo "按 Ctrl+C 可停止两个进程。"

  trap 'echo; echo "[runai] 收到中断，停止中..."; cleanup_dev; exit 130' INT TERM
  trap 'cleanup_dev' EXIT

  wait_for_dev_exit
  local status=$?
  echo "[runai] 检测到有进程退出（status=$status），停止另一个进程..."
  cleanup_dev
  trap - INT TERM EXIT
  return "$status"
}

start_bridge() {
  local old_pid
  old_pid="$(read_pid "$BRIDGE_PID_FILE" || true)"
  if is_running "$old_pid"; then
    echo "bridge 已在运行，PID=$old_pid"
    return 0
  fi

  echo "启动 bridge..."
  cd "$BRIDGE_DIR" || return 1

  if [[ ! -f "venv/bin/python" ]]; then
    echo "bridge 缺少虚拟环境：$BRIDGE_DIR/venv"
    return 1
  fi

  nohup env PYTHONUNBUFFERED=1 "$BRIDGE_DIR/venv/bin/python" -u bridge.py >>"$BRIDGE_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$BRIDGE_PID_FILE"
  sleep 2

  if is_running "$pid"; then
    echo "bridge 启动成功，PID=$pid，PORT=$BRIDGE_PORT"
  else
    echo "bridge 启动失败，请检查日志：$BRIDGE_LOG"
    rm -f "$BRIDGE_PID_FILE"
    return 1
  fi
}

start_agent() {
  local old_pid
  old_pid="$(read_pid "$AGENT_PID_FILE" || true)"
  if is_running "$old_pid"; then
    echo "agent 已在运行，PID=$old_pid"
    return 0
  fi

  echo "启动 agent..."
  cd "$AGENT_DIR" || return 1

  local pybin=""
  if [[ -f "venv/bin/python" ]]; then
    pybin="$AGENT_DIR/venv/bin/python"
  elif [[ -f ".venv/bin/python" ]]; then
    pybin="$AGENT_DIR/.venv/bin/python"
  else
    echo "agent 缺少虚拟环境：$AGENT_DIR/venv 或 $AGENT_DIR/.venv"
    return 1
  fi

  nohup env PYTHONUNBUFFERED=1 PC_AGENT_PORT="$PC_AGENT_PORT" "$pybin" -u agent.py >>"$AGENT_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$AGENT_PID_FILE"
  sleep 2

  if is_running "$pid"; then
    echo "agent 启动成功，PID=$pid，PORT=$PC_AGENT_PORT"
  else
    echo "agent 启动失败，请检查日志：$AGENT_LOG"
    rm -f "$AGENT_PID_FILE"
    return 1
  fi
}

stop_one() {
  local name="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file" || true)"

  if ! is_running "$pid"; then
    echo "$name 未运行"
    rm -f "$pid_file"
    return 0
  fi

  echo "停止 $name，PID=$pid"
  kill "$pid" 2>/dev/null || true
  sleep 1

  if is_running "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi

  rm -f "$pid_file"
  echo "$name 已停止"
}

status_one() {
  local name="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file" || true)"

  if is_running "$pid"; then
    echo "$name 运行中，PID=$pid"
  else
    echo "$name 未运行"
  fi
}

show_logs() {
  local target="${1:-all}"
  case "$target" in
    bridge)
      echo "==== bridge.log 最后 40 行 ===="
      [[ -f "$BRIDGE_LOG" ]] && tail -n 40 "$BRIDGE_LOG" || echo "暂无日志"
      ;;
    agent)
      echo "==== agent.log 最后 40 行 ===="
      [[ -f "$AGENT_LOG" ]] && tail -n 40 "$AGENT_LOG" || echo "暂无日志"
      ;;
    all)
      echo "==== bridge.log 最后 40 行 ===="
      [[ -f "$BRIDGE_LOG" ]] && tail -n 40 "$BRIDGE_LOG" || echo "暂无日志"
      echo
      echo "==== agent.log 最后 40 行 ===="
      [[ -f "$AGENT_LOG" ]] && tail -n 40 "$AGENT_LOG" || echo "暂无日志"
      ;;
    *)
      echo "logs 用法: runai logs [bridge|agent|all]"
      return 1
      ;;
  esac
}

start_all() {
  echo "Starting AI system (background mode)..."
  start_bridge || return 1
  start_agent || return 1
  echo "AI system started."
}

stop_all() {
  stop_one "bridge" "$BRIDGE_PID_FILE"
  stop_one "agent" "$AGENT_PID_FILE"
}

restart_all() {
  "$0" stop
  "$0" start
}

status_all() {
  status_one "bridge" "$BRIDGE_PID_FILE"
  status_one "agent" "$AGENT_PID_FILE"
}

print_help() {
  cat <<'HELP'
用法:
  runai                     开发模式（同一终端前台启动 bridge+agent，实时日志）
  runai gui                 开发模式（两个终端窗口前台启动）
  runai start               后台模式启动（nohup）
  runai stop                停止后台进程
  runai restart             重启后台进程
  runai status              查看后台状态
  runai logs [bridge|agent|all]
HELP
}

if [[ $# -eq 0 ]]; then
  run_dev_mode
  exit $?
fi

case "$1" in
  gui)
    open_gui_windows
    ;;
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    restart_all
    ;;
  status)
    status_all
    ;;
  logs)
    show_logs "${2:-all}"
    ;;
  help|-h|--help)
    print_help
    ;;
  *)
    print_help
    exit 1
    ;;
esac
