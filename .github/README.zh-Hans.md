# topomark

**你的智能体为了找一个函数读了两千行的文件。给它一张地图吧。**

topomark 是给 AI 编程智能体用的零依赖 code map：分层的文档告诉智能体该看哪里，摘要过期时审阅戳记会让 CI 失败，
再加上按符号、影响范围和测试的快速导航，适用于任何 git 仓库。只用 Python 3.11 及以上版本的标准库；完全离线；
对你的代码只读。

![license: MIT](https://img.shields.io/badge/license-MIT-blue)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

[English](../README.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md)

## 让你的智能体帮你安装

在你的仓库里，把下面这段粘贴给 Claude Code、Codex 或任何有终端的编程智能体：

```text
安装 topomark（https://github.com/tipoLi5890/topomark），一个零依赖的 code map 与导航 CLI，
并把这个仓库配置好来使用它：

1. clone 下来：git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
   （如果这个目录已经存在，改为运行 git -C ~/tools/topomark pull）。
2. 加入 PATH：ln -sf ~/tools/topomark/bin/topomark ~/.local/bin/topomark，并确认 ~/.local/bin
   在 PATH 里。用 topomark --version 确认（需要 Python 3.11 及以上版本和 git）。
3. 在这个仓库里运行 topomark doctor，报告它发现的任何问题。
4. 读 ~/tools/topomark/skills/topomark/SKILL.md，此后按它的做法工作。
5. 把下面这一行加入 AGENTS.md；如果这个仓库用的是 CLAUDE.md，就加入 CLAUDE.md：
   "Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
   `topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before
   an edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and
   keep `topomark check` green."
6. 运行 topomark init --dry-run，给我看建议的区域。在我同意之前什么都不要写；
   同意后再运行 topomark init，并对每个区域运行 topomark draft <area> --write，把每一行填好。
```

在建立 code map 之前，`topomark map --tokens 2000` 和其他导航命令就已经能用了；第 6 步让 `check` 和审阅戳记成为可能。

## 30 秒试用

导航不需要安装步骤、配置文件，也不用先建索引。clone 下来，然后对任何 git 仓库使用：

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
cd your-repo
~/tools/topomark/bin/topomark map --tokens 2000      # 在 token 预算内按重要性排序的仓库地图
```

什么都不会安装，也不会写入你的仓库。

## 为什么选 topomark

### 一架梯子，而不是一堆干草

智能体有很多 context 花在为了找一个函数而读整个文件上。topomark 给它一级一级的梯子，每一级都小到可以完整读完：

```text
L0  docs/codemap/README.md     一份索引：仓库分成哪些区域，各自负责什么
L1  docs/codemap/<area>.md     每个文件一行：做什么、有多少文件依赖它、
                               改了要更新什么
L2  按符号读代码               topomark outline / symbol / refs：一个函数，而不是整个文件
```

### 审阅戳记，而不是时间戳

手写的地图会悄悄过期。所以 topomark 为每个文件记下那一行被审阅时它的*接口*哈希（文件头注释、公开签名、常量）。

- 改了接口却没有重新审阅那一行：`topomark check` 失败。
- 只改函数体：不会打扰你。

「最后更新日期」分不清这两种情况，戳记分得清。所以地图要么是最新的，要么 CI 会明确指出哪几行不是。

### 真正的零依赖

不用 tree-sitter，不用语言服务器，不联网。一次 `git clone` 加上 Python 3.11 解释器就能运行，
在 CI、pre-commit hook 和智能体的沙箱里行为都一样。

### 快到每一步都能运行

在 3,000 个文件的合成仓库上、缓存已建立时，`outline` 和 `symbol` 约用 0.05 秒 CPU 时间，
`map`、`search`、`impact` 和 `brief` 在 0.16 到 0.28 秒之间（在一台 Apple silicon 笔记本上；
表格与测量方法见 [docs/pilots.md](../docs/pilots.md)）。

### 只链接，不重写

`init` 会找出仓库已有的规则文件（CLAUDE.md、AGENTS.md、ARCHITECTURE.md、REPO_MAP.md 等），
链接过去，而不是把内容复制一份。

## 安装

以下任一种方式都可以：

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
~/tools/topomark/bin/topomark --version     # 能自己定位的启动器，不需要安装步骤
```

把 `~/tools/topomark/bin` 加入 `PATH`（例如 `ln -s ~/tools/topomark/bin/topomark ~/.local/bin/topomark`）。
也可以用 pipx 从 PyPI 安装成命令（并非必须安装 pipx；`pip install topomark` 也可以）：

```bash
pipx install topomark
```

`bin/topomark` 会自己找到 Python 3.11 及以上版本的解释器（从 `python3.14` 往下找到 `python3`）。`PATH` 里需要有 `git`。

**作为智能体插件。** 这个仓库本身就是 Claude Code 插件与 marketplace（`.claude-plugin/`），也是 Codex 插件
（`.codex-plugin/`），内含一个技能 [`skills/topomark`](../skills/topomark/SKILL.md)。在 Claude Code 中先运行
`/plugin marketplace add tipoLi5890/topomark`，再运行 `/plugin install topomark@topomark`。插件还带有三个 hook：
会话开始时给出一段简短的 code map 指引，读大文件或第一次读某个区域的文件前给出提示，每次修改文件后检查语法
（见[在智能体中使用](#在智能体中使用)）。

## 快速开始

**导航**（完全不需要配置）：

```bash
topomark map --tokens 2000
topomark outline src/core/router.py --exported-only
topomark symbol src/core/router.py#Router.add
topomark symbol src/core/router.py#Router --skeleton
topomark outline src/core/ --tokens 1200
topomark find Router --exact
topomark search route handler registration
topomark locate "no such file: src/app.py"
topomark locate --trace crash.txt
topomark refs Router --no-tests
topomark impact Router
topomark brief src/core/router.py
topomark tests-for --since main
topomark syntax
topomark changes --staged
```

**建立一份不会过期的 code map**：

```bash
cd your-repo
topomark doctor                 # Python、git、配置文件、被 git 跟踪的机密文件
topomark init --dry-run         # 建议的区域、排除规则和要写的文件；什么都不写
topomark init                   # 写出 topomark.toml 与 code map 骨架
topomark draft backend --write  # 一个区域的行，摘要与扇入已预先填好；之后人工修改
topomark gen                    # 生成扇入表与模块依赖图
topomark stamp --baseline       # 读完每一行之后，只做一次
topomark check                  # 此后每次：地图和代码同步吗？
topomark hook install           # 可选的 pre-commit 检查
```

## 在智能体中使用

内置的技能教智能体这个流程：读 L0，读一份区域文件，`outline`、`symbol`；修改前 `brief`，修改后 `syntax`；运行
`tests-for` 打印的命令；提交前 `changes`；最后 `check`、`diff`、`stamp`。不需要斜杠命令或插件运行环境：每一步都是
shell 命令，所以同一套说明在 Claude Code、Codex 或任何有终端的智能体里都适用。在 `AGENTS.md` 或 `CLAUDE.md`
里加一行就够了（智能体读英文，所以这一行保留原文）：

```text
Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
`topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before an
edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and keep
`topomark check` green.
```

**Claude Code 插件的 hook。** 以插件方式安装时，topomark 还会注册三个 hook（`hooks/hooks.json`），只补充 context，
从不阻止工具调用：

- **SessionStart**（startup、clear、compact）：L0 的路径、每个区域的名称与区域文件、一行导航命令，以及是否已有审阅戳记；
  最多 40 行。没有 code map 时只给一行，建议运行 `topomark map --tokens 2000`。
- **PreToolUse（Read）**：超过 400 行的文件会收到改用 `outline` 与 `symbol --skeleton` 的提示；第一次读某个区域的文件时，
  指出它的区域文件。每个提示每个会话只出现一次；指定行范围的读取不会收到提示。
- **PostToolUse（Edit、Write、MultiEdit）**：对修改过的文件做 `syntax` 检查，只有这次修改让文件无法解析时才报告。

每个 hook 只启动一个短暂的进程（在 3,000 个文件的仓库上约 0.15 到 0.3 秒 CPU 时间）。topomark 只为 Claude Code 提供 hook；
在其他智能体中，技能会要求每次修改文件后运行 `topomark syntax --diff`。详见
[adoption.md](../skills/topomark/reference/adoption.md#claude-code-plugin-hooks)（英文）。

## 命令

**导航**：只读，任何 git 仓库都能用，无需配置。按智能体遇到的顺序排列：先了解环境、找到位置，改之前先看，改完再检查。

| 命令 | 用途 |
|---|---|
| `map` | 在 token 预算内给出按重要性排序的仓库地图，适合还没有 code map 的仓库（`--focus`、`--tokens`、`--area`） |
| `outline <path>..` | 符号及其行号范围、种类、签名、文档摘要；可以一次给多个文件或一个目录，只列顶层并受 token 预算限制（`--exported-only`、`--kinds`、`--depth`、`--tokens`） |
| `symbol <file>#<Name>`／`symbol <Name>` | 打印一个符号的源码（`--signature`；`--skeleton` 只保留声明、省略函数体；`--context N`） |
| `find <Name>` | 按名字查找定义（`--kind`、`--exact`、`--limit`） |
| `search <keywords>` | 按主题查找代码：用 BM25 匹配符号名、签名、文档和路径；匹配到的测试会带出它所使用的代码。请给关键词，不要粘贴整段 issue（`--limit`、`--area`、`--tokens`） |
| `locate "<消息>"`／`locate --trace [FILE]` | 找出错误消息背后的代码（按字面的连续词匹配，所以插入的值不影响匹配），或调用栈背后的代码（Python、Node、Java/Kotlin、C#、Dart、Go、Rust、`path:line`）；代码排在测试前，测试排在文档前（`--regex`、`--limit`） |
| `owner <path>` | 所属区域、单元、扇入和戳记状态 |
| `refs <Name>` | 引用位置，排除注释与字符串；文本输出显示各组数量和前 20 条（`--area`、`--no-tests`、`--limit`） |
| `impact <Name 或文件>` | 修改会波及的调用方、导入它的文件、跨区域使用者、测试和文档（`--top`） |
| `brief <文件或 Name>` | 修改前的一份简报，受 token 预算限制：区域文件里的那一行、outline、耦合最深的调用方、测试及运行它们的命令（`--tokens`） |
| `syntax [paths]` | 改过的文件是否仍能解析：Python、JSON、TOML 精确解析，花括号语言检查括号是否配对（只在 HEAD 版本配对时才检查）；有发现时退出码为 1（`--diff`，默认） |
| `tests-for [paths]` | 覆盖修改文件的测试，没有测试提到它们时经由调用方查找，打印成可以直接运行的命令（`--diff`、`--staged`、`--since REV`、`--depth N`） |
| `changes` | 这次 diff 涉及的符号，是接口（新增、删除、新签名）还是只改函数体；还有谁引用改过的接口、要运行的测试、要重新审阅的 code map 行（`--staged`、`--since REV`、`--top`） |

**Code map**：只写 `topomark.toml` 与 `docs_dir`。

| 命令 | 用途 |
|---|---|
| `init` | 检测技术栈并写出 code map 骨架（`--dry-run`、`--docs-dir`、`--force`） |
| `draft <area>` | 区域文件缺少的行，内容已预先填好（`--write`） |
| `check` | 覆盖率、失效路径、归属、行数上限、扇入、生成文件、戳记（`--area`、`--no-stamps`） |
| `stale` | 需要审阅的行（阻断）与只改函数体的文件（提示）（`--area`） |
| `diff <unit>` | 从这个单元的审阅戳记到现在改了什么，先列接口 |
| `stamp` | 记录一次审阅（`<units>`、`--area`、`--edges`、`--prune`、`--baseline`，后者可加 `--force`） |
| `gen` | 重新生成 `<docs_dir>/_generated/` |
| `sync` | 改写区域文件里写的扇入数字 |

**Hook 与工具**

| 命令 | 用途 |
|---|---|
| `hook install\|uninstall\|status` | 可选的 git pre-commit 检查，会运行 `check` |
| `agent-hook session-start\|pre-read\|post-edit` | Claude Code 插件的 hook 运行的命令：从 stdin 读 hook JSON，按 hook 协议回应，退出码始终为 0 |
| `doctor` | 环境与仓库健康检查 |
| `capabilities` | 从实际的 parser 列出所有命令与参数（配合 `--json`） |

全局参数放在命令前后都可以：`--json`、`-C/--repo DIR`、`--config PATH`、`-q`、`-v`、`--debug`。

## 语言

| | |
|---|---|
| **符号**（`outline`、`symbol`、`find`） | Python、JavaScript 与 TypeScript（含 JSX、TSX）、C#、Java、Kotlin、Swift、Dart、Go、Rust、C、C++ 与 Objective-C、shell、SQL、数据文件（JSON、JSONC、JSON5、TOML、YAML、Unity `.asmdef`）以及 Markdown |
| **Import 边**（谁导入了这个文件，以及从修改过的文件找到测试的路径） | Python、JS/TS、C 系列的 `#include "x.h"`、Dart、Go、Rust、Java 与 Kotlin。C# 与 Swift 的 import 指向命名空间和模块而不是文件，所以那里只有名称引用 |
| **纯文本** | `required_ext` 列出的其他扩展名：没有符号，整个文件都计入审阅戳记的接口 |
| **没有解析器** | Ruby、PHP、Scala、Lua、Elixir 等：`outline`、`symbol` 和 `find` 在那里没有内容可显示，但 `locate` 和按路径的 `search` 仍然可用 |

## 配置

全部都是可选的。放在仓库根目录的 `topomark.toml`：

```toml
[topomark]
docs_dir = "docs/codemap"

[files]
exclude = ["**/l10n/app_localizations*.dart"]

[[tests.runner]]
match = "tests/"
command = "python3 -m unittest {names}"
names = "file"
```

区域不在这里配置：每份区域文件的 frontmatter（`scope`、`granularity`）是唯一的依据。完整说明见
[docs/config.md](../docs/config.md)；概念（分层、归属、单元、戳记、扇入）见 [docs/concepts.md](../docs/concepts.md)（英文）。

## 为脚本而设计：退出码与 JSON

| 退出码 | 含义 |
|---|---|
| 0 | 正常 |
| 1 | 有发现（`check`、`stale`、`doctor`、`syntax`）：工具正常运行并发现了问题 |
| 2 | 用法错误，或拒绝执行会丢失信息的操作 |
| 3 | `topomark.toml` 无效 |
| 4 | 找不到路径、符号或区域 |
| 5 | 这个操作没有对应的语言解析器 |
| 6 | 不在 git 工作区里 |
| 7 | 内部错误（加上 `--debug` 重新运行） |

`--json` 在 stdout 只打印一个 JSON 对象，带有 `"schema_version": "topomark/1"` 与 `"command"`。错误输出
`{"error": {"code", "message", "exit", "remediation"}}`，同样在 stdout。`agent-hook` 是唯一的例外：它按
Claude Code 的 hook 协议回应，退出码始终为 0。

## 设计说明与坦诚的局限

- **文件来自 git**，从不遍历目录：`.gitignore` 排除的内容本来就不在范围内。
- **看起来像机密的路径一律不读**（`.env`、`*.pem`、`keys/`、`credentials*` 等），这份清单无法关闭。
  `doctor` 会对被 git 跟踪的机密文件发出警告。
- **解析是词法层面的，不是语义层面的。** 解析器屏蔽注释和字符串、跟踪作用域并读出声明；引用就是标识符匹配。所以 `refs`
  的结果是实际引用的超集，`fan-in` 是近似值；也正因如此，工具速度快、零依赖，并且能处理无法编译的代码。
- **接口哈希忽略函数体**，所以函数内部的重构不需要重新审阅；新的公开方法、改过的常量或重写的文件头注释则需要。
- **缓存放在仓库之外**（`$TOPOMARK_CACHE`、`$XDG_CACHE_HOME/topomark`，Windows 上是 `%LOCALAPPDATA%\topomark\Cache`，
  其余为 `~/.cache/topomark`），以文件的 mtime 和大小为键，语言解析器变化时整体失效。缓存分片存储，所以对单个文件的
  `outline` 在 3,000 个文件的仓库和小仓库上开销相同；大型仓库上第一个需要整个仓库的命令会用 worker process 并行解析
  （`TOPOMARK_JOBS`）。插件 hook 的「每个会话一次」标记也存放在这里。

## 致谢

topomark 借鉴的是思路，不是代码。按重要性排序的仓库地图参考了 [Aider 的 repo map](https://aider.chat/docs/repomap.html)
（Apache-2.0）；符号级别的工具参考了 [Serena](https://github.com/oraios/serena)（GPL-3.0-or-later）；影响范围摘要的
灵感来自 [GitNexus](https://github.com/abhigyanpatwari/GitNexus) 的影响分析（PolyForm Noncommercial，只借鉴概念）。
**topomark 没有复制任何一个项目的代码。** 详见 [ACKNOWLEDGMENTS.md](../ACKNOWLEDGMENTS.md)。

## 贡献、安全与许可证

[CONTRIBUTING.md](../CONTRIBUTING.md) · [SECURITY.md](../SECURITY.md) · [CHANGELOG.md](../CHANGELOG.md) ·
MIT，见 [LICENSE](../LICENSE)。Copyright (c) 2026 Li, ching yu.
