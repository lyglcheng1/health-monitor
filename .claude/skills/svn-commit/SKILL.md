---
name: svn-commit
description: 自动 SVN 提交健康数据监控（health-monitor）项目：先 update，检测冲突（有冲突则停止并提示），无冲突则把本地改动 commit 到 svn://10.10.10.20/myrepo/code/apps/myrag/health-monitor。当用户说"提交svn"、"commit代码"、"提交代码"、"svn提交"时使用。
---

# SVN 自动提交

把 `E:\nasvpn\health-monitor` 的本地改动提交到内网 SVN。先 update 再 commit，冲突必须人工介入。

| 项 | 值 |
|---|---|
| 仓库地址 | `svn://10.10.10.20/myrepo/code/apps/myrag/health-monitor` |
| 工作副本 | `E:\nasvpn\health-monitor`（注意：父目录 `E:\nasvpn` 也是工作副本，里面还有其他项目——**永远只在 health-monitor 目录内操作，不要 cd 到 E:\nasvpn 提交**） |
| 账号 | `liucheng`（凭据已缓存在 `~/.subversion/auth`，命令一律加 `--non-interactive`） |
| 密码 | **禁止**把密码写进任何命令参数（`--password` 一律不用）；凭据失效时让用户本人跑一次 `svn ls svn://10.10.10.20/myrepo --username liucheng` 交互输入 |

## 提交流程（每次按顺序执行）

### 1. update 并检测冲突

```bash
cd "e:/nasvpn/health-monitor"
svn update --non-interactive --accept postpone
svn status | grep -E "^C|^.C|tree conflict|incoming" || echo "NO_CONFLICTS"
```

- 输出 `NO_CONFLICTS` → 继续第 2 步。
- 有任何冲突行（`C` 状态或 tree conflict / incoming）→ **立即停止，不要 commit**。向用户报告：
  - 冲突文件清单（`svn status | grep "^C"`）
  - 每个冲突可选项：`svn resolve --accept working <文件>`（保留本地）/ `--accept theirs-full <文件>`（用仓库版）/ `--accept mine-full <文件>`（用本地版）
  - 等用户解决完（或明确授权代解决某个文件）后再重新走流程

### 2. 检查待提交内容 + 添加新文件

```bash
svn status
```

- `?` 未版本化的**新代码/文档/脚本** → `svn add <路径>`（自动纳入，如新增模块、tests、docs、static 下的文件、.claude/skills 之类）
- 例外 **不要 add、也不要一并 commit**：`data/` 运行期产物（health.db / health.db-wal / uploads/ / backups/ / logs/）、`health-env/` 虚拟环境、`__pycache__/`、`*.tmp`、临时脚本；拿不准的先问用户
- `M` 修改、`D` 删除正常随 commit 提交
- **`.env`**：含真实密钥（AUTH_PASSWORD 等），默认**不主动 add、不提交**；若已被仓库跟踪且本次有改动，先向用户说明再决定是否提交
- **`.env.example`**：默认入库，正常提交

### 3. 生成提交说明

看 `svn status` + `svn diff --summarize`，按项目规范格式写中文说明：

```text
<type>(<scope>): <一句话主题>

- 改动要点 1
- 改动要点 2
```

type 取 feat / fix / docs / refactor / test / chore。scope 可用项目阶段（V0.1/V0.2…）或模块（static/app.js、app/main.py、tests…）。多件事时主题写概括，要点分条。

### 4. 提交

```bash
svn commit --non-interactive --encoding UTF-8 -F "$TEMP/svn-msg.txt" <路径列表>
```

- 提交说明含换行时用 `-F <临时文件>`，**必须同时加 `--encoding UTF-8`**：
  Windows 下 svn 默认按系统 locale（GBK）解读 -F 文件再转 UTF-8 存储，中文 UTF-8 文件
  会被双重编码——仓库里存的 svn:log 直接乱码（r26~r30 已踩坑）。
  `-m` 直传中文同样会乱码，多行/中文说明一律走 `-F + --encoding UTF-8`
- **临时说明文件写到工作副本之外**（如 `"$TEMP/svn-msg.txt"`），别放仓库根目录：
  r78 曾把 `.svn-commit-msg.tmp` 顺带 add 进版本库（r81 才删掉），且提交时报
  `E205004: Log message file is a versioned file` 直接拒绝。
- 提交后自检（防再次静默乱码）：`svn log -r <N> --xml | grep -c "锛\|鍒\|鐨"` 应为 0
- 本 skill 的 svn 命令已在 `.claude/settings.json` 加白名单（status/diff/info/update/add/resolve/commit），无需人工审批

成功后输出含 `Committed revision N.`，向用户报告 revision 号与本次提交的文件清单。

## 提交授权（2026-09-19 更新）

⚠️ **只在用户明确发话时才提交**（「提交 svn」「commit 代码」「提交一下」等，或直接调用本 skill）。
完成代码/测试后**不要**自动进入提交流程——等用户的命令。写完代码就把「待提交内容」
列出来让用户过目即可，不要自作主张 commit。

一旦用户发话：自动 update + 检测 + 提交，提交流程内不需要再逐项审核；唯一中断条件是
第 1 步发现冲突。`.env` 等已跟踪文件的改动按上述约定处理。

## 提交前测试门禁

- `app/` 或 `tests/` 有实质改动 → 先跑 `AUTH_PASSWORD= health-env/Scripts/python.exe -m pytest -q`（必须带 `AUTH_PASSWORD=` 前缀置空登录，否则 .env 开启登录会让 API 测试全部 401；当前基线：**34 passed**，2026-10-13 跑通；`pytest.ini` 已配 `asyncio_mode = auto`），不过则停止并报告失败
- `static/` 前端改动 → 先跑 `node --check static/js/app.js`；改 index.html 则确认 test_static_routes 过（内联规则守卫）
- 仅文档（docs/、*.md）、配置或 skill 文件改动 → 可跳过

## 禁止事项

- 禁止 `svn revert` 用户已有的本地修改；禁止 `--force`
- 禁止在 E:\nasvpn 父目录执行 add/commit/update（会带上父目录其他项目的文件）
- 禁止带冲突提交（SVN 本身也会拒绝，但流程上必须先停）
- 禁止把 `--password` 写进命令行