<!--
================================================================
文件: remotion-skills.md
说明: 从 english 项目复制的 Remotion 视频创作技能简介
================================================================
-->

# Remotion 技能包（remotion× skills）简介

> 来源：`E:\nasvpn\english\.claude\skills`（2026-10-13 复制）。
> 这些是 **Remotion（React 视频编程框架）** 的官方技能，用于「用代码生成/剪辑视频」。
> 与 health-monitor 现有业务（体检数据管理）无关，属通用创作能力，**仅在用户要求做视频 / 动画 / 大片时才会用到**，不会自动触发。

## 复制到本项目的目录

```
.claude/skills/
├── remotion-best-practices/   ← 入口路由（总技能）
├── remotion-docs/             ← 查 Remotion 官方文档
├── remotion-interactivity/    ← Studio 交互式编辑最佳实践
└── remotion-upgrade/          ← 升级 Remotion 及配套包
```

## 各技能说明

| 技能 | 作用 | 典型场景 |
|------|------|---------|
| `remotion-best-practices` | **总入口**：根据用户意图路由到下面 11 个子技能（remotion-create / remotion-markup / remotion-maps / remotion-multimedia / remotion-render / remotion-studio / remotion-captions / remotion-saas / remotion-docs / remotion-interactivity / remotion-upgrade） | 用户说「做一个视频 / 新建 composition」时先加载它 |
| `remotion-docs` | 通过 Algolia 搜索并抓取 Remotion 官方文档（`xxx.md` 源码格式） | 需要查某个 API 的正确用法 |
| `remotion-interactivity` | 指导如何写 Remotion 标记，让 Studio 里能直接点击/拖拽/编辑关键帧与样式 | 做可交互编辑的视频模板 |
| `remotion-upgrade` | 升级 `remotion` 与 `@remotion/*` 依赖、配套包（zod/mediabunny 等）及已安装的 Remotion 技能 | 版本落后时一键升级 |

`remotion-best-practices` 目录内还包含完整子技能（`remotion-create`、`remotion-maps`、`remotion-markup`、`remotion-multimedia`、`remotion-render`、`remotion-studio`、`remotion-captions`、`remotion-saas` 等），它们由总技能按需加载，不需要单独手动调用。

## 怎么用

1. 直接对 Claude 说需求即可，例如：
   - 「用 Remotion 做一个 xxx 宣传视频」
   - 「把体检趋势做成一个视频」
   - 「查一下 Remotion 的字幕 API」
   - 「升级 Remotion」
2. 也可以主动调用技能：`/remotion-docs`、`/remotion-upgrade` 等（斜杠命令按技能名匹配）。
3. 这些技能**不会影响** health-monitor 的测试、启动与既有开发流程；提交 SVN 时正常纳入 `.claude/skills/` 即可。

## 注意

- 技能来自 Remotion 官方（版本 4.0.5xx），含 `agents/`、`assets/` 子目录，请保持原样，不要改动内部结构。
- 若本项目后续不使用，可直接删除 `.claude/skills/remotion-*` 四个目录，不影响任何现有功能。