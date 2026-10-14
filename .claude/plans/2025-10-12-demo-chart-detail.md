# Demo 页面增强：异常概览环形图 + 详情面板扩展

## 背景与目标
1. 异常概览目前只有 4 个数字卡片，信息表现单调 → 加入 **SVG 轻量环形图**（严重程度占比），图例可点击聚焦 3D 部位。
2. 右侧详情面板仅 268px，检查记录线性堆叠，10+ 次记录后浏览困难 → **加宽右栏 + 记录改为竖向时间轴 + 折叠展开**（默认最近 3 条，可展开全部）。

已确认选型：SVG 自绘环形图（零依赖）；时间轴 + 折叠展开。

## 改动文件
| 文件 | 改动 |
|------|------|
| `index.html` | stats 面板 `<h3>` 与 `.stats-cards` 之间插入环形图容器 `<div class="stats-donut" id="stats-donut">`（SVG 由 JS 生成，HTML 只放容器，遵守规则 11） |
| `css/style.css` | 右栏 268→320px（@1100px 断点 232→280px）；环形图/图例/时间轴/展开按钮样式；stats 面板 min-width 252→300px |
| `js/app.js` | 新增环形图绘制函数；记录改时间轴渲染 + 折叠逻辑；图例点击交互；演示数据补充 1–2 个部位到 5–6 条以验证折叠 |
| `README.md` | 补充新交互说明（可选） |

## 实现细节

### 1. SVG 环形图（严重程度占比）
- 数据源：`ABNORMALITIES` 按 `severity` 分组计数（复用 `updateStats` 的统计）。
- 绘制：`stroke-dasharray` 三段弧拼接成一个环（半径 ~40px、stroke ~12px），颜色用 CSS 变量 `--severe / --moderate / --mild`，弧段之间留 2px 间隙。
- 环中心：大数字显示异常部位总数（与 `stat-total` 一致）。
- 右侧图例：色点 + 等级名 + 数量 + 百分比；图例项 `pointer-events: auto`，点击后调用 `selectConcept(该等级第一个异常部位的 conceptId)` 触发 3D 相机飞行聚焦。
- 面板整体保持 `pointer-events: none`（不干扰 3D 拖拽），仅图例区单独开启点击。

### 2. 详情面板：时间轴 + 折叠
- 右栏宽度：`.layout` 的 `grid-template-columns` 第三列 `268px → 320px`；`@1100px` 断点 `232px → 280px`。
- 检查记录区改为竖向时间轴：
  - 左侧一条连续竖线（`::before`），每条记录顶部一个时间圆点（新增 `.tl-dot` 或调整 `.ab-record::before/::after`）。
  - 每条记录仍含日期、类型、摘要、结论；日期用语义色高亮。
- 折叠逻辑（`js/app.js`）：
  - 常量 `RECORDS_PREVIEW = 3`。
  - `records` 超过 3 条时，第 4 条起加 `record-hidden` class（默认 `display:none`）。
  - 底部渲染「展开全部 N 条记录」按钮；点击后移除 hidden、按钮变「收起」。
- 时间轴区域随 `.panel` 整体滚动，10+ 条无压力。

### 3. 演示数据补充（验证折叠）
- 心脏：3 条 → 5 条（补充 2024-12 血脂复查、2023-12 年度体检，数值与既有趋势一致）。
- 肝脏：2 条 → 4 条（补充 ALT 波动记录）。
- 数据结构不变（`records[]`），未来真实后端数据可直接替换。

## 验证
1. `http-server` 启动后 headless Chrome 截图：确认环形图、图例、时间轴、折叠按钮渲染正常。
2. Console 无 JS 错误；`data-state="ready"`。
3. 点击图例 → 3D 相机聚焦（手动/脚本验证）。
4. 响应式：1100px / 900px 断点下布局正常，右栏不挤压 3D 舞台。