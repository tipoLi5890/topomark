# topomark

**你的代理為了找一個函式讀了兩千行的檔案。給它一張地圖吧。**

topomark 是給 AI 程式代理用的零相依 code map：分層的文件告訴代理該看哪裡，摘要過期時審閱戳記會讓 CI 失敗，
再加上符號、影響範圍與測試的快速導覽，適用任何 git repo。只用 Python 3.11 以上的標準函式庫；完全離線；
對你的程式碼唯讀。

![license: MIT](https://img.shields.io/badge/license-MIT-blue)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

[English](../README.md) · [简体中文](README.zh-Hans.md) · [日本語](README.ja.md)

## 讓你的代理幫你安裝

在你的 repo 裡，把下面這段貼給 Claude Code、Codex 或任何有終端機的程式代理：

```text
安裝 topomark（https://github.com/tipoLi5890/topomark），一個零相依的 code map 與導覽 CLI，
並把這個 repo 設定好來使用它：

1. clone 下來：git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
   （如果這個目錄已經存在，改成執行 git -C ~/tools/topomark pull）。
2. 加進 PATH：ln -sf ~/tools/topomark/bin/topomark ~/.local/bin/topomark，並確認 ~/.local/bin
   在 PATH 上。用 topomark --version 確認（需要 Python 3.11 以上與 git）。
3. 在這個 repo 執行 topomark doctor，回報它找到的任何問題。
4. 讀 ~/tools/topomark/skills/topomark/SKILL.md，之後照它的做法工作。
5. 把下面這一行加進 AGENTS.md；如果這個 repo 用的是 CLAUDE.md，就加進 CLAUDE.md：
   "Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
   `topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before
   an edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and
   keep `topomark check` green."
6. 執行 topomark init --dry-run，給我看提議的分區。在我同意之前什麼都不要寫；
   同意後再執行 topomark init，並對每一區執行 topomark draft <area> --write，把每一列填好。
```

在建立 code map 之前，`topomark map --tokens 2000` 和其他導覽指令就已經能用了；第 6 步讓 `check` 與審閱戳記成為可能。

## 30 秒試用

導覽不需要安裝步驟、設定檔，也不用先建索引。clone 下來，然後對任何 git repo 使用：

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
cd your-repo
~/tools/topomark/bin/topomark map --tokens 2000      # 在 token 預算內的 repo 排名地圖
```

什麼都不會安裝，也不會寫入你的 repo。

## 為什麼選 topomark

### 一把梯子，而不是一堆乾草

代理有很多 context 花在為了找一個函式而讀整個檔案。topomark 給它一階一階的梯子，每一階都小到可以整份讀完：

```text
L0  docs/codemap/README.md     一份索引：repo 分成哪些區，各自負責什麼
L1  docs/codemap/<area>.md     每個檔一列：做什麼、有多少檔依賴它、
                               改了要更新什麼
L2  依符號讀程式碼             topomark outline / symbol / refs：一個函式，而不是整個檔案
```

### 審閱戳記，不是時間戳記

手寫的地圖會默默過期。所以 topomark 為每個檔記下那一列被審閱時它的*介面*雜湊（檔頭註解、公開簽章、常數）。

- 改了介面卻沒審那一列：`topomark check` 失敗。
- 只改函式內容：不打擾。

「最後更新日期」分不出這兩種情況，戳記分得出來。所以地圖要嘛是最新的，要嘛 CI 會明確指出哪幾列不是。

### 真的零相依

不用 tree-sitter、不用語言伺服器、不連網路。一個 `git clone` 加上 Python 3.11 直譯器就能跑，
在 CI、pre-commit hook 與代理的沙盒裡行為都一樣。

### 快到每一步都能跑

在 3,000 個檔案的合成 repo 上、快取已建立時，`outline` 與 `symbol` 約用 0.05 秒 CPU 時間，
`map`、`search`、`impact` 與 `brief` 介於 0.16 到 0.28 秒（在一台 Apple silicon 筆電上；
表格與量測方法見 [docs/pilots.md](../docs/pilots.md)）。

### 只連結、不重寫

`init` 會找出 repo 既有的規則檔（CLAUDE.md、AGENTS.md、ARCHITECTURE.md、REPO_MAP.md 等），
連過去而不是把內容抄一份。

## 安裝

以下任一種都可以：

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
~/tools/topomark/bin/topomark --version     # 會自己找到路徑的啟動器，不需要安裝步驟
```

把 `~/tools/topomark/bin` 加進 `PATH`（例如 `ln -s ~/tools/topomark/bin/topomark ~/.local/bin/topomark`）。
已經在用 pipx 的話，也可以用它安裝成指令（不一定要裝 pipx）：

```bash
pipx install git+https://github.com/tipoLi5890/topomark
```

`bin/topomark` 會自己找 Python 3.11 以上的直譯器（從 `python3.14` 往下找到 `python3`）。`PATH` 上需要有 `git`。

**當成代理外掛。** 這個 repo 本身就是 Claude Code 外掛與 marketplace（`.claude-plugin/`），也是 Codex 外掛
（`.codex-plugin/`），內含一個技能 [`skills/topomark`](../skills/topomark/SKILL.md)。在 Claude Code 中先執行
`/plugin marketplace add tipoLi5890/topomark`，再執行 `/plugin install topomark@topomark`。外掛還附帶三個 hook：
session 開始時給一段簡短的 code map 指引、讀大檔或第一次讀到某區的檔案前給提示、每次改檔後檢查語法
（見[從代理使用](#從代理使用)）。

## 快速開始

**導覽**（完全不需要設定）：

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

**建立一份不會過期的 code map**：

```bash
cd your-repo
topomark doctor                 # Python、git、設定檔、被 git 追蹤的機密檔
topomark init --dry-run         # 提議的分區、排除規則與要寫的檔案；什麼都不寫
topomark init                   # 寫出 topomark.toml 與 code map 骨架
topomark draft backend --write  # 一區的列，摘要與扇入先填好；接著人工修改
topomark gen                    # 產生扇入表與模組依賴圖
topomark stamp --baseline       # 讀過每一列之後，只做一次
topomark check                  # 之後每次：地圖跟程式碼同步嗎？
topomark hook install           # 選用的 pre-commit 檢查
```

## 從代理使用

內附的技能教代理這個流程：讀 L0，讀一份區檔，`outline`、`symbol`；改檔前 `brief`，改完 `syntax`；執行
`tests-for` 印出的指令；提交前 `changes`；最後 `check`、`diff`、`stamp`。不需要斜線指令或外掛執行環境：每一步都是
shell 指令，所以同一套說明在 Claude Code、Codex 或任何有終端機的代理裡都適用。在 `AGENTS.md` 或 `CLAUDE.md`
加一行就夠了（代理讀英文，所以這一行保留原文）：

```text
Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
`topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before an
edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and keep
`topomark check` green.
```

**Claude Code 外掛的 hook。** 以外掛安裝時，topomark 會另外註冊三個 hook（`hooks/hooks.json`），只補充 context，
從不阻擋工具呼叫：

- **SessionStart**（startup、clear、compact）：L0 的路徑、每區的名稱與區檔、一行導覽指令，以及是否已有審閱戳記；
  最多 40 行。沒有 code map 時只給一行，建議執行 `topomark map --tokens 2000`。
- **PreToolUse（Read）**：超過 400 行的檔案會收到改用 `outline` 與 `symbol --skeleton` 的提示；第一次讀到某區的檔案時，
  指出它的區檔。每個提示每個 session 只出現一次；指定行數範圍的讀取不會收到提示。
- **PostToolUse（Edit、Write、MultiEdit）**：對改過的檔案做 `syntax` 檢查，只有這次修改讓檔案無法解析時才回報。

每個 hook 只啟動一個短暫的行程（在 3,000 個檔案的 repo 上約 0.15 到 0.3 秒 CPU 時間）。topomark 只為 Claude Code 提供 hook；
在其他代理裡，技能會要求每次改檔後執行 `topomark syntax --diff`。細節見
[adoption.md](../skills/topomark/reference/adoption.md#claude-code-plugin-hooks)（英文）。

## 指令

**導覽**：唯讀，任何 git repo 都能用，不需設定。依代理遇到的順序排列：先認識環境、找到位置，改檔前先看，改完再檢查。

| 指令 | 用途 |
|---|---|
| `map` | 在 token 預算內的 repo 排名地圖，適合還沒有 code map 的 repo（`--focus`、`--tokens`、`--area`） |
| `outline <path>..` | 符號與行號範圍、種類、簽章、文件摘要；可一次給多個檔或一個目錄，只列頂層並受 token 預算限制（`--exported-only`、`--kinds`、`--depth`、`--tokens`） |
| `symbol <file>#<Name>`／`symbol <Name>` | 印出一個符號的原始碼（`--signature`；`--skeleton` 只留宣告、省略函式內容；`--context N`） |
| `find <Name>` | 依名字找定義（`--kind`、`--exact`、`--limit`） |
| `search <keywords>` | 依主題找程式碼：以 BM25 比對符號名稱、簽章、文件與路徑；比對到的測試會帶到它使用的程式碼。請給關鍵字，不要貼整段 issue（`--limit`、`--area`、`--tokens`） |
| `locate "<訊息>"`／`locate --trace [FILE]` | 找出錯誤訊息背後的程式碼（比對字面的連續字詞，所以插入的值不影響比對），或 stack trace 背後的程式碼（Python、Node、Java/Kotlin、C#、Dart、Go、Rust、`path:line`）；程式碼先於測試，測試先於文件（`--regex`、`--limit`） |
| `owner <path>` | 歸屬的區、單元、扇入與戳記狀態 |
| `refs <Name>` | 引用位置，排除註解與字串；文字輸出顯示各組數量與前 20 筆（`--area`、`--no-tests`、`--limit`） |
| `impact <Name 或檔案>` | 改動會牽動的呼叫端、匯入它的檔案、跨區使用者、測試與文件（`--top`） |
| `brief <檔案或 Name>` | 改檔前的一份簡報，受 token 預算限制：區檔那一列、outline、耦合最深的呼叫端、測試與執行它們的指令（`--tokens`） |
| `syntax [paths]` | 改過的檔是否仍能解析：Python、JSON、TOML 精確解析，大括號語言檢查括號是否成對（只在 HEAD 版本成對時才檢查）；有發現時結束碼為 1（`--diff`，預設） |
| `tests-for [paths]` | 涵蓋改動檔案的測試，沒有測試提到它們時經由呼叫端找，印成可以直接執行的指令（`--diff`、`--staged`、`--since REV`、`--depth N`） |
| `changes` | 這次 diff 碰到的符號，是介面（新增、移除、新簽章）還是只有內容；還有誰引用改過的介面、要跑的測試、要重審的 code map 列（`--staged`、`--since REV`、`--top`） |

**Code map**：只寫 `topomark.toml` 與 `docs_dir`。

| 指令 | 用途 |
|---|---|
| `init` | 偵測技術組成並寫出 code map 骨架（`--dry-run`、`--docs-dir`、`--force`） |
| `draft <area>` | 區檔缺少的列，內容先填好（`--write`） |
| `check` | 覆蓋率、死路徑、歸屬、行數上限、扇入、產生檔、戳記（`--area`、`--no-stamps`） |
| `stale` | 需要審閱的列（擋關）與只改內容的檔（提示）（`--area`） |
| `diff <unit>` | 從這個單元的審閱戳記到現在改了什麼，先列介面 |
| `stamp` | 記錄一次審閱（`<units>`、`--area`、`--edges`、`--prune`、`--baseline`，後者可加 `--force`） |
| `gen` | 重新產生 `<docs_dir>/_generated/` |
| `sync` | 改寫區檔裡寫的扇入數字 |

**Hook 與工具**

| 指令 | 用途 |
|---|---|
| `hook install\|uninstall\|status` | 選用的 git pre-commit 檢查，會執行 `check` |
| `agent-hook session-start\|pre-read\|post-edit` | Claude Code 外掛的 hook 執行的指令：從 stdin 讀 hook JSON，依 hook 協定回應，結束碼一律為 0 |
| `doctor` | 環境與 repo 健康檢查 |
| `capabilities` | 從實際的 parser 列出所有指令與旗標（搭配 `--json`） |

全域旗標放在指令前後都可以：`--json`、`-C/--repo DIR`、`--config PATH`、`-q`、`-v`、`--debug`。

## 語言

| | |
|---|---|
| **符號**（`outline`、`symbol`、`find`） | Python、JavaScript 與 TypeScript（含 JSX、TSX）、C#、Java、Kotlin、Swift、Dart、Go、Rust、C、C++ 與 Objective-C、shell、SQL、資料檔（JSON、JSONC、JSON5、TOML、YAML、Unity `.asmdef`）以及 Markdown |
| **Import 邊**（誰匯入了這個檔案，以及從改動的檔案找到測試的路徑） | Python、JS/TS、C 系列的 `#include "x.h"`、Dart、Go、Rust、Java 與 Kotlin。C# 與 Swift 的 import 指向命名空間與模組而不是檔案，所以那裡只有名稱參照 |
| **純文字** | `required_ext` 列出的其他副檔名：沒有符號，整份內容都算進審閱戳記的介面 |
| **沒有解析器** | Ruby、PHP、Scala、Lua、Elixir 等：`outline`、`symbol` 與 `find` 在那裡沒有東西可顯示，但 `locate` 與依路徑的 `search` 仍可用 |

## 設定

全部都是選用的。放在 repo 根目錄的 `topomark.toml`：

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

分區不在這裡設定：每份區檔的 frontmatter（`scope`、`granularity`）是唯一的依據。完整說明見
[docs/config.md](../docs/config.md)；概念（分層、歸屬、單元、戳記、扇入）見 [docs/concepts.md](../docs/concepts.md)（英文）。

## 為腳本而設計：結束碼與 JSON

| 結束碼 | 意義 |
|---|---|
| 0 | 正常 |
| 1 | 有發現（`check`、`stale`、`doctor`、`syntax`）：工具正常執行並找到問題 |
| 2 | 用法錯誤，或拒絕執行會遺失資訊的動作 |
| 3 | `topomark.toml` 無效 |
| 4 | 找不到路徑、符號或區 |
| 5 | 這個操作沒有對應的語言解析器 |
| 6 | 不在 git 工作目錄裡 |
| 7 | 內部錯誤（加上 `--debug` 重新執行） |

`--json` 在 stdout 只印一個 JSON 物件，帶 `"schema_version": "topomark/1"` 與 `"command"`。錯誤印出
`{"error": {"code", "message", "exit", "remediation"}}`，同樣在 stdout。`agent-hook` 是唯一的例外：它依
Claude Code 的 hook 協定回應，結束碼一律為 0。

## 設計說明與坦白的限制

- **檔案來自 git**，從不走訪目錄：`.gitignore` 排除的東西本來就不在範圍內。
- **看起來像機密的路徑一律不讀**（`.env`、`*.pem`、`keys/`、`credentials*` 等），這份清單無法關閉。
  `doctor` 會警告被 git 追蹤的機密檔。
- **解析是詞法層級，不是語意層級。** 解析器遮掉註解與字串、追蹤作用域並讀出宣告；參照就是識別字比對。所以 `refs`
  的結果是實際參照的超集，`fan-in` 是近似值；也因此工具快速、零相依，並且能處理無法編譯的程式碼。
- **介面雜湊忽略函式內容**，所以函式內部的重構不需要重審；新的公開方法、改過的常數或重寫的檔頭註解則需要。
- **快取放在 repo 之外**（`$TOPOMARK_CACHE`、`$XDG_CACHE_HOME/topomark`，Windows 上是 `%LOCALAPPDATA%\topomark\Cache`，
  其餘為 `~/.cache/topomark`），以檔案的 mtime 與大小為鍵，語言解析器改變時整份作廢。快取分片儲存，所以對單一檔案的
  `outline` 在 3,000 個檔案的 repo 和小 repo 上成本相同；大型 repo 上第一個需要整個 repo 的指令會用 worker process
  平行解析（`TOPOMARK_JOBS`）。外掛 hook 的「每個 session 一次」標記也放在這裡。

## 致謝

topomark 借用的是想法，不是程式碼。排名式 repo 地圖參考 [Aider 的 repo map](https://aider.chat/docs/repomap.html)
（Apache-2.0）；符號層級的工具參考 [Serena](https://github.com/oraios/serena)（GPL-3.0-or-later）；影響範圍摘要的
靈感來自 [GitNexus](https://github.com/abhigyanpatwari/GitNexus) 的影響分析（PolyForm Noncommercial，只借概念）。
**topomark 沒有複製任何一個專案的程式碼。** 詳見 [ACKNOWLEDGMENTS.md](../ACKNOWLEDGMENTS.md)。

## 貢獻、安全與授權

[CONTRIBUTING.md](../CONTRIBUTING.md) · [SECURITY.md](../SECURITY.md) · [CHANGELOG.md](../CHANGELOG.md) ·
MIT，見 [LICENSE](../LICENSE)。Copyright (c) 2026 Li, ching yu.
