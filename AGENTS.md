<!--
================================================================
文件: AGENTS.md
作者: chengge
最后修改: 2026-10-11
================================================================
-->
# AGENTS.md

## 项目简介
个人身体健康数据监控（开发代号 health-monitor）：历史体检数据、医院检查病历、化验单、体重等个人健康数据的本地管理系统。数据以图片/扫描件为主 → 本地 OCR（RapidOCR）提取文字 → LLM 结构化提取指标 → 异常标注 → 3D 人体大屏可视化问题区域。单机局域网，Python 3.10+ / FastAPI / SQLite / RapidOCR / Three.js。

## 技术栈（冻结，不得擅自升级）
Python 3.10+ · FastAPI 0.104.x · SQLAlchemy 2.0（异步）· SQLite（aiosqlite）· RapidOCR（rapidocr-onnxruntime）· Three.js（V0.3 人体大屏）· ECharts（V0.2 趋势图）· itsdangerous（签名会话 Cookie）· httpx · pytest
问答/AI 提取：可选接 LLM（OpenAI 兼容 / Anthropic 端点），在「模型设置」页添加自定义模型并启用（Key 入库，不走 .env）。

## 快速导航
| 想做什么 | 去哪看 |
|---------|--------|
| **交接文档（新 Agent 先读）** | docs/handover.md |
| 需求 / 范围 / 验收 | docs/requirements/requirements.md |
| 架构 / 模块依赖 / 数据表 | docs/architecture/architecture.md |
| 当前迭代与最近完成 | docs/plans/current-sprint.md |
| 测试计划 | docs/testing/test-plan.md |
| 验收记录 | docs/testing/acceptance.md |
| 错误码规范 | docs/reference/error-codes.md |
| **代码链路导读（新手先读）** | docs/reference/code-walkthrough.md |
| Remotion 技能简介（视频创作） | docs/reference/remotion-skills.md |

## 启动
```bash
health-env\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```
启动后本机访问 http://127.0.0.1:8020；局域网其他机器访问 http://<本机IP>:8020（写接口带 Origin/Host 校验中间件兜底 CSRF）。

## 硬性规则
1. 分层依赖：前端 → 路由层 → 业务层 → 数据层；下层不可依赖上层
2. API 成功统一 `{code, data, message}`；错误经 HTTPException，实际 `{"detail": {code, message}}` + 状态码（见 error-codes.md）
3. 敏感信息（API Key / 口令）一律走环境变量（.env）或本地数据库（模型设置页录入），禁止硬编码进源码
4. 异步 I/O 用 async/await + aiofiles/httpx；日志用 logging 统一格式
5. 新增 API 必须有集成测试；外部依赖（LLM 网关 / OCR 引擎）一律 mock，禁止在测试中发真实请求
6. 前端渲染动态内容先 escapeHtml，禁止把外部输入直接拼 innerHTML
7. **体检图片上传后，图片原件、OCR 文本、结构化提取结果（extracted_json）三处数据必须一致**
8. 删除/编辑体检记录后，旧图片文件（uploads/）必须同步清理，不允许残留
9. 外部服务调用（LLM 提取/分析）统一封装超时/重试/错误透传
10. **编码规范：源码/文档一律 UTF-8 无 BOM；Python/Markdown 用 LF 行尾；仅 `.cmd/.bat` 批处理用 ASCII + CRLF（Windows cmd 解析需要），禁止在批处理内写中文（易被代码页误解析）**
11. **前端分层：HTML 文件只写纯标记，禁止内联 `<style>`/`<script>` 块与 `on*` 事件属性、`style=` 属性**；样式一律 static/css/，逻辑与事件绑定一律 static/js/（守卫测试 test_static_routes.py）

## 核心模块（按目录）
| 模块 | 职责 |
|------|------|
| app/main.py | 路由层：认证、体检记录、指标、身体数据、模型管理、备份还原、3D 大屏聚合 |
| app/crud.py | 数据访问层：SQLite 体检/指标/身体数据/模型 CRUD |
| app/body3d.py | 3D 大屏聚合：body_part → atlas conceptIds，异常部位/issues/records/severity 组装 |
| app/ocr.py | OCR 服务：RapidOCR 本地识别图片文本（懒加载单例） |
| app/llm.py | LLM 路由：模型解析/端点归一化/回落链/chat_text |
| app/backup.py | 备份还原：SQLite 快照 + uploads + manifest → tar.gz |
| app/db.py | 引擎/SessionLocal/建表 |
| app/models.py | ORM：Exam / Metric / BodyRecord / ModelSetting |
| app/schemas.py | Pydantic 请求/响应模型 |
| app/config.py | Settings：路径、上传限制、LLM、认证 |
| app/auth.py | 登录认证：itsdangerous 签名 Cookie 会话 |

## 安全基线
- 外部 API 调用（LLM 提取/分析）统一封装，超时/错误可追溯
- 体检图片不送第三方，OCR 本地计算（RapidOCR onnxruntime）
- 上传限制大小与类型；备份/还原流程带 safety 快照与失败回滚
- 会话登录 Cookie 签名防篡改；写接口校验 Origin/Host

## 前端设计规范
简洁实用风格。字体系统默认；主色 #2563EB；图标内联 SVG；hover 过渡 200ms。
文件组织（硬性规则 11）：`static/index.html` 纯标记；`static/css/style.css` 全站样式；
`static/js/app.js` 全部逻辑与事件绑定（第三方库仍放 static/vendor/）。HTML 内不写 JS/CSS。
3D 大屏：`static/body3d.html` + `static/js/body3d.js` + `static/css/body3d.css`，Three.js 资源复用 `demo-anatomy/vendor/`（demo-anatomy 目录保持原样，勿改）。

## 项目技能
| 技能 | 用途 |
|------|------|
| code-review | 审查代码正确性，调用 /code-review |
| test-driven-development | 测试驱动开发流程，调用 /t.d.d |
| systematic-debugging | 系统调试技能，调用 /systematic-debugging |
| ui-ux-pro-max | 前端UI设计使用该技能 调用 /ui-ux-pro-max |
| svn-commit | 提交 SVN（仓库 svn://10.10.10.20/myrepo/code/apps/myrag/health-monitor，先 update 检冲突、中文说明走 -F + --encoding UTF-8），用户说「提交svn」时用 |
| deploy | 部署到 Ubuntu 服务器 10.10.10.88:8020（同步代码并重启，无向量模型目录），用户说「部署/更新服务器」时用 |
| remotion-best-practices | Remotion 视频创作总入口（路由到 create/markup/maps/multimedia/render/studio/captions/saas 等子技能），用户说「做视频/动画」时用 |
| remotion-docs | 搜索并读取 Remotion 官方文档（Algolia + .md 源码），查 API 用 |
| remotion-interactivity | Remotion Studio 交互式编辑最佳实践（点击/拖拽/关键帧可编辑的标记写法） |
| remotion-upgrade | 升级 Remotion 及 @remotion/* 配套包，用户说「升级 remotion」时用 |
| remotion 简介 | 见 docs/reference/remotion-skills.md（复制自 english 项目，与体检业务无关） |

项目技能目录 .claude/skills/（随项目入库）；通用技能（brainstorming、tailwind 等）在用户级
~/.claude/skills/，不进本仓库。提交 SVN 时跳过 data/（运行数据）、health-env/、__pycache__/，`.env` 含真实密钥默认不提交。