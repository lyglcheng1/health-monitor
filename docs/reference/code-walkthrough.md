<!--
================================================================
文件: code-walkthrough.md
作者: chengge
最后修改: 2026-10-11
================================================================
-->

# 代码链路导读：健康数据监控（health-monitor）

按「我要做什么 → 代码去哪看」组织，新手先读。

## 1. 我打开首页看到什么
```
GET /  → static/index.html（纯标记，无内联 JS/CSS）
static/js/app.js：
  init() → loadSiteInfo()（GET /api/site-info）
  auth_enabled ? showLoginView() : showMainView()
  route() 按 location.hash 分发：仪表盘/体检/身体/设置/备份
```

## 2. 我上传一张体检化验单
```
页面：#/ 仪表盘「上传体检图片」（bindUploadForm）
POST /api/exams（multipart）
app/main.py api_create_exams：
  1) 校验数量/大小
  2) run_in_threadpool(app.ocr.ocr_image_bytes, data)  ← RapidOCR 本地识别
  3) crud.create_exam(...) 先拿自增 id
  4) 图片落盘 data/uploads/{id}/{filename}，回填 image_path
页面：结果列表 → 点「查看详情」进 #/exam/{id}
```

## 3. 我查看体检详情 / 手工录入指标
```
GET /api/exams/{id} → ExamDetailOut（基本信息 + ocr_text + metrics）
GET /api/exams/{id}/image → FileResponse 图片原件
POST /api/exams/{id}/metrics  / PUT /api/metrics/{id}  / DELETE
app/main.py：api_add_metric / api_update_metric / api_delete_metric
app/crud.py：add_metric/update_metric/delete_metric
数据库：metrics 表（abnormal 标记异常，body_part 供 3D 标注）
```

## 4. 我配置 LLM（后续 AI 提取要用）
```
页面：#/settings（renderSettings）→ GET /api/models/admin
添加自定义模型：
POST /api/models/custom/detect → llm.detect_protocols（探测 openai/anthropic）
POST /api/models/custom → llm._endpoint_for_protocol 归一化端点 → crud.add_custom_model
启用：POST /api/models/{name}@{id}/enable → crud.set_custom_model_enabled（互斥）
调用时：llm.resolve_model(session, model) 回落链（显式 > 启用的自定义模型 > None）
        llm.resolve_endpoint(model) 自定义行（有 base_url）→ 该端点 + Bearer Key；否则抛「未配置自定义模型」
        llm.chat_text(model, messages) 发对话（V0.2 AI 提取复用它）
```

## 5. 我备份 / 还原
```
页面：#/backup（renderBackup）
POST /api/backup → backup.create_backup：
  SQLite backup API 在线快照 health.db + uploads/ 目录 + manifest.json → tar.gz
POST /api/backup/restore → backup.restore_backup：
  解包校验 → safety 快照 → 新库升级 schema → 文件换位 → 重绑 engine → 回滚保护
注意：还原端点会先 dispose 当前引擎池（释放文件句柄）再进线程池
页面操作后调用 /api/backup/restart → 后台跑 manage.sh restart 重启进程
```

## 6. 我想加一个新 API（示例：AI 提取）
```
1. schemas.py 加请求/响应模型（如 ExtractRequest 只有 exam_id）
2. 新建 app/extractor.py：ocr_text → LLM 结构化 JSON（用 llm.resolve_model + llm.chat_text）
3. crud.py 加批量写入草稿/确认入库的方法
4. main.py 加 @app.post("/api/exams/{exam_id}/extract")，异常按 error-codes.md 映射
5. tests/ 加集成测试（mock llm.chat_text，规则：外部依赖一律 mock）
6. 前端 app.js 加「AI 提取」按钮与确认弹层（HTML 仍保持无内联 JS）
```

## 关键文件速查
| 想找 | 文件 |
|------|------|
| 全部路由与中间件 | app/main.py |
| SQL 操作 | app/crud.py |
| 表结构 | app/models.py |
| 入参/出参模型 | app/schemas.py |
| OCR | app/ocr.py |
| LLM 模型路由 | app/llm.py |
| 备份还原 | app/backup.py |
| 登录 | app/auth.py |
| 配置项 | app/config.py（.env：存储/上传/登录/LLM 超时；模型不走 .env） |
| 前端逻辑 | static/js/app.js |
| 前端样式 | static/css/style.css |
| 测试 | tests/ |