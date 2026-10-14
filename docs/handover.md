# 交接文档（Handover）

> 本文档供下一轮 Agent 快速恢复上下文使用。新 Agent 开工前**先读本文档 + AGENTS.md**。
> 最后更新：2026-09-06（骨架 + 文档 + 技能阶段完成，尚未跑测试/未部署）

## 1. 项目是什么

**健康数据监控（health-monitor）**：个人身体健康数据本地管理系统，位于 `E:\nasvpn\health-monitor`。
管理历史体检数据、医院检查病历、化验单、体重等个人数据——**以图片/扫描件为主**。
流程：上传图片 → 本地 OCR（RapidOCR）→ LLM 结构化提取指标 → 异常标注 → 3D 人体大屏可视化问题区域。

- 本项目**独立目录、独立虚拟环境、独立 SVN 路径**，与其他项目不要混用。
- 父目录 `E:\nasvpn` 下还有其他项目，所有操作严格限定在 `health-monitor` 目录内。

## 2. 技术栈（冻结）

Python 3.10+ · FastAPI 0.104.x · SQLAlchemy 2.0（异步）+ SQLite（aiosqlite）· RapidOCR（rapidocr-onnxruntime）·
Three.js（V0.3 3D 大屏）· ECharts（V0.2 趋势图）· itsdangerous（签名会话 Cookie）· httpx · pytest
LLM：模型在「模型设置」页添加自定义模型（OpenAI 兼容 / Anthropic 端点），不走 `.env` 配置。

## 3. 已完成 ✅

### 3.1 后端骨架（app/ 全部可编译）
- `config.py` — Settings：database_url（`data/health.db`）、uploads_dir、max_upload_size_mb=20、llm_*、auth_*
- `auth.py` — itsdangerous 签名 Cookie 会话（SALT `hm.session.v1`、Cookie `hm_session`），无 API token
- `models.py` — `Exam`（体检单：exam_date/hospital/source_type/image_path/ocr_text/extracted_json）、
  `Metric`（exam_id FK CASCADE、name/value_text/unit/ref_low/ref_high/abnormal/body_part）、
  `BodyRecord`（日常身体数据）、`ModelSetting`（自定义模型，name 非唯一、enabled 互斥、kind/base_url/api_key/protocol）
- `schemas.py` — LoginRequest / MetricIn/Out / ExamOut/ExamDetailOut/ExamUpdate / BodyRecordIn/Out / 模型 / 备份
- `crud.py` — 模型 CRUD（`custom_models_map` 返回 `dict[int, dict]`）、exam/metric/body_record CRUD
- `ocr.py` — RapidOCR 懒加载单例；`ocr_image_bytes(data: bytes) -> str`，cv2.imdecode → ndarray → 引擎
- `llm.py` — `resolve_model` 回落链（显式 model > 启用的自定义模型 > None）、
  `{name}@{id}` 自定义模型路由、`_endpoint_for_protocol` 归一化端点、`chat_text`
- `backup.py` — SQLite backup API 在线快照 + uploads + manifest.json → tar.gz；还原先 safety 快照、换位、进程内重绑 engine/SessionLocal、失败逆序回滚
- `main.py` — 中间件（limit_body_size 60MB、verify_origin、require_session）、登录/登出/site-info、
  `POST /api/exams`（multipart 批量上传+OCR）、exam/metric/body_record 全套 CRUD、模型管理、备份全套 + `/api/backup/restart`。
  含 `_row_dict(obj)` 助手（剔除 `_sa_instance_state` 等 `_` 开头键，**所有接口必须用它序列化，禁止直接 `__dict__`**）

### 3.2 前端骨架（static/）
- `index.html` — 纯标记（登录视图 + 主视图 + 顶栏导航 + `#content` + toast），**无内联 JS/CSS**
- `css/style.css` — 主色 `#2563EB`、卡片/表单/表格/徽章/登录/3D 占位
- `js/app.js` — 哈希路由 SPA（escapeHtml/api 封装/登录/仪表盘上传/体检列表/详情/指标/身体数据/模型设置/备份），已过 `node --check`
- `favicon.svg` — 心形图标

### 3.3 测试（tests/）
- `conftest.py` — `os.environ.setdefault("AUTH_PASSWORD", "")`；engine/session/client fixture（临时库 + ASGITransport）
- `test_auth.py` T-101~105、`test_exams.py` T-201~208、`test_models.py` T-301~307、`test_static_routes.py`（含 HTML 守卫 + node --check）

### 3.4 文档（docs/ 全部完成）
- `requirements/requirements.md`（需求/范围/V0.1~V0.3 规划/已确认决策 §7/验收 A-01~A-10）
- `architecture/architecture.md`（分层、模块依赖、数据表，含 V0.2 `analyses` 表设计）
- `plans/current-sprint.md`（V0.1 状态、下一步计划、V0.2/V0.3 任务拆分）
- `testing/test-plan.md`（含 V0.2/V0.3 补充 T-501~505）、`testing/acceptance.md`（A-01~A-07 待验证）
- `reference/error-codes.md`（1001/1002/1006/1007/1008/2004/2005/3004/3005/403/413）、`reference/code-walkthrough.md`

### 3.5 配置与脚本
- `requirements.txt`（fastapi==0.104.1、uvicorn[standard]==0.24.0、sqlalchemy==2.0.23、aiosqlite==0.19.0、pydantic==2.5.0、
  httpx>=0.25.2,<0.29、aiofiles==23.2.1、python-multipart==0.0.6、rapidocr-onnxruntime>=1.3.10,<2、python-dotenv==1.0.0、
  itsdangerous==2.2.0、pytest==7.4.3、pytest-asyncio==0.21.1）
- `.env.example`、`.gitignore`（data/logs/.env/health-env/__pycache__/.deploy-tmp.tar.gz）、`README.md`
- `manage.sh`（端口 **8020**，依赖检查 import uvicorn/fastapi/itsdangerous/rapidocr_onnxruntime）
- `scripts/deploy.sh`（SERVER=root@10.10.10.88、REMOTE_DIR=/root/apps/health-monitor、APP_PORT=8020、
  TAR_CONTENTS=(app static requirements.txt manage.sh)，无模型目录）

### 3.6 项目技能（.claude/）
- `.claude/skills/svn-commit/SKILL.md` — 仓库 `svn://10.10.10.20/myrepo/code/apps/myrag/health-monitor`、工作副本 `E:\nasvpn\health-monitor`、
  测试门禁 `AUTH_PASSWORD= health-env/Scripts/python.exe -m pytest -q`、跳过 data/health-env/__pycache__、`.env` 不提交、`.env.example` 入库
- `.claude/skills/deploy/SKILL.md` — root@10.10.10.88:/root/apps/health-monitor、端口 8020、SSH 免密、`.env` 只在服务器
- `.claude/settings.json` — SVN 命令白名单（svn status/diff/info/update/add/resolve/commit），无 hooks
- `AGENTS.md` — 已按 health-monitor 适配（技术栈、端口 8020、硬性规则、核心模块、技能表）

## 4. 已确认的关键决策（用户拍板）

| # | 决策点 | 结论 |
|---|--------|------|
| D1 | AI 提取触发方式 | **手动按钮**（上传后不自动调 LLM，用户点按钮才提取） |
| D2 | 3D 大屏显示范围 | **可切换 全部/异常**，默认只看异常部位 |
| D3 | AI 健康分析结果 | **保存历史**（新增 `analyses` 表，可回看） |
| D4 | 日常身体数据参与 3D | **体重异常也标注**（体重→whole_body 部位，血压→heart 部位） |
| D5 | OCR 方案 | 本地 RapidOCR + LLM 结构化提取（图片不上第三方） |
| D6 | 3D 方案 | Three.js 真 3D（GLB 人体模型） |
| D7 | 部署形态 | 局域网单机部署（服务器 10.10.10.88:8020） |

## 5. 版本规划

- **V0.1 骨架**（当前）：登录、体检上传/OCR、指标 CRUD、日常身体数据、模型设置、备份还原、文档/测试/技能——代码已完成
- **V0.2 AI**：手动 AI 提取按钮、AI 健康分析（analyses 表）、ECharts 趋势图
- **V0.3 3D**：Three.js 人体大屏、全部/异常切换、体重/血压参与标注

## 6. 当前状态与下一步（重要）

### ✅ 当前状态（2026-10-11 更新）
- **依赖已全部安装完成**（health-env 54 个包：fastapi 0.104.1、rapidocr-onnxruntime 1.4.4、onnxruntime 1.23.2、pytest 7.4.3 等）。
- **新增 `pytest.ini`**（`asyncio_mode = auto`）——原测试全是 `async def`，缺配置会被 pytest 全部跳过（21 skipped）。
- **全量测试已跑通：21 passed**。修复了 3 个骨架 bug：
  1. `require_session` 中间件豁免 `/`，导致未登录访问首页返回 200 而非 302（不符 F-101）→ 已移除豁免；
  2. `/api/exams` 的 `files` 参数 `File(...)` 必填，空表单被 FastAPI 以 422 提前拒绝，走不到 400 分支 → 改为 `File(default=[])`；
  3. `test_static_routes.py` 误把外部 `<script src>` 当内联脚本判挂 → 正则只禁内联 `<script>`。
- **已本机启动验证**：`uvicorn app.main:app --port 8020` 启动正常，`/api/site-info`、首页、静态资源均 200（未配 `.env`，登录默认关闭）。
- **新增 V0.3 大屏静态原型 `prototype/`**（body3d.html + css + js，SVG 人体模拟 Three.js 大屏效果，可直接双击打开预览）。
- **仍未提交 SVN、未部署服务器。**

### ✅ 下一步清单（按顺序）
1. ~~安装依赖~~ → 已完成（2026-10-11）
2. ~~跑全量测试~~ → 已完成，**21 passed**；基线已回填 `.claude/skills/svn-commit/SKILL.md` 测试门禁
3. ~~本机启动验证~~ → 已完成基础验证；剩余人工项：配 `.env` 后验证登录、上传体检图片、OCR 出文本、指标展示、模型设置、备份
4. **填验收记录**：`docs/testing/acceptance.md` 把 A-01~A-07 从「待验证」改为实际结果（A-06 测试套件已通过；A-02/04/05 需人工点一遍）
5. **提交 SVN**（用户说「提交svn」时执行，用 `/svn-commit` 技能）：本次新增 `pytest.ini`、`prototype/`，一并纳入首提交；跳过 `data/ health-env/ logs/ __pycache__/ .env .gitignore`
6. **部署服务器**（用户说「部署/更新服务器」时执行，用 `/deploy` 技能）：首次需先建目录、装依赖、放 `.env`，再 `bash scripts/deploy.sh`

### ⏸ 明确不做
- V0.2 / V0.3 功能**尚未开工**，等 V0.1 验证与提交完成后再推进。
- 不要修改父目录下其他项目；不要在其他目录操作。

## 7. 已知坑与注意事项

- **`_row_dict` 序列化**：ORM 对象直接 `__dict__` 会带 `_sa_instance_state` 导致 JSON 序列化失败，必须用 `_row_dict`。
- **测试必须带 `AUTH_PASSWORD=` 前缀**：`.env` 若配置了登录密码，不带前缀测试会 401。
- **OCR mock**：测试中禁止真实调用 RapidOCR（`monkeypatch app.ocr.ocr_image_bytes`）。
- **HTML 守卫**：`static/index.html` 禁止内联 style/script/on* 属性，否则 `test_static_routes.py` 挂。
- **SVN**：提交信息用 UTF-8 临时文件（`-F`），提交后自检乱码 `svn log -r N --xml | grep -c "锛\|鍒\|鐨"` 应为 0；
  **禁止 `--password` 写命令行**，凭据在 `~/.subversion/auth`。
- **部署**：`.env` 只在服务器上，同步脚本不覆盖它；服务器上运行数据在 `data/`，部署不会动。
- **同服务器多项目**：8010 / 8000 / 8020 三个服务共存，管理脚本各管各的，别混用。
- **先文档后开发纪律**：用户要求每阶段先完善文档再写代码，V0.2/V0.3 动工前先更新需求/架构/计划文档。

## 8. 联系上下文

如需追溯代码细节/决策过程，可读取本机 Claude 会话记录（`C:\Users\Lenovo\.claude\projects\e--nasvpn-health-monitor\` 下的 jsonl）。