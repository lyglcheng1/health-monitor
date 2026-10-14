<!--
================================================================
文件: test-plan.md
作者: chengge
最后修改: 2026-10-11
================================================================
-->

# 测试计划：健康数据监控（health-monitor）

## 测试策略
1. **外部依赖一律 mock**：LLM（连通测试/协议探测/后续提取分析）、OCR 全部 mock，
   禁止在测试中发真实请求 / 跑真实推理（AGENTS.md 规则 5 同款）。
2. 每个测试用独立临时 SQLite 文件（`tests/conftest.py` 的 `engine` fixture）。
3. 登录开关通过环境变量钉死（`AUTH_PASSWORD=`），需要登录的用例用 monkeypatch 构造 Settings。
4. 前端守卫：静态路由 200 + HTML 无内联 JS/CSS/on* + `node --check` 校验 app.js。
5. 上传图片用极小的 1x1 PNG 字节，OCR 被 mock，不落真实 data/。

## 测试用例清单

### 认证（test_auth.py）
| 编号 | 用例 | 断言 |
|------|------|------|
| T-101 | 开启登录后未登录访问 /api/exams | 401 + code=1001 |
| T-102 | 开启登录后访问 / | 302 → /login |
| T-103 | 登录错误密码 | 401 + 统一文案 |
| T-104 | 登录正确 | 200 + hm_session cookie |
| T-105 | 退出登录后再访问 | 401 |

### 体检记录（test_exams.py）
| 编号 | 用例 | 断言 |
|------|------|------|
| T-201 | 上传图片（mock OCR）→ 列表 | 201 + ocr_text 正确 + 列表 1 条 |
| T-202 | 空文件上传 | 400 + code=1002 |
| T-203 | 详情/图片预览/指标数 | 200 + 图片字节非空 |
| T-204 | 指标增删改 | 201 → 200 → metric_count 变化 |
| T-205 | 体检信息编辑 | 日期/医院/备注生效 |
| T-206 | 删除体检记录 | 200 → 详情 404 |
| T-207 | 不存在的体检/指标 | 404 + code=2004 |
| T-208 | 日常身体数据增删查 | 201 → 列表 → 删除后空 |
| T-209 | 来源/附件字段 | 上传 source=文件名 → 列表/详情含 source → PUT 可修改 |

### 模型管理（test_models.py）
| 编号 | 用例 | 断言 |
|------|------|------|
| T-301 | 模型清单只含自定义模型 | 未添加时 200 + 空列表；添加后仅自定义行 |
| T-302 | 自定义模型增改删 | 201（has_key）→ PUT 改 Key/端点 → 启用/停用 → 删除 |
| T-303 | 同名同端点重复添加 | 400 + code=1006 |
| T-304 | 删除不存在的自定义模型 | 404 + code=2004 |
| T-305 | 连通测试（mock llm.test_model） | 200 + ok=true |
| T-306 | 协议探测（mock detect_protocols） | 200 + ok=true |
| T-307 | 非法 API 地址探测 | 400 + code=1006 |

### 前端守卫（test_static_routes.py）
| 编号 | 用例 | 断言 |
|------|------|------|
| T-401 | /static/css/style.css | 200 + text/css |
| T-402 | /static/js/app.js | 200 + javascript |
| T-403 | / 返回 index.html | 200 + text/html |
| T-404 | index.html 无内联 JS/CSS/on*/style= | 正则守卫通过 |
| T-405 | node --check app.js | 语法通过 |

## 补充测试（V0.2/V0.3）
- T-501（V0.2）：AI 提取接口（mock LLM）：生成草稿指标 → 确认入库 → 与手工录入一致
- T-502（V0.2）：AI 提取无 LLM 配置时返回友好错误
- T-503（V0.2）：AI 分析接口（mock LLM）：生成建议 → 入库 → 历史列表可回看
- T-504（V0.3）：异常聚合接口：abnormal/all 两种模式、时间过滤、体重→whole_body / 血压→heart 映射正确
- T-505（V0.3）：备份还原真实演练（临时 data 目录注入）

## 运行方式
```bash
# 项目根目录
AUTH_PASSWORD= health-env\Scripts\python.exe -m pytest -v
```