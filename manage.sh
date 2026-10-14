#!/usr/bin/env bash
# ============================================================
# 文件: manage.sh
# 项目: 健康数据监控 health-monitor (Ubuntu 22.04 / 系统 Python3.10 部署)
# 用法: ./manage.sh start|stop|restart|status|logs
# 说明: 直接使用系统 python3.10，不使用虚拟环境；
#       运行数据在 data/（health.db + uploads + backups），脚本只管进程
# ============================================================

set -u

# ---------- 可按需修改的配置 ----------
APP_NAME="health-monitor"                  # 服务名（用于提示信息）
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # 脚本所在目录 = 项目目录
HOST="0.0.0.0"                             # 局域网访问；仅本机用 127.0.0.1
PORT="8020"                                # 与同服务器其他服务（8010/8000）共存
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/app.out"
PID_FILE="$LOG_DIR/app.pid"
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"   # 国内服务器镜像；海外可清空
# --------------------------------------

export PYTHONUTF8=1   # 与 Windows 开发环境一致，避免任何 locale 编码意外
cd "$APP_DIR" || exit 1
mkdir -p "$LOG_DIR" data   # data/ 实际由 init_db 创建，这里兜底

# 选择解释器：优先 python3.10，没有就用 python3
if command -v python3.10 >/dev/null 2>&1; then
    PYTHON="python3.10"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "[ERROR] 未找到 python3，请先安装: sudo apt install python3.10 python3-pip"
    exit 1
fi

# 首次运行：检查并安装依赖（装到系统/用户 site-packages，不用虚拟环境）
if ! "$PYTHON" -c "import uvicorn, fastapi, itsdangerous, rapidocr_onnxruntime" >/dev/null 2>&1; then
    echo "[INFO] 首次运行，使用 $PYTHON 安装依赖（requirements.txt，含 onnxruntime，可能较久）..."
    if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
        echo "[ERROR] 缺少 pip，请先安装: sudo apt install python3-pip"
        exit 1
    fi
    if [ -n "$PIP_MIRROR" ]; then
        "$PYTHON" -m pip install -r requirements.txt -i "$PIP_MIRROR" \
            || "$PYTHON" -m pip install --user -r requirements.txt -i "$PIP_MIRROR"
    else
        "$PYTHON" -m pip install -r requirements.txt \
            || "$PYTHON" -m pip install --user -r requirements.txt
    fi
    echo "[INFO] 依赖安装完成。"
fi

get_pid() {
    # 优先读 pid 文件，其次按启动命令兜底查找
    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi
    pgrep -f "uvicorn app.main:app.*--port $PORT" | head -n 1
}

do_start() {
    local pid
    pid="$(get_pid)"
    if [ -n "$pid" ]; then
        echo "[WARN] $APP_NAME 已在运行 (PID: $pid)，无需重复启动。"
        exit 0
    fi
    echo "[INFO] 启动 $APP_NAME ($PYTHON, host=$HOST, port=$PORT)..."
    # setsid 让新服务进入独立会话/进程组：即使被管理脚本从「正在处理请求的服务
    # 进程自身」内调用（如 /api/backup/restart 杀掉当前 worker 后再拉起），新
    # uvicorn 也不会随父进程一同被回收，确保重启后服务存活。
    setsid nohup "$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" \
        >> "$LOG_FILE" 2>&1 < /dev/null &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    # 等待最多 8 秒确认进程存活（首次启动加载 OCR 模型，更久属正常）
    for _ in 1 2 3 4 5 6 7 8; do
        sleep 1
        if ! kill -0 "$new_pid" 2>/dev/null; then
            echo "[ERROR] 启动失败，最近日志如下："
            tail -n 30 "$LOG_FILE"
            rm -f "$PID_FILE"
            exit 1
        fi
    done
    echo "[OK] $APP_NAME 已启动 (PID: $new_pid)"
    echo "     访问地址: http://<服务器IP>:$PORT/"
    echo "     查看日志: ./manage.sh logs"
}

do_stop() {
    local pid
    pid="$(get_pid)"
    if [ -z "$pid" ]; then
        echo "[INFO] $APP_NAME 未在运行。"
        rm -f "$PID_FILE"
        return 0
    fi
    echo "[INFO] 正在停止 $APP_NAME (PID: $pid)..."
    kill "$pid" 2>/dev/null
    # 最多等 10 秒优雅退出
    for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "[WARN] 优雅停止超时，强制结束 (kill -9)..."
        kill -9 "$pid" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    echo "[OK] $APP_NAME 已停止。"
}

do_status() {
    local pid
    pid="$(get_pid)"
    if [ -n "$pid" ]; then
        echo "[OK] $APP_NAME 运行中 (PID: $pid)"
        ps -o pid,user,etime,%cpu,%mem,cmd -p "$pid" 2>/dev/null
        if command -v ss >/dev/null 2>&1; then
            ss -ltn 2>/dev/null | grep -q ":$PORT " \
                && echo "     端口 $PORT 监听正常" \
                || echo "     [WARN] 端口 $PORT 尚未监听（可能仍在启动中）"
        fi
        exit 0
    fi
    echo "[STOP] $APP_NAME 未在运行。"
    exit 3
}

do_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "[INFO] 暂无日志文件: $LOG_FILE"
        exit 0
    fi
    tail -n 100 -f "$LOG_FILE"    # Ctrl+C 退出，不影响服务
}

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; do_start ;;
    status)  do_status ;;
    logs)    do_logs ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo "  start   启动服务（后台运行）"
        echo "  stop    停止服务"
        echo "  restart 重启服务"
        echo "  status  查看运行状态"
        echo "  logs    实时查看日志 (Ctrl+C 退出)"
        exit 1
        ;;
esac