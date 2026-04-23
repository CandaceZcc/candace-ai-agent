#!/usr/bin/env bash
set -u
set -o pipefail

ROOT="$HOME/candace-ai-agent"
VENV="$ROOT/.venv"
BRIDGE_DIR="$ROOT/qq-ai-bridge"
AGENT_DIR="$ROOT/pc-agent"
OPENMAIC_DIR="$HOME/OpenMAIC"

RUNTIME_DIR="$ROOT/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

BRIDGE_LOG="$LOG_DIR/bridge.log"
AGENT_LOG="$LOG_DIR/agent.log"
OPENMAIC_LOG="$LOG_DIR/openmaic.log"

BRIDGE_PID_FILE="$PID_DIR/bridge.pid"
AGENT_PID_FILE="$PID_DIR/agent.pid"
OPENMAIC_PID_FILE="$PID_DIR/openmaic.pid"

PC_AGENT_PORT="${PC_AGENT_PORT:-5050}"
BRIDGE_NODE_VERSION="${BRIDGE_NODE_VERSION:-22.22.1}"
OPENMAIC_NODE_VERSION="${OPENMAIC_NODE_VERSION:-22.22.2}"
BRIDGE_PORT="${BRIDGE_PORT:-5000}"
OPENMAIC_PORT_PRIMARY="${OPENMAIC_PORT_PRIMARY:-3000}"
OPENMAIC_PORT_FALLBACK="${OPENMAIC_PORT_FALLBACK:-3002}"
BRIDGE_ADMIN_UI_URL="http://127.0.0.1:${BRIDGE_PORT}/admin/groups"

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

say() {
  echo "[$(timestamp)] $*"
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

build_follow_log_cmd() {
  local primary="$1"
  cat <<EOF
primary='$primary'
target="\$primary"
mkdir -p "\$(dirname "\$target")"
touch "\$target"
echo "跟随日志: \$target"
tail -F -n 200 "\$target"
EOF
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

  if [[ ! -d "$BRIDGE_DIR" ]]; then
    echo "未找到 bridge 目录：$BRIDGE_DIR"
    exit 1
  fi

  if [[ ! -d "$AGENT_DIR" ]]; then
    echo "未找到 agent 目录：$AGENT_DIR"
    exit 1
  fi

  if [[ ! -d "$OPENMAIC_DIR" ]]; then
    echo "未找到 OpenMAIC 目录：$OPENMAIC_DIR"
    echo "如果路径不对，改 runai.sh 里的 OPENMAIC_DIR"
    exit 1
  fi
}

load_nvm() {
  export NVM_DIR="$HOME/.nvm"
  if [[ -s "$NVM_DIR/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    source "$NVM_DIR/nvm.sh"
  else
    echo "未找到 nvm.sh：$NVM_DIR/nvm.sh"
    exit 1
  fi
}

is_pid_running() {
  local pid="$1"
  [[ -n "${pid:-}" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

find_pid_by_port() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v p=":$port" '
    index($4, p) {
      if (match($0, /pid=[0-9]+/)) {
        print substr($0, RSTART + 4, RLENGTH - 4)
        exit
      }
    }
  '
}

service_running_on_port() {
  local port="$1"
  local pid
  pid="$(find_pid_by_port "$port")"
  [[ -n "${pid:-}" ]] || return 1
  is_pid_running "$pid"
}

service_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "${pid:-}" ]] || return 1
  is_pid_running "$pid"
}

bridge_running() {
  service_running "$BRIDGE_PID_FILE" || service_running_on_port "$BRIDGE_PORT"
}

agent_running() {
  service_running "$AGENT_PID_FILE" || service_running_on_port "$PC_AGENT_PORT"
}

openmaic_running() {
  service_running "$OPENMAIC_PID_FILE" \
    || service_running_on_port "$OPENMAIC_PORT_PRIMARY" \
    || service_running_on_port "$OPENMAIC_PORT_FALLBACK"
}

write_pid() {
  local pid_file="$1"
  local pid="$2"
  echo "$pid" > "$pid_file"
}

remove_pid() {
  local pid_file="$1"
  rm -f "$pid_file"
}

start_bridge_bg() {
  if bridge_running; then
    local pid
    pid="$(cat "$BRIDGE_PID_FILE" 2>/dev/null || true)"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$BRIDGE_PORT")"
    [[ -n "${pid:-}" ]] && write_pid "$BRIDGE_PID_FILE" "$pid"
    say "bridge 已在运行，PID=${pid:-unknown} PORT=$BRIDGE_PORT"
    return 0
  fi

  say "启动 bridge ..."
  (
    cd "$ROOT" || exit 1
    source "$VENV/bin/activate"
    load_nvm
    nvm use "$BRIDGE_NODE_VERSION" >/dev/null || exit 1
    cd "$BRIDGE_DIR" || exit 1
    export PYTHONUNBUFFERED=1
    nohup python3 -u bridge.py >>"$BRIDGE_LOG" 2>&1 &
    echo $! > "$BRIDGE_PID_FILE"
    wait
  ) >/dev/null 2>&1 &

  sleep 1
  if bridge_running; then
    local pid
    pid="$(cat "$BRIDGE_PID_FILE" 2>/dev/null || true)"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$BRIDGE_PORT")"
    [[ -n "${pid:-}" ]] && write_pid "$BRIDGE_PID_FILE" "$pid"
    say "bridge 启动成功，PID=${pid:-unknown} PORT=$BRIDGE_PORT"
  else
    say "bridge 启动失败，查看日志：$BRIDGE_LOG"
    return 1
  fi
}

start_agent_bg() {
  if agent_running; then
    local pid
    pid="$(cat "$AGENT_PID_FILE" 2>/dev/null || true)"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$PC_AGENT_PORT")"
    [[ -n "${pid:-}" ]] && write_pid "$AGENT_PID_FILE" "$pid"
    say "agent 已在运行，PID=${pid:-unknown} PORT=$PC_AGENT_PORT"
    return 0
  fi

  say "启动 agent ..."
  (
    cd "$ROOT" || exit 1
    source "$VENV/bin/activate"
    cd "$AGENT_DIR" || exit 1
    export PYTHONUNBUFFERED=1
    nohup env PC_AGENT_PORT="$PC_AGENT_PORT" python3 -u agent.py >>"$AGENT_LOG" 2>&1 &
    echo $! > "$AGENT_PID_FILE"
    wait
  ) >/dev/null 2>&1 &

  sleep 1
  if agent_running; then
    local pid
    pid="$(cat "$AGENT_PID_FILE" 2>/dev/null || true)"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$PC_AGENT_PORT")"
    [[ -n "${pid:-}" ]] && write_pid "$AGENT_PID_FILE" "$pid"
    say "agent 启动成功，PID=${pid:-unknown} PORT=$PC_AGENT_PORT"
  else
    say "agent 启动失败，查看日志：$AGENT_LOG"
    return 1
  fi
}

start_openmaic_bg() {
  if openmaic_running; then
    local pid
    pid="$(cat "$OPENMAIC_PID_FILE" 2>/dev/null || true)"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$OPENMAIC_PORT_PRIMARY")"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$OPENMAIC_PORT_FALLBACK")"
    [[ -n "${pid:-}" ]] && write_pid "$OPENMAIC_PID_FILE" "$pid"
    say "openmaic 已在运行，PID=${pid:-unknown} PORT=${OPENMAIC_PORT_PRIMARY}/${OPENMAIC_PORT_FALLBACK}"
    return 0
  fi

  say "启动 openmaic ..."
  (
    load_nvm
    cd "$OPENMAIC_DIR" || exit 1
    nvm use "$OPENMAIC_NODE_VERSION" >/dev/null || exit 1
    nohup pnpm dev --hostname 0.0.0.0 >>"$OPENMAIC_LOG" 2>&1 &
    echo $! > "$OPENMAIC_PID_FILE"
    wait
  ) >/dev/null 2>&1 &

  sleep 2
  if openmaic_running; then
    local pid
    pid="$(cat "$OPENMAIC_PID_FILE" 2>/dev/null || true)"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$OPENMAIC_PORT_PRIMARY")"
    [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$OPENMAIC_PORT_FALLBACK")"
    [[ -n "${pid:-}" ]] && write_pid "$OPENMAIC_PID_FILE" "$pid"
    say "openmaic 启动成功，PID=${pid:-unknown} PORT=${OPENMAIC_PORT_PRIMARY}/${OPENMAIC_PORT_FALLBACK}"
  else
    say "openmaic 启动失败，查看日志：$OPENMAIC_LOG"
    return 1
  fi
}

stop_one() {
  local name="$1"
  local pid_file="$2"

  if ! service_running "$pid_file"; then
    say "$name 未运行"
    remove_pid "$pid_file"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  say "停止 $name，PID=$pid"
  kill "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if is_pid_running "$pid"; then
      sleep 0.3
    else
      break
    fi
  done

  if is_pid_running "$pid"; then
    say "$name 未正常退出，强制结束"
    kill -9 "$pid" 2>/dev/null || true
  fi

  remove_pid "$pid_file"
  say "$name 已停止"
}

status_one() {
  local name="$1"
  local pid_file="$2"
  local pid=""
  case "$name" in
    bridge)
      if bridge_running; then
        pid="$(cat "$pid_file" 2>/dev/null || true)"
        [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$BRIDGE_PORT")"
        [[ -n "${pid:-}" ]] && write_pid "$pid_file" "$pid"
        echo "$name: RUNNING (PID=${pid:-unknown}, PORT=$BRIDGE_PORT)"
        return 0
      fi
      ;;
    agent)
      if agent_running; then
        pid="$(cat "$pid_file" 2>/dev/null || true)"
        [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$PC_AGENT_PORT")"
        [[ -n "${pid:-}" ]] && write_pid "$pid_file" "$pid"
        echo "$name: RUNNING (PID=${pid:-unknown}, PORT=$PC_AGENT_PORT)"
        return 0
      fi
      ;;
    openmaic)
      if openmaic_running; then
        pid="$(cat "$pid_file" 2>/dev/null || true)"
        [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$OPENMAIC_PORT_PRIMARY")"
        [[ -n "${pid:-}" ]] || pid="$(find_pid_by_port "$OPENMAIC_PORT_FALLBACK")"
        [[ -n "${pid:-}" ]] && write_pid "$pid_file" "$pid"
        echo "$name: RUNNING (PID=${pid:-unknown}, PORT=${OPENMAIC_PORT_PRIMARY}/${OPENMAIC_PORT_FALLBACK})"
        return 0
      fi
      ;;
  esac
  echo "$name: STOPPED"
}

run_window_mode() {
  ensure_env
  echo "Bridge 管理前端入口: $BRIDGE_ADMIN_UI_URL"

  local bridge_cmd="
    cd '$ROOT' || exit 1
    source '$VENV/bin/activate'
    export NVM_DIR='$HOME/.nvm'
    [ -s \"\$NVM_DIR/nvm.sh\" ] && source \"\$NVM_DIR/nvm.sh\"
    nvm use '$BRIDGE_NODE_VERSION' >/dev/null || exit 1
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

  local openmaic_cmd="
    export NVM_DIR='$HOME/.nvm'
    [ -s \"\$NVM_DIR/nvm.sh\" ] && source \"\$NVM_DIR/nvm.sh\"
    cd '$OPENMAIC_DIR' || exit 1
    nvm use '$OPENMAIC_NODE_VERSION' >/dev/null || exit 1
    pnpm dev --hostname 0.0.0.0 2>&1 | tee -a '$OPENMAIC_LOG'
  "

  echo "窗口模式：弹出 bridge / agent / openmaic 三个独立终端..."
  if bridge_running; then
    open_terminal_window "runai-bridge" "$(build_follow_log_cmd "$BRIDGE_LOG")" || exit 1
  else
    open_terminal_window "runai-bridge" "$bridge_cmd" || exit 1
  fi

  if agent_running; then
    open_terminal_window "runai-agent" "$(build_follow_log_cmd "$AGENT_LOG")" || exit 1
  else
    open_terminal_window "runai-agent" "$agent_cmd" || exit 1
  fi

  if openmaic_running; then
    open_terminal_window "runai-openmaic" "$(build_follow_log_cmd "$OPENMAIC_LOG")" || exit 1
  else
    open_terminal_window "runai-openmaic" "$openmaic_cmd" || exit 1
  fi
  echo "已打开三个终端窗口。"
}

run_dev_mode() {
  ensure_env
  load_nvm

  echo "开发模式：前台启动 bridge + agent + openmaic（实时日志）"
  echo "Bridge 管理前端入口: $BRIDGE_ADMIN_UI_URL"
  echo "按 Ctrl+C 可停止全部进程。"

  (
    cd "$ROOT" || exit 1
    source "$VENV/bin/activate"
    load_nvm
    nvm use "$BRIDGE_NODE_VERSION" >/dev/null || exit 1
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

  (
    load_nvm
    cd "$OPENMAIC_DIR" || exit 1
    nvm use "$OPENMAIC_NODE_VERSION" >/dev/null || exit 1
    exec pnpm dev --hostname 0.0.0.0
  ) 2>&1 | sed -u 's/^/[openmaic] /' &
  OPENMAIC_PID=$!

  cleanup() {
    kill "$BRIDGE_PID" "$AGENT_PID" "$OPENMAIC_PID" 2>/dev/null || true
    sleep 0.5
    kill -9 "$BRIDGE_PID" "$AGENT_PID" "$OPENMAIC_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" "$AGENT_PID" "$OPENMAIC_PID" 2>/dev/null || true
  }

  trap 'echo; echo "[runai] 收到中断，停止中..."; cleanup; exit 130' INT TERM
  trap 'cleanup' EXIT

  while true; do
    if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
      wait "$BRIDGE_PID" 2>/dev/null
      STATUS=$?
      echo "[runai] 检测到 bridge 退出（status=$STATUS），停止其他服务..."
      cleanup
      trap - INT TERM EXIT
      exit "$STATUS"
    fi

    if ! kill -0 "$AGENT_PID" 2>/dev/null; then
      wait "$AGENT_PID" 2>/dev/null
      STATUS=$?
      echo "[runai] 检测到 agent 退出（status=$STATUS），停止其他服务..."
      cleanup
      trap - INT TERM EXIT
      exit "$STATUS"
    fi

    if ! kill -0 "$OPENMAIC_PID" 2>/dev/null; then
      wait "$OPENMAIC_PID" 2>/dev/null
      STATUS=$?
      echo "[runai] 检测到 openmaic 退出（status=$STATUS），停止其他服务..."
      cleanup
      trap - INT TERM EXIT
      exit "$STATUS"
    fi

    sleep 0.2
  done
}

start_all() {
  ensure_env
  start_bridge_bg
  start_agent_bg
  start_openmaic_bg
  say "Bridge 管理前端入口: $BRIDGE_ADMIN_UI_URL"
}

stop_all() {
  stop_one "openmaic" "$OPENMAIC_PID_FILE"
  stop_one "agent" "$AGENT_PID_FILE"
  stop_one "bridge" "$BRIDGE_PID_FILE"
}

status_all() {
  status_one "bridge" "$BRIDGE_PID_FILE"
  status_one "agent" "$AGENT_PID_FILE"
  status_one "openmaic" "$OPENMAIC_PID_FILE"
}

logs_one() {
  local name="$1"
  local file="$2"
  local target="$file"
  if [[ ! -f "$target" ]]; then
    mkdir -p "$(dirname "$target")"
    touch "$target"
  fi
  echo "跟随日志：$target"
  tail -F -n 200 "$target"
}

case "${1:-window}" in
  window)
    run_window_mode
    ;;
  dev)
    run_dev_mode
    ;;
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  logs)
    case "${2:-}" in
      bridge)
        logs_one "bridge" "$BRIDGE_LOG"
        ;;
      agent)
        logs_one "agent" "$AGENT_LOG"
        ;;
      openmaic)
        logs_one "openmaic" "$OPENMAIC_LOG"
        ;;
      *)
        echo "用法: $0 logs [bridge|agent|openmaic]"
        exit 1
        ;;
    esac
    ;;
  *)
    echo "用法: $0 [window|dev|start|stop|restart|status|logs bridge|agent|openmaic]"
    exit 1
    ;;
esac
