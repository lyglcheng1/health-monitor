<!--
================================================================
文件: current-sprint.md
作者: chengge
最后修改: 2026-10-11
================================================================
-->

# 当前迭代：健康数据监控（health-monitor）

## 状态
- **V0.1 骨架：代码 + 测试 + 文档全部完成，全量测试 21 passed（2026-10-11）**
- **V0.3 3D 大屏初版：2026-10-12 夜间完成，全量测试 25 passed；已重启 8020 服务验证通过**
- **V0.3 体验优化（2026-10-13）：按「最近一次体检」判定正常/异常（历史已恢复正常不再标红）、部位清单扩充到 20 个器官、右栏指标状态颜色 + 偏高↑/偏低↓ 箭头；全量测试 29 passed**
- **V0.3 LLM 严重度判定（2026-10-13）：异常部位严重度由大模型判定（命中/失败回退/非法 JSON 回退/进程内缓存），`severity_reason` 展示 AI 判定理由；已启用自定义模型 u2-flash，服务重启验证通过；全量测试 33 passed**
- **模型设置去内置化（2026-10-13）：模型设置页去掉「内置模型（.env 清单）」，只保留自定义模型；代码/文档移除 DEEPSEEK_API_KEY/BASE_URL/MODEL/AVAILABLE_MODELS 等 .env 模型参数；LLM 严重度只依赖自定义模型；跨项目 myrag 内容清理完成**
- **体检记录新增「来源/附件」字段（2026-10-13）：上传时默认取原始文件名，列表/详情展示、可编辑；存量记录从 note「来源：xxx」回填；全量测试 34 passed**
- **Remotion 视频介绍（2026-10-13）：remotion 系列技能复制到 `.claude/skills/` 并写简介文档；`intro-video/` Remotion 项目完成 8 场景介绍视频（标题/项目简介/本地 OCR/LLM 提取/3D 大屏/模型设置/备份还原/结束页）；渲染交付 `intro-video/out/health-monitor-intro.mp4`（1280×720 @30fps，27.5s，H.264，1.86MB），5 个关键帧视觉验证通过**
- 依赖已安装完成（health-env 54 包，含 rapidocr/onnxruntime）
- 已本机启动验证（uvicorn 8020 启动正常，静态/站点信息/3D 大屏接口 200）
- 下一步：人工验收（登录/上传/备份/大屏走查）→ 填验收记录 → 提交 SVN → 部署服务器

## V0.1 骨架（本次迭代）
| 内容 | 状态 |
|------|------|
| 项目脚手架（app/ static/ scripts/ tests/） | ✅ 完成 |
| 登录会话 + 站点信息 | ✅ 完成 |
| 体检图片上传 + 本地 OCR + 列表/详情/图片预览 | ✅ 完成（OCR 待环境验证） |
| OCR 文本编辑、体检信息编辑 | ✅ 完成 |
| 指标手工 CRUD（异常/body_part） | ✅ 完成 |
| 日常身体数据 CRUD | ✅ 完成 |
| 模型管理（页面自定义 + 启停/测试） | ✅ 完成 |
| 备份还原（DB+图片） | ✅ 完成 |
| 集成测试（tests/） | ✅ 完成并跑通（21 passed，含 pytest.ini asyncio_mode=auto 配置） |
| 文档（需求/架构/计划/测试/错误码/导读） | ✅ 完成并评审 |
| 本地启动验证 + 全量测试通过 | ✅ 完成（uvicorn 8020 启动正常；21 passed） |
| 部署 10.10.10.88:8020 | ⏳ 待办（验收通过后） |

## 已确认决策（2026-09-19 用户拍板）
1. AI 提取触发方式：**手动按钮**（详情页点「AI 提取」，不自动调 LLM）
2. 3D 大屏数据范围：**默认只看异常，可切换查看全部指标**
3. AI 分析结果：**保存历史**（新增 `analyses` 表，可回看）
4. 日常身体数据是否参与 3D：**参与**——体重异常标全身、血压异常标心脏
5. GLB 人体模型资源来源：**待 V0.3 启动时确认**

详见 `docs/requirements/requirements.md` §7。

## 下一步计划
1. ✅ 依赖安装完成（2026-10-11）
2. ✅ 跑通全量测试（21 passed；修复 pytest.ini 配置 + 3 处骨架 bug）
3. ✅ 本机启动 `uvicorn app.main:app --port 8020` 基础验证通过（站点信息/首页/静态资源 200）
4. 人工验收：配 `.env` 后验证登录、上传体检图片出 OCR、指标/模型/备份页面走查
5. 填写验收记录 docs/testing/acceptance.md（A-06 已通过，其余人工点验后回填）
6. 提交 SVN（如用户要求）→ `bash scripts/deploy.sh` 部署服务器

## V0.2（AI 提取 + 趋势分析 + 历史保存）任务拆分（V0.1 验收后启动）
- [ ] `app/extractor.py`：把 ocr_text → LLM 结构化指标 JSON（prompt + JSON 校验）
- [ ] `POST /api/exams/{id}/extract`：生成草稿指标（不入库），前端确认后批量入库
- [ ] `analyses` 表 + `POST /api/analyze`：按时间范围聚合异常 → LLM 生成健康建议 → 入库
- [ ] `GET /api/analyze/history`：历史分析列表回看
- [ ] ECharts 引入 `static/vendor/`，体检详情/大屏加趋势折线
- [ ] 相关集成测试（LLM 一律 mock）

## V0.3（3D 人体大屏）任务拆分（2026-10-12 夜间初版；10-13 体验优化）
- [x] 选定人体模型资源：复用本地 `demo-anatomy/`（BodyParts3D 4.0 + ashemag/human-atlas 网格，CC BY 4.0 / MIT），demo 目录保持原样不动
- [x] `static/js/body3d.js` + `static/body3d.html`（importmap 指向 demo-anatomy/vendor 的 three.module.min.js）
- [x] `GET /api/body3d/overview` 聚合接口（abnormal|all 模式；`app/body3d.py`：body_part → conceptIds，血液/全身=ALL，骨骼=SKELETAL）
- [x] 大屏页面 `#/body3d`（全宽 iframe）+ 左栏部位清单 + 右栏详情 + 全部/异常切换 + 异常统计环图
- [x] 修复前端路由 bug（`#/exam/` ↔ `#/exams/`），体检详情支持指标行内编辑
- [x] 新增 `tests/test_body3d.py`（初版 4 条）
- [x] **按最近一次体检判定正常/异常**：每个（部位, 指标名）只取最近一次数值；历史异常已恢复正常（吃药治好）不再标红，记录时间线仍保留便于回顾（新增测试 `test_body3d_latest_state_cured`）
- [x] **部位清单扩充到 20 个器官**：BODY_PART_MAP 增加 脑/气管/主动脉/食管/胆囊/肾上腺/膀胱/前列腺/睾丸/颅骨，全部模式显示全部部位（暂无数据部位标灰「暂无数据」）；支持 `?mode=all` 深链（新增测试 `test_body3d_all_mode_contains_empty_parts`）
- [x] **右栏指标状态颜色 + 箭头**：正常绿色、偏高红色（↑）、偏低蓝色（↓）、异常红色；`static/css/body3d.css` 新增 status-* 类
- [x] 优化 `_status`：支持参考区间单侧写法（`<5.2` 存 ref_low / `>1.0` 存 ref_high）与定性结果（不把「颜色 淡黄色」误标异常）
- [x] **LLM 严重度判定**：异常部位严重度由大模型判断（不再只按异常数量），`app/body3d.py` 实现 `_judge_part_severity` + 指纹缓存（TTL 24h）+ 三级失败回退（异常/非法 JSON → 数量规则），前端展示「AI 判定：…」理由；未配置/启用自定义模型或模型不可用时自动回退数量规则
- [x] **测试**：`tests/test_body3d.py` 新增 LLM 严重度 4 条（AI 命中覆盖数量兜底/调用异常回退/非法 JSON 回退/缓存复用）
- [x] 全量 **33 passed**（2026-10-13，含上述新增测试）
- [ ] 待办：日常身体数据（体重/血压）参与 3D 映射（体重→全身、血压→心脏）；ECharts 趋势折线