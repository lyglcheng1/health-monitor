<!--
================================================================
文件: README.md
作者: chengge
最后修改: 2026-10-14
说明: GitHub 开源版 README（含本地开发 / 服务器部署 / LLM 接入 / 数据隐私）
================================================================
-->

# Health Monitor 健康数据监控

> 个人身体健康数据本地管理系统：体检报告 / 化验单 / 病历扫描件 → 本地 OCR → LLM 结构化提取 → 异常标注 → 3D 人体大屏可视化问题区域。
> **本地优先，数据不出本机。**

**English:** A self-hosted personal health data manager. Upload physical exam scans → on-device OCR (RapidOCR) → optional LLM extraction → abnormal flagging → interactive 3D human-body dashboard (Three.js). All data stays local (SQLite + files).

---

## ✨ 功能特性

### 📄 体检记录管理（V0.1）
- 批量上传体检图片（≤10 张/批，单张 ≤20MB），自动调用**本地 RapidOCR** 识别文字
- 体检列表 / 详情 / 图片预览 / OCR 文本编辑
- 体检信息（日期 / 医院 / 来源 / 附件 / 备注）可编辑
- 删除记录级联删除指标与图片原件，**不留残留文件**

### 📊 指标管理
- 每条体检记录手动录入指标（名称 / 数值 / 单位 / 参考范围 / 异常标记 / 身体部位）
- 支持单侧参考区间（如 `<5.2`、`>1.0`）与定性结果（如「颜色 淡黄色」不误标异常）

### 🩺 日常身体数据
- 按日期录入体重 / 血压 / 血糖等，类型自由填写，列表倒序展示

### 🧠 可选 LLM 能力
- **模型设置页**添加自定义模型（OpenAI 兼容 / Anthropic 端点），API Key 只入库、不回显
- 启用后用于 **3D 大屏异常部位严重度判定**（严重 / 中度 / 轻度 + AI 判定理由）
- LLM 调用失败 / 非法 JSON / 模型不可用时**自动回退数量规则**，不阻塞主流程
- **不配置 LLM 也能完整使用**（OCR + 手工指标 + 3D 标注）

### 🦴 3D 人体大屏（V0.3）
- Three.js 真 3D 人体模型（复用 [vastlabs/human-atlas](https://github.com/vastlabs/human-atlas) 解剖数据，无外部 CDN）
- **默认只看异常部位**，可一键切换查看全部 20 个器官
- 按「**最近一次体检**」判定当前正常/异常：历史异常已恢复正常（吃药治好）不再标红，时间线保留
- 点击部位查看指标列表（正常绿 / 偏高红 ↑ / 偏低蓝 ↓ / 异常红）与历次检查记录
- 异常部位脉冲高亮 + 头顶标注 + 统计环图，模型可旋转 / 缩放

### 💾 备份还原
- 一键备份：SQLite 在线快照 + uploads 图片原件 + manifest → `tar.gz`
- 备份清单 / 下载 / 删除 / 上传还原
- 还原前自动生成 **safety 快照**，旧库留底，失败逆序回滚

---

## 📸 界面预览

3D 人体大屏与介绍视频的截图包含真实健康数据，为保护隐私**不在此展示**。本地运行后访问 `/body3d` 即可看到 3D 大屏效果；介绍视频可用 `intro-video/`（Remotion 项目）自行渲染。

---

## 🛠 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+ · FastAPI 0.104.x · SQLAlchemy 2.0（异步） |
| 数据库 | SQLite（aiosqlite） |
| OCR | RapidOCR（rapidocr-onnxruntime，CPU 本地推理，自带中英文模型） |
| 3D 大屏 | Three.js（GLB 人体模型，ES Module，无 CDN） |
| 会话 | itsdangerous 签名 Cookie（HttpOnly + SameSite=Lax） |
| 测试 | pytest · pytest-asyncio（外部依赖一律 mock） |

---

## 🚀 快速开始（本地开发）

```bash
# 1) 创建虚拟环境并安装依赖
python -m venv health-env
health-env\Scripts\activate            # Windows
# source health-env/bin/activate        # Linux / macOS
pip install -r requirements.txt

# 2) 复制环境变量样例（可选，不配置则免登录）
copy .env.example .env                 # Windows
# cp .env.example .env                 # Linux / macOS

# 3) 启动服务（默认 8020 端口）
#    Windows:
health-env\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
#    Linux / macOS:
# health-env/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

访问：本机 `http://127.0.0.1:8020`，局域网 `http://<本机IP>:8020`。

> 首次启动会自动创建 `data/health.db` 数据库和 `data/uploads/` 目录。OCR 模型在首次上传图片时加载，可能需要数秒。

---

## ⚙️ 配置说明（.env）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/health.db` | 数据库连接串 |
| `DATA_DIR` | `data` | 数据根目录 |
| `UPLOADS_DIR` | `data/uploads` | 图片原件保存目录 |
| `MAX_UPLOAD_SIZE_MB` | `20` | 单张图片上传大小上限 |
| `SITE_TITLE` | `健康数据监控` | 站点标题 |
| `SITE_TAGLINE` | `个人体检与病历数据管理` | 站点副标题 |
| `AUTH_USERNAME` | `admin` | 登录用户名 |
| `AUTH_PASSWORD` | 空 | **配置后即开启登录**；不配置则免登录 |
| `SESSION_TTL_HOURS` | `168` | 会话有效期（小时） |
| `DEEPSEEK_TIMEOUT` | `60` | LLM 调用通用超时（秒） |

> LLM 的 API Key / 模型端点**不放在 .env**，请在页面「模型设置」中录入（Key 仅存本地数据库，任何接口不回显）。

---

## 🤖 接入 LLM（可选）

1. 在「模型设置」页点击「添加模型」
2. 填写：名称、Base URL、API Key，选择协议（OpenAI 兼容 / Anthropic）
3. 点击「测试协议」验证连通性，保存后**启用**该模型
4. 打开 3D 大屏，异常部位会显示「AI 判定：严重/中度/轻度 + 理由」；未配置或调用失败时自动回退数量规则

支持的端点示例：
- **OpenAI 兼容**：`https://api.openai.com/v1`、DeepSeek、Moonshot 等兼容网关
- **Anthropic**：`https://api.anthropic.com`

---

## 🖥 服务器部署（Ubuntu）

项目提供两个脚本：`scripts/deploy.sh`（一键部署到远程服务器）与 `manage.sh`（进程管理）。二者均需先按你的环境修改配置。

### 1. 修改部署脚本配置

编辑 `scripts/deploy.sh` 顶部：

```bash
SERVER="root@<你的服务器IP>"        # 替换为你的服务器
REMOTE_DIR="/root/apps/health-monitor"
APP_PORT="8020"
```

### 2. 配置 SSH 免密（首次）

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519    # 若不存在
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<服务器IP>
```

### 3. 首次部署：服务器基础环境

```bash
ssh root@<服务器IP> 'mkdir -p /root/apps/health-monitor'
# 上传 .env（含 AUTH_PASSWORD 等密钥，仅保存在服务器）
scp .env root@<服务器IP>:/root/apps/health-monitor/.env
```

### 4. 一键部署

```bash
bash scripts/deploy.sh
```

脚本会：打包 `app/ static/ requirements.txt manage.sh` → 上传 → 远端解包覆盖 → 依赖有变化时自动安装 → 重启服务 → 健康检查（`/api/site-info` 返回 200 即成功）。

### 5. 进程管理

```bash
./manage.sh start      # 启动（后台运行，端口 8020）
./manage.sh stop       # 停止
./manage.sh restart    # 重启
./manage.sh status    # 查看运行状态与端口监听
./manage.sh logs       # 实时查看日志
```

> 脚本直接使用系统 `python3.10`（不存在则回落 `python3`），首次运行自动安装依赖。运行数据保存在服务器 `data/` 目录，部署不会覆盖。

---

## 🧪 测试

```bash
# 完整测试套件（LLM / OCR 外部依赖一律 mock，不发真实请求）
AUTH_PASSWORD= health-env\Scripts\python.exe -m pytest     # Windows
# AUTH_PASSWORD= health-env/bin/python -m pytest           # Linux / macOS
```

覆盖：登录会话、体检 CRUD、指标 CRUD、模型管理、备份还原、3D 大屏聚合（含 LLM 严重度回退）、静态资源守卫（HTML 禁内联 JS/CSS）。

---

## 📁 目录结构

```
app/
  main.py      路由层（登录 / 体检 / 指标 / 身体数据 / 模型 / 备份 / 3D 大屏）
  crud.py      数据访问层（SQLAlchemy 异步 CRUD）
  body3d.py    3D 大屏聚合：body_part → atlas conceptIds、异常部位 / 严重度组装
  ocr.py       RapidOCR 本地识别（懒加载单例，线程池调用）
  llm.py       LLM 路由：模型解析 / 端点归一化 / 回落链 / chat_text
  backup.py    备份还原：SQLite 在线快照 + uploads + manifest → tar.gz
  models.py      ORM 表结构（exams / metrics / body_records / model_settings）
  schemas.py   Pydantic 请求 / 响应模型
  auth.py      登录会话（itsdangerous 签名 Cookie）
  config.py      环境变量配置（路径 / 上传限制 / 认证 / LLM 超时）
static/
  index.html   纯标记 SPA 入口（无内联 JS/CSS，守卫测试强制）
  body3d.html   3D 大屏页面
  css/          全站样式（style.css / body3d.css）
  js/           app.js（哈希路由 SPA）、body3d.js（Three.js 渲染）
scripts/
  deploy.sh      一键部署到远程服务器
  ingest_pdfs.py 批量 PDF 渲染页 → OCR → 入库（官方体检报告用）
manage.sh        start | stop | restart | status | logs
tests/           集成测试（临时库 + mock OCR/LLM）
demo-anatomy/    Three.js 人体模型资源（BodyParts3D / human-atlas，保持原样）
```

---

## 🔒 数据与隐私

- **全部数据本地存储**：SQLite（`data/health.db`）+ 图片原件（`data/uploads/`）+ 备份（`data/backups/`）
- **OCR 本地计算**（RapidOCR onnxruntime），体检图片不送第三方
- LLM 为可选：仅在你配置模型后，将 OCR 文本发送到你自选的端点用于结构化提取/严重度判定
- 写接口带 **Origin/Host 校验中间件**兜底 CSRF；上传文件名清洗防路径穿越；备份文件名白名单校验
- 生产环境请务必配置 `AUTH_PASSWORD` 并妥善保管 `.env`（含会话签名密钥）

---

## 🙏 3D 模型致谢

人体解剖数据来源于：

- **BodyParts3D** © The Database Center for Life Science，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) —— 源几何数据 `isa_BP3D_4.0_obj_99.zip`
- **[vastlabs/human-atlas](https://github.com/vastlabs/human-atlas)**（MIT）—— 优化网格、坐标系转换与浏览器渲染方案

详见 `demo-anatomy/ATTRIBUTION.md`。

---

## 📄 License

[MIT](LICENSE)（项目本体建议使用 MIT；`demo-anatomy/` 内含 BodyParts3D CC BY 4.0 数据与 human-atlas MIT 代码，二次分发时请保留其独立 LICENSE / ATTRIBUTION）。