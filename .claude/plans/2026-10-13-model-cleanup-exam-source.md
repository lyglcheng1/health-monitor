# 模型设置去内置化 + 体检记录增加来源字段（2026-10-13）

## 任务 1：模型设置界面去掉内置模型（.env 清单），只保留自定义模型；去掉 .env 模型参数及相关文档

### 1.1 后端
| 文件 | 改动 |
|------|------|
| `app/config.py` | 删除 `llm_api_key` / `llm_base_url` / `llm_model` / `available_models`（.env 内置模型配置）；**保留** `llm_timeout`（DEEPSEEK_TIMEOUT，通用超时）；文件头去掉「从 myrag 精简」 |
| `app/llm.py` | 删除 `available_models()`；`all_models()` 只含自定义模型；`resolve_model()` 三级回落改为「显式 model > 启用自定义模型 > None」；`resolve_endpoint()` 无自定义行时抛「未配置自定义模型」；文件头去掉 myrag |
| `app/main.py` | `GET /api/models`、`GET /api/models/admin` 只返回自定义模型（`default` 为当前启用自定义或空）；`_validate_model_name` 只认自定义模型（去掉 .env 清单分支）；enable/disable 去掉 .env 分支 |
| `app/body3d.py` | `_llm_available()` 去掉 `get_settings().llm_api_key` 判断（只认「启用了 kind=custom 且有 base_url」）；移除 `get_settings` 导入 |

### 1.2 前端
- `static/js/app.js` `renderSettings`：删除「内置模型（.env 清单）」整块卡片；「默认模型」区在无启用模型时提示「未配置（请添加并启用自定义模型）」；只保留自定义模型表格 + 添加表单。

### 1.3 测试
- `tests/test_models.py`：`test_models_list_has_env` → 改为 `test_models_list_custom_only`（无自定义时列表可为空，添加后出现）；`test_model_test_mocked` 先添加自定义模型再测 `{name}@{id}/test`。
- `tests/test_body3d.py` `test_llm_severity_used`：先通过 API 添加并启用自定义模型，断言 `chat_text` 收到的 model 为 `{name}@{id}`（不再断言 `deepseek-v4-flash`）。

### 1.4 文档清理（只保留 health-monitor 内容，去掉 myrag / .env 模型参数）
- `.env.example`：删除 `DEEPSEEK_API_KEY/BASE_URL/MODEL/AVAILABLE_MODELS`，保留超时/认证/存储。
- `README.md`、`docs/handover.md`、`docs/architecture/architecture.md`（含 §6「与 myrag 的复用与裁剪」）、`docs/requirements/requirements.md`、`docs/plans/current-sprint.md`、`docs/testing/test-plan.md`、`docs/reference/error-codes.md`（含「与 myrag 的差异」）、`docs/reference/code-walkthrough.md`：
  - LLM 描述改为「页面自定义模型（OpenAI 兼容/Anthropic 端点）」，删除 `.env 默认模型/网关/Key` 表述；
  - 删除「同 myrag」「从 myrag 精简」等跨项目对比内容；
  - 部署技能里 `DEEPSEEK_API_KEY` 与 myrag 同机描述同步清理（SVN 仓库路径等真实地址保留）。
- `AGENTS.md`：LLM 行改为「模型管理页自定义模型」；SVN 仓库路径（含 myrag 的真实 URL）保留。

## 任务 2：体检记录增加「来源/附件名称」字段

> 用户原话：增加一个字段（附件名称），知道是哪个文件里的数据，如「连云港第一人民医院20260930检查.pdf 第6/6页（检验报告单）」。

### 2.1 数据模型与迁移
- `app/models.py` `Exam` 增加 `source: Mapped[str] = mapped_column(String(500), nullable=False, default="")`。
- `app/db.py` `init_db`：幂等补列 `ALTER TABLE exams ADD COLUMN source VARCHAR(500) NOT NULL DEFAULT ''`；一次性回填 `UPDATE exams SET source = substr(note, 4) WHERE source = '' AND note LIKE '来源：%'`（去掉「来源：」前缀，得到「连云港第一人民医院20260930检查.pdf 第6/6页（检验报告单）」）。
- 存量库由服务重启后的 `init_db` 自动完成迁移。

### 2.2 后端
- `app/schemas.py`：`ExamOut` / `ExamDetailOut` / `ExamUpdate` 增加 `source`。
- `app/crud.py`：`create_exam` 增加 `source=""` 参数；`list_exams` 输出 `source`；`update_exam` 支持改 `source`。
- `app/main.py`：
  - `POST /api/exams`：`source = 原始文件名`（用户上传图片时用文件名标识来源）；
  - `GET /api/exams/{id}` 输出 `source`；`PUT /api/exams/{id}` 接受并保存 `source`。
- `scripts/ingest_pdfs.py`：入库时写 `source = f"{doc}.pdf 第{i}/{len(pages)}页（{ptype}）"`（note 保留原样，兼容历史）。

- [ ] `source` 与 `note` 同时保留：note 不再承担「来源」职责（历史数据 note 不变）。

### 2.3 前端
- `static/js/app.js`：
  - `examListItem`：显示 `source`（附件名）作为副标题（替代/补充 hospital）；
  - `renderExam`：详情表单新增「来源/附件」输入框，随保存信息一起提交。

### 2.4 测试
- `tests/test_exams.py`：上传后断言 `source` 等于文件名；列表/详情含 `source`；PUT 可修改 `source`。
- `test_body3d.py` 现有用例不受影响（上传仍走 `/api/exams`，source 默认为文件名）。

## 验收
1. 全量测试通过（预计 34+ passed）。
2. 模型设置页只剩「自定义模型」；`/api/models/admin` 不再返回 `custom=false` 条目。
3. `.env` 中 DEEPSEEK_* 模型参数不再被读取；无自定义模型时 LLM 严重度自动回退数量规则。
4. 体检列表/详情显示「来源」字段；存量 29 条记录自动回填为「XX.pdf 第N/N页（类型）」。
5. 服务重启后 `/api/exams` 返回 `source` 且非空。

## 说明
- 不破坏现有 `u2-flash` 自定义模型：它本来就是 custom，任务 1 后依然是唯一模型来源。
- `DEEPSEEK_TIMEOUT` 保留为通用 LLM 超时（`llm_timeout`）。
- SVN/部署技能里的真实仓库路径（含 myrag 的 URL）与服务器地址是硬事实，仅清理解释性文字。