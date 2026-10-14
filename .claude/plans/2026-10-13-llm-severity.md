# 3D 大屏严重度改用 LLM 综合判定（2026-10-13）

> **状态：✅ 已完成（2026-10-13）**。全量测试 33 passed；已重启 8020；当前模型管理启用 u2-flash，LLM 判定实际生效（肾脏=中度、心脏=中度、血液=轻度，均带 AI 理由）；headless Chrome 验证右栏「AI 判定：…」正常渲染。

## 背景与目标
用户反馈：目前「严重/中度/轻度」只按部位**异常指标数量**判定（≥3 严重 / 2 中度 / 1 轻度），
不靠谱——比如「肌酐显著升高」和「甘油三酯轻度偏高」都只算 1 项。希望**借助大模型综合判断**
（指标名称、数值、参考区间、历史记录），LLM 不可用时回退到数量规则。

## 方案总览
- `GET /api/body3d/overview` 返回的每个异常部位 `severity` 优先由 LLM 判定；
- 判定结果带 `severity_reason`（一句话理由），前端右栏展示「AI 判定」；
- 结果按「异常指标指纹」做**进程内缓存**（数据不变不重复调用 LLM）；
- `.env` 未配 `DEEPSEEK_API_KEY` 且未启用自定义模型时，自动回退到现在的数量规则（3D 大屏永远可用）。

## 改动文件
| 文件 | 改动 |
|------|------|
| `app/body3d.py` | 新增 LLM 可用性探测、严重度判定函数、JSON 解析、进程内缓存；`build_body3d_overview` 增加可选 `use_llm` 参数，输出 `severity_reason` |
| `app/main.py` | body3d 路由调用处传 `use_llm=None`（自动探测），其余不变 |
| `static/js/body3d.js` | `overviewToAbnormalities` 透传 `severityReason`；`renderAbnormalDetail` 展示「AI 判定：…」 |
| `static/css/body3d.css` | 新增 `.severity-reason` 样式 |
| `tests/test_body3d.py` | 新增 LLM 判定/失败回退/无效 JSON 回退测试 + 缓存清理 fixture |
| 文档 | `docs/plans/current-sprint.md`、`docs/architecture/architecture.md`、`docs/requirements/requirements.md` 补记该能力 |

## 实现细节

### 1. `app/body3d.py` 新增函数
- `_llm_available(session) -> bool`：`get_settings().llm_api_key` 非空 **或** 模型管理启用了一个 `kind=custom` 模型 → True。
- `_parse_severity(text) -> (severity|None, reason|None)`：先整段 `json.loads`，失败用正则抓 `{...}` 再解析；`severity` 白名单 `severe|moderate|mild`。
- `_judge_part_severity(model, part_name, issues, records_count) -> (severity, reason)`：构造 system+user 两段 prompt，调 `llm.chat_text(model, messages, max_tokens=300, disable_thinking=True)`，返回解析结果。
  - prompt 只列**当前异常指标**（名称/数值/单位/参考区间/状态）+ 历史异常次数，要求只输出 JSON。
- `clear_severity_cache()`：测试隔离用。

### 2. 缓存
- 模块级 `_severity_cache: dict[str, tuple[ts, severity, reason]]`，键 = `模型|部位key|异常指标SHA256指纹`。
- 指纹由异常指标 `(name, value, unit, range, status)` 排序后 JSON 的 SHA256 计算；指标变化自动失效重判。
- TTL 24h；服务重启后缓存清空（首次访问会重新调用 LLM，本数据量下仅 3~5 个部位，可接受）。

### 3. `build_body3d_overview(session, mode, use_llm=None)`
- 组装 `out` 时先按数量规则算出兜底 `severity`，同时收集「异常且 LLM 可用」的部位；
- 若 LLM 可用：先 `model = await llm.resolve_model(session, None)`，再对收集到的部位**并发**（`asyncio.gather`）判定，每部位 `asyncio.wait_for(..., timeout=20)`；
- 命中缓存直接复用；LLM 抛异常/超时/返回非法 JSON → 保留数量兜底，不阻塞大屏。
- 输出对象新增 `severity_reason`（无 LLM 判定时为空字符串），`severity` 字段格式不变（severe/moderate/mild），前端无需改统计逻辑。

### 4. 前端
- `overviewToAbnormalities`：`severityReason: part.severity_reason || ''`。
- `renderAbnormalDetail`：badge 下方加 `<div class="severity-reason">AI 判定：{reason}</div>`（有值才显示）。
- `body3d.css`：`.severity-reason` 浅色小字（复用 `--text-2` / accent 左边框）。

### 5. 测试（tests/test_body3d.py 新增）
- `autouse` fixture 每次清 `_severity_cache`，防止跨测试污染。
- `test_llm_severity_used`：monkeypatch `body3d._llm_available=True`、`app.llm.chat_text` 返回 `{"severity":"severe","reason":"肾功能异常"}`；1 项异常指标 → 预期 severity=severe 且 reason 透出。
- `test_llm_severity_fallback_on_error`：`chat_text` 抛异常 → 回退数量规则（1 项异常 = mild）。
- `test_llm_severity_fallback_on_invalid_json`：`chat_text` 返回非 JSON → 回退 mild。
- 既有 29 条测试不受影响：`.env` 无 key、测试库无自定义模型 → 自动回退数量规则。

## 验收
- 全量测试通过（预计 32 passed）。
- 当前 `.env` 未配 key：`#/body3d` 仍显示数量规则（严重/中度/轻度不变，无 AI 理由）。
- 用户配置 `DEEPSEEK_API_KEY`（或模型管理启用自定义模型）后刷新大屏：异常部位严重度变为 AI 判定，右栏出现「AI 判定：…」；再次切换模式不重复调用（缓存命中）。

## 说明
- LLM 判定为辅助参考，不取代医生诊断；判定失败/不可用始终回退数量规则，保证大屏可用。
- 若后续希望**持久化**判定结果（避免重启后重新调用），可再加 `severity_judgements` 表，本次先用进程内缓存。