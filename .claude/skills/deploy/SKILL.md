---
name: deploy
description: 自动部署健康数据监控（health-monitor）到 Ubuntu 服务器（10.10.10.88），同步代码并重启应用。当用户说"部署到服务器"、"更新服务器"、"重启服务器上的应用"、"发布新版本"时使用。
---

# 自动部署到服务器

把本地项目同步到 Ubuntu 服务器并重启应用。目标服务器信息：

| 项 | 值 |
|---|---|
| 服务器 | `root@10.10.10.88`（Ubuntu 22.04，系统 Python 3.10，无虚拟环境） |
| 应用目录 | `/root/apps/health-monitor` |
| 管理脚本 | `/root/apps/health-monitor/manage.sh`（start/stop/restart/status/logs） |
| 访问地址 | http://10.10.10.88:8020 （同机共存 8010 / 8000 服务） |
| 密码 | 只用于首次 `ssh-copy-id`，由用户本人输入——**禁止把密码写进任何文件或命令行参数** |

## 认证（SSH 免密）

首次部署前检查密钥是否已配置（`BatchMode` 不会卡在密码输入）：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@10.10.10.88 "echo SSH_KEY_OK"
```

- 输出 `SSH_KEY_OK` → 免密已配置，直接部署。
- `Permission denied` → 需要**用户本人**在终端执行一次（Claude 不要代输密码）：

```bash
# 1. 本地生成密钥（若 ~/.ssh/id_ed25519 不存在）
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# 2. 把公钥推到服务器（会提示输入一次密码）
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@10.10.10.88
```

配置好后再跑一次 BatchMode 检查确认。**之后所有部署操作全部免密。**

## 首次部署（服务器还没有 /root/apps/health-monitor 时）

常规部署脚本要求目录已存在；首次先手工做一次基础环境：

```bash
# 1. 建目录
ssh root@10.10.10.88 "mkdir -p /root/apps/health-monitor"

# 2. 上传代码包并解包（deploy.sh 在目录存在后正常工作）
bash scripts/deploy.sh

# 3. 首次启动会自动装依赖（requirements.txt 含 onnxruntime，可能较久）
ssh root@10.10.10.88 "/root/apps/health-monitor/manage.sh start"

# 4. 确认 .env 在服务器上就位（见下方「.env」注意事项）
```

## 部署步骤（每次部署都走这里）

### 1. 部署前跑测试（后端有改动时）

```bash
cd "e:/nasvpn/health-monitor" && PYTHONUTF8=1 AUTH_PASSWORD= health-env/Scripts/python.exe -m pytest -q
```

基线以首次跑通后的输出为准（`AUTH_PASSWORD=` 前缀必须带，否则 .env 开启登录会让 API 测试 401）。
测试不过 → 停下来报告失败，**不要部署**。仅前端静态文件（css/js/html）改动可跳过测试。

### 2. 同步代码（用本项目脚本）

```bash
bash scripts/deploy.sh
```

脚本行为（详见 scripts/deploy.sh）：
- `ssh` 检查服务器可达 + `/root/apps/health-monitor` 存在
- 打 tar 包上传后远端解包覆盖 `app/`、`static/`、`requirements.txt`、`manage.sh`（天然排除 `data/`、`.env`、`health-env/`、`tests/`、`docs/` 等运行数据与本地专属内容）
- 远端执行 `manage.sh restart`，然后 `manage.sh status` 验证进程与端口 8020 监听
- curl `/api/site-info` 健康检查（公开端点，不受登录拦截影响）
- 任一步失败立即退出并显示哪一步失败

### 3. 部署后验证

```bash
curl -s -o /dev/null -w "%{http_code}" http://10.10.10.88:8020/api/site-info
# 期望输出 200
```

向用户报告：上传了什么、重启结果、健康检查结果、访问地址。

## 常用远程操作

```bash
ssh root@10.10.10.88 "/root/apps/health-monitor/manage.sh status"       # 看状态
ssh root@10.10.10.88 "tail -50 /root/apps/health-monitor/logs/app.out"  # 最近日志
ssh root@10.10.10.88 "/root/apps/health-monitor/manage.sh stop"         # 停应用
```

## 注意事项

- **不要**在命令行里明文传密码（`sshpass -p`、`ssh root:pass@` 一律禁止）；密码只用于首次 `ssh-copy-id`，且由用户自己输入
- **运行数据全在服务器 `data/`**：health.db（体检/指标/身体数据/模型配置）、uploads/（体检图片原件）、backups/（备份包）——同步脚本永远不碰；上传只覆盖代码，不删服务器上的其他文件
- **`.env` 只在服务器上有真实 Key**（AUTH_PASSWORD；模型 Key 存「模型设置」页对应 SQLite），同步不上传它；改环境变量须登服务器手动改。本地 `.env` 含真实密钥，任何时候不得把内容写入输出或提交物
- `requirements.txt` 有变化时，`manage.sh restart` 内置的依赖检查会先装新依赖再启动（首次装 onnxruntime 较久）；也可手动：`ssh root@10.10.10.88 "python3.10 -m pip install -r /root/apps/health-monitor/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"`
- **无向量模型目录**（不含 BGE/Chroma），OCR 模型随 `rapidocr-onnxruntime` pip 包自带，无需单独上传模型
- 部署是**覆盖线上服务**，用户说"部署/发布/更新服务器"即视为授权；但部署失败时先报告，不要反复重试
- 同服务器还有其他项目（端口 8010 / 8000，管理脚本各自独立）——三套脚本互不相干，不要混用目录