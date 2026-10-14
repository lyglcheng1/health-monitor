#!/usr/bin/env bash
# ============================================================
# 文件: deploy.sh
# 项目: 健康数据监控 health-monitor (一键部署到 Ubuntu 服务器)
# 用法: bash scripts/deploy.sh
# 说明: 打包上传代码到服务器并重启应用（需先配置 SSH 免密）
# ============================================================

set -euo pipefail

# ---------- 服务器配置 ----------
SERVER="root@10.10.10.88"
REMOTE_DIR="/root/apps/health-monitor"
APP_PORT="8020"
# --------------------------------

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 部署内容：代码 + 依赖清单 + 管理脚本
# 不含运行数据（data/）、密钥（.env）、虚拟环境（health-env）、测试（tests）
TAR_FILE=".deploy-tmp.tar.gz"
TAR_CONTENTS=(app static requirements.txt manage.sh)
TAR_EXCLUDES=(--exclude='__pycache__' --exclude='.pytest_cache')

step() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"; }
fail() { printf '[ERROR] %s\n' "$1" >&2; exit 1; }
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5)

# ---------- 0. SSH 免密检查 ----------
step "0/5 检查 SSH 免密连接 (${SERVER})"
if ! ssh "${SSH_OPTS[@]}" "$SERVER" "true" 2>/dev/null; then
    cat >&2 <<'EOF'
[ERROR] SSH 免密未配置。请由用户本人在终端执行一次：

  ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519   # 若 ~/.ssh/id_ed25519 不存在
  ssh-copy-id -i ~/.ssh/id_ed25519.pub root@10.10.10.88

（会提示输入一次密码）之后重新运行本脚本。
EOF
    exit 1
fi
echo "[OK] SSH 免密可用"

# ---------- 1. 远端环境检查 ----------
step "1/5 检查服务器与应用目录"
ssh "${SSH_OPTS[@]}" "$SERVER" "[ -d '$REMOTE_DIR' ]" \
    || fail "服务器上不存在 $REMOTE_DIR，请先手动部署一次基础环境：
  ssh ${SERVER} 'mkdir -p $REMOTE_DIR'"
echo "[OK] $REMOTE_DIR 存在"

# ---------- 2. 打包 ----------
step "2/5 打包代码 (${TAR_CONTENTS[*]})"
[ -f "requirements.txt" ] || fail "找不到 requirements.txt"
[ -f "manage.sh" ]        || fail "找不到 manage.sh"
[ -d "app" ]              || fail "找不到 app/ 目录"
rm -f "$TAR_FILE"
tar -czf "$TAR_FILE" "${TAR_EXCLUDES[@]}" "${TAR_CONTENTS[@]}"
echo "[OK] 打包完成: $(du -h "$TAR_FILE" | cut -f1)"
trap 'rm -f "$TAR_FILE"' EXIT

# ---------- 3. 上传 ----------
step "3/5 上传到服务器"
scp -q "${SSH_OPTS[@]}" "$TAR_FILE" "$SERVER:/tmp/health-monitor-deploy.tar.gz" \
    || fail "上传失败"
echo "[OK] 上传完成"

# ---------- 4. 远端解包覆盖代码 ----------
step "4/5 远端解包覆盖代码（不动 data/ logs/ .env）"
ssh "${SSH_OPTS[@]}" "$SERVER" "
    set -e
    tar -xzf /tmp/health-monitor-deploy.tar.gz -C '$REMOTE_DIR'
    rm -f /tmp/health-monitor-deploy.tar.gz
    chmod +x '$REMOTE_DIR/manage.sh'
" || fail "远端解包失败"
echo "[OK] 代码已更新"

# ---------- 5. 依赖有变化时先装依赖，再重启 ----------
step "5/5 检查依赖并重启应用"
ssh "${SSH_OPTS[@]}" "$SERVER" "'$REMOTE_DIR/manage.sh' restart" \
    || fail "重启失败，可登服务器查看 $REMOTE_DIR/logs/app.out"
ssh "${SSH_OPTS[@]}" "$SERVER" "'$REMOTE_DIR/manage.sh' status" \
    || fail "状态检查未通过（进程或端口异常）"

# 健康检查：/api/site-info 为公开端点（无登录拦截），200 即服务可用
HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://10.10.10.88:${APP_PORT}/api/site-info" || true)"
if [ "$HTTP_CODE" = "200" ]; then
    echo "[OK] 健康检查通过 (HTTP $HTTP_CODE)"
else
    printf '[WARN] 健康检查返回 %s（首次启动可能仍在加载 OCR 模型，稍后访问确认）\n' "$HTTP_CODE"
fi

printf '\n[完成] 部署成功: http://10.10.10.88:%s/\n' "$APP_PORT"