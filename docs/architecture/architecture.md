<!--
================================================================
文件: architecture.md
作者: chengge
最后修改: 2026-10-11
================================================================
-->

# 架构文档：健康数据监控（health-monitor）

## 1. 总体分层

```
前端（static/） → 路由层（app/main.py） → 业务层（app/crud.py、app/ocr.py、app/llm.py、app/backup.py） → 数据层（app/db.py + SQLite）
```

- 下层不可依赖上层；路由层只做参数校验/错误映射/编排
- 业务层（crud/ocr/llm/backup）不 import FastAPI 的 Request/Response
- 外部依赖（LLM 网关、OCR 模型）在测试中一律 mock

## 2. 模块依赖图

```
main.py
 ├── auth.py        （登录会话：itsdangerous 签名 cookie）
 ├── config.py      （Settings 环境变量，lru_cache）
 ├── db.py          （engine/SessionLocal/init_db）
 ├── crud.py        （SQLAlchemy 数据访问）
 ├── schemas.py     （Pydantic 模型）
 ├── ocr.py         （RapidOCR 本地识别，线程池调用）
 ├── llm.py         （模型路由注册表 + 端点归一 + 连通测试 + chat_text）
 ├── backup.py      （打包/校验/还原，线程池调用）
 └── models.py      （ORM：Exam/Metric/BodyRecord/ModelSetting，V0.2 加 Analysis）
```

- `ocr.py` 与 `llm.py` 只被路由层（main.py）调用，互不依赖
- `backup.py` 在还原时动态 import `db.py`/`crud.py`/`llm.py` 做引擎重绑
- 前端 `static/js/app.js` 为哈希路由 SPA，只调 `/api/*`

## 3. 数据表结构（data/health.db）

### exams（体检记录）
| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK 自增 | |
| exam_date | VARCHAR(10) 索引 | 体检日期 YYYY-MM-DD |
| hospital | VARCHAR(200) | 医院 |
| source_type | VARCHAR(20) | 默认 image（预留 pdf） |
| note | TEXT | 备注 |
| image_path | VARCHAR(500) | 相对 data/ 的图片路径，如 `uploads/3/report.png` |
| ocr_text | TEXT | RapidOCR 识别原文（AI 提取输入） |
| extracted_json | TEXT | 预留：LLM 结构化提取结果 |
| created_at / updated_at | DATETIME | |

### metrics（指标）
| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK 自增 | |
| exam_id | FK exams.id ON DELETE CASCADE 索引 | |
| name | VARCHAR(100) | 指标名（如 谷丙转氨酶 ALT） |
| value_text | VARCHAR(100) | 数值文本（兼容 `<0.1`、`1.2-3.4`） |
| unit | VARCHAR(50) | 单位 |
| ref_low / ref_high | VARCHAR(50) | 参考下限/上限（文本保留原样） |
| abnormal | INTEGER 0/1 | 异常标记（3D 高亮依据） |
| body_part | VARCHAR(50) | 身体部位（heart/liver/...，自由文本） |
| note | VARCHAR(500) | 备注 |
| sort | INTEGER | 排序 |

### body_records（日常身体数据）
| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK 自增 | |
| record_date | VARCHAR(10) 索引 | 日期 |
| record_type | VARCHAR(20) 索引 | weight/blood_pressure/blood_glucose/... |
| value | FLOAT | 数值 |
| unit | VARCHAR(20) | 单位 |
| note | VARCHAR(500) | 备注 |

### analyses（AI 分析历史，V0.2 新增）
| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK 自增 | |
| range_start / range_end | VARCHAR(10) | 分析时间范围 |
| summary | TEXT | 输入摘要（涉及哪些异常指标） |
| content | TEXT | LLM 生成的健康建议全文 |
| created_at | DATETIME | |

### model_settings（模型管理）
id 自增 PK、name（非唯一，允许同名多厂商）、enabled（互斥）、kind（custom；env 为旧版遗留，不再使用）、
base_url、api_key、protocol（openai|anthropic）、updated_at。

## 4. 关键流程

### 4.1 上传 → OCR → 入库
```
POST /api/exams (multipart: files + exam_date/hospital/note)
  1. 校验数量/大小（≤10 张，≤20MB/张）
  2. run_in_threadpool(ocr.ocr_image_bytes, data)   // RapidOCR，不阻塞事件循环
  3. create_exam（先拿自增 id）→ 图片落盘 data/uploads/{id}/{filename}
  4. 更新 image_path，commit
  5. 返回每条记录状态（created/failed）；单文件失败不影响其他
```

### 4.2 模型路由
```
resolve_model(session, model)
  优先级：请求显式 model > model_settings 启用行（custom → {name}@{id}）> None
resolve_endpoint(model)
  自定义行（有 base_url）→ 该端点 + 可选 Bearer Key；否则抛「未配置自定义模型」
```
- 注册表：`llm._custom_models`（id → {name,base_url,api_key,protocol}）
- 每次管理/问答请求入口用 `crud.custom_models_map(session)` 刷新
- `{name}@{id}` 解析见 `llm._parse_route`

### 4.3 备份还原
```
备份：SQLite backup API 在线快照 health.db + uploads/ 整目录 + manifest.json
    → data/backups/kb_*.tar.gz
还原：解包校验（白名单/防穿越/≤2GB）→ safety 快照 → 新库升级 schema →
    文件换位（旧库改名 restore_<ts>.db 留底）→ 进程内重绑 engine/SessionLocal
    → 重载自定义模型注册表 → 失败逆序回滚
```

### 4.4 AI 提取（V0.2）
```
POST /api/exams/{id}/extract
  1. 取 exam.ocr_text
  2. llm.resolve_model 定模型 → llm.chat_text 发结构化提取 prompt
  3. 解析返回 JSON（校验字段）→ 生成草稿指标（不入库）返回前端
  4. 前端展示草稿 → 用户确认 → POST /api/exams/{id}/metrics 批量入库
```

### 4.5 3D 大屏数据流（V0.3，已实现）
```
GET /api/body3d/overview?mode=abnormal|all
  → app/body3d.py 按 body_part 聚合体检指标：
      - 「最近一次状态」口径：按 (部位, 指标名) 分组，每组只取最近一次体检的
        数值判定当前正常/异常；历史异常已恢复正常（吃药治好）不再标红，
        records[] 时间线仍保留全部历史异常记录便于回顾
      - 异常部位：issues[]（名称/数值/单位/参考区间/状态）、records[]（按日期倒序）、
        severity + severity_reason（LLM 严重度判定，见下）、note（自动建议）
      - severity 判定：默认由大模型判断（app/body3d.py `_judge_part_severity`），
        把部位、异常指标列表、历史异常次数发给 LLM 返回 {"severity","reason"}；
        进程内指纹缓存（SHA256 of issues，TTL 24h）；三级失败回退：LLM 抛异常 /
        返回非 JSON / 返回非法 severity → 回退数量规则（异常条数 ≥3 严重 / 2 中度 / 1 轻度）
      - _status 支持单侧参考区间（<5.2 存 ref_low / >1.0 存 ref_high）与定性结果，
        避免「颜色 淡黄色」这类定性正常项被误标异常
      - body_part → atlas conceptIds 映射（app/body3d.py BODY_PART_MAP，20 个部位）：
        肾脏→FMA7205/FMA7204、肝脏→FMA7197、心脏→FMA7088、胰腺→FMA7198、
        肺/胃/脾/脑/气管/主动脉/食管/胆囊/肾上腺/膀胱/前列腺/睾丸/颅骨→对应 FMA，
        血液/全身→ALL（全身高亮）、骨骼→SKELETAL（骨骼系统）
      - mode=all 返回全部 20 个部位（暂无数据部位 abnormal=false，前端标灰「暂无数据」）
  → static/js/body3d.js（复刻 demo-anatomy 渲染器，demo-anatomy/ 目录原样保留）
      加载 /demo-anatomy/models/atlas.json + body-*.bin.gz
      异常部位脉冲高亮 + 头顶标注 Sprite + 左栏部位清单 + 右栏详情 + 统计环图
      「仅异常 / 全部部位」切换重新拉取；支持 ?mode=all 深链；#/body3d 以全宽 iframe 嵌入 SPA
  → 右栏指标状态着色：正常绿、偏高红（↑）、偏低蓝（↓）、异常红（body3d.css .flag.status-*）
```

## 5. 安全设计
- 写操作中间件校验 Origin/Host 一致性，防 CSRF / DNS rebinding
- 登录会话 HttpOnly + SameSite=Lax；口令时序安全比较
- API Key 只进本地 SQLite（模型设置页录入），任何响应不回显（has_key 布尔）
- 上传文件名清洗（防路径穿越）；备份文件名白名单正则
- 前端 HTML 纯标记，禁内联 JS/CSS/on*（静态守卫测试强制）