# topomark

**給 AI 程式代理用的零相依 code map。** 分層漸進揭露的文件告訴代理該看哪裡，逐檔審閱戳記抓出過期的摘要，
再加上符號、影響範圍、測試的快速導覽，適用任何 git repo。只用 Python 3.11 以上的標準函式庫，完全離線，
不改動你的程式碼。

[English README](../README.md)

## 為什麼

- **漸進揭露。** 代理大部分的 context 都花在為了找一個函式而讀整個檔案。topomark 給它一把梯子：
  L0 分區索引、每區一份 L1 區檔（每個檔一列：做什麼、有多少檔依賴它、改了要動什麼），最後才是用符號讀程式
  （`outline`、`symbol`、`refs`）。每一層都小到可以整份讀完。
- **審閱戳記，不是時間戳記。** 手寫的地圖會默默過期。topomark 為每個檔記下審閱那一列當時的*介面*雜湊
  （檔頭註解、公開簽章、常數）。介面改了卻沒審那一列，`topomark check` 就會失敗；只改函式內容則不打擾。
  日期做不到這件事。
- **零相依。** 不用 tree-sitter、不用語言伺服器、不連網路。一個 `git clone` 加上 Python 3.11 就能跑，
  在 CI、pre-commit hook、代理的沙盒裡行為都一樣。
- **只連結、不重寫。** `init` 會找出 repo 既有的規則檔（CLAUDE.md、AGENTS.md、ARCHITECTURE.md、
  REPO_MAP.md 等），在 L0 連過去，不把內容抄一份。

## 安裝

目前是私人 repo，以下任一種都可以：

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
~/tools/topomark/bin/topomark --version
```

把 `~/tools/topomark/bin` 加進 `PATH`；remote 建好之後也可以安裝成指令：

```bash
pipx install git+https://github.com/tipoLi5890/topomark
```

`bin/topomark` 會自己找 Python 3.11 以上的直譯器，`PATH` 上需要有 `git`。

**當成代理外掛。** 這個 repo 本身就是 Claude Code 外掛與 marketplace（`.claude-plugin/`），也是 Codex 外掛
（`.codex-plugin/`），內含一個技能 [`skills/topomark`](../skills/topomark/SKILL.md)。在 Claude Code 中先執行
`/plugin marketplace add tipoLi5890/topomark`，再執行 `/plugin install topomark@topomark`。外掛還附帶三個 hook：
session 開始時指出 code map 的位置、讀大檔或第一次讀到某區的檔案前給提示、每次改檔後檢查語法（見下方「從代理使用」）。

## 快速開始

```bash
cd your-repo
topomark doctor                 # Python、git、設定檔、被追蹤的機密檔
topomark init --dry-run         # 提議的分區、排除規則與要寫的檔案；什麼都不寫
topomark init                   # 寫出 topomark.toml 與 code map 骨架
topomark draft backend --write  # 一區的檔案表，摘要與扇入先填好；接著人工修改
topomark gen                    # 產生扇入表與模組依賴圖
topomark stamp --baseline       # 讀過每一列之後，只做一次
topomark check                  # 之後每次：地圖跟程式同步嗎？
topomark hook install           # 選用的 pre-commit 檢查
```

導覽指令不需要任何設定：

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

## 指令

**導覽**：唯讀，任何 git repo 都能用，不需設定。依代理遇到的順序排列：先認識環境、找到位置，改檔前先看，改完再檢查。

| 指令 | 用途 |
|---|---|
| `map` | 在 token 預算內的 repo 排名地圖，適合還沒有 code map 的 repo（`--focus`、`--tokens`、`--area`） |
| `outline <path>..` | 列出符號與行號範圍、種類、簽章、文件摘要；可一次給多個檔或目錄（只列頂層，有 token 上限） |
| `symbol <file>#<Name>` | 只印出一個符號的原始碼；`--skeleton` 只留宣告，函式內容以 `…` 代替 |
| `find <Name>` | 依名字找定義 |
| `search <keywords>` | 依關鍵字找程式（BM25：符號名稱、簽章、文件摘要、路徑）；請給關鍵字，不要貼整段 issue |
| `locate "<訊息>"`、`locate --trace [FILE]` | 從錯誤訊息或 stack trace 找到產生它的程式；訊息裡插入的值不影響比對，trace 先列最內層 |
| `owner <path>` | 歸屬的區、單元、扇入、戳記狀態 |
| `refs <Name>` | 引用位置（排除註解與字串） |
| `impact <Name 或檔案>` | 改動會牽動的呼叫端、匯入它的檔案、跨區使用者、測試、文件 |
| `brief <檔案或 Name>` | 改檔前一次看完：區檔那一列、outline、耦合最深的呼叫端、測試與執行指令（有 token 上限） |
| `syntax [paths]` | 改完的檔還能不能解析：Python、JSON、TOML 用正式解析器，其他大括號語言檢查括號是否成對（只在 HEAD 版本成對時回報）；有問題時結束碼為 1 |
| `tests-for [paths]` | 涵蓋這次改動的測試，印成可以直接執行的指令；沒有測試提到時沿著呼叫端往上找（`--depth`） |
| `changes` | 這次改動碰到哪些符號：介面（新增、移除、簽章）或只改內容；還有誰引用改過的名字、要跑的測試、要重審的 code map 列（`--staged`、`--since`） |

**Code map**：只寫 `topomark.toml` 與 `docs_dir`。

| 指令 | 用途 |
|---|---|
| `init` | 偵測技術組成並寫出 code map 骨架（`--dry-run`、`--docs-dir`、`--force`） |
| `draft <area>` | 區檔缺的列，先填好摘要與扇入（`--write`） |
| `check` | 覆蓋率、死路徑、歸屬、行數上限、扇入、產生檔、戳記 |
| `stale` | 需要審的列（擋關）與只改內容的檔（提示） |
| `diff <unit>` | 從上次審閱到現在改了什麼，先列介面 |
| `stamp` | 記錄一次審閱 |
| `gen` | 重產 `_generated/` |
| `sync` | 更新區檔裡的扇入數字 |

**Hook 與工具**

| 指令 | 用途 |
|---|---|
| `hook install\|uninstall\|status` | 選用的 git pre-commit 檢查，會執行 `check` |
| `agent-hook session-start\|pre-read\|post-edit` | Claude Code 外掛的 hook 執行的指令：從 stdin 讀 hook JSON，依 hook 協定回應，結束碼一律為 0 |
| `doctor` | 環境與 repo 健康檢查 |
| `capabilities` | 從實際的 parser 列出所有指令與旗標（搭配 `--json`） |

內建的語言解析器涵蓋 Python、JavaScript 與 TypeScript（含 JSX、TSX）、C#、Java、Kotlin、Swift、Dart、
Go、Rust、C、C++ 與 Objective-C、shell、SQL、資料檔（JSON、JSONC、JSON5、TOML、YAML、Unity `.asmdef`）
以及 Markdown。`required_ext` 列出的其他副檔名當成純文字讀：沒有符號，整份內容都算進審閱戳記的介面雜湊。

`--json` 在 stdout 只印一個 JSON 物件，帶 `"schema_version": "topomark/1"`。結束碼：0 正常、1 有發現、
2 用法錯誤或拒絕執行、3 設定檔錯誤、4 找不到、5 不支援的語言、6 不是 git repo、7 內部錯誤。
`agent-hook` 是唯一的例外：它依 Claude Code 的 hook 協定回應，結束碼一律為 0。

`init` 寫出的範本、`gen` 產生的報表與 `draft` 填好的列一律是英文。

設定檔說明見 [docs/config.md](../docs/config.md)，概念見 [docs/concepts.md](../docs/concepts.md)（英文）。

## 從代理使用

內附的技能教代理照這個流程走：先讀 L0，再讀一份區檔，接著 `outline`、`symbol`；改檔前 `brief`，改完 `syntax`；
執行 `tests-for` 印出的指令；提交前 `changes`；最後 `check`、`diff`、`stamp`。每一步都是 shell 指令，不需要斜線指令
或外掛執行環境，所以 Claude Code、Codex 或任何有終端機的代理都能照做。

**Claude Code 外掛的 hook。** 以外掛安裝時，topomark 會另外註冊三個 hook（`hooks/hooks.json`），只補充 context，
從不阻擋工具呼叫：

- **SessionStart**（startup、clear、compact）：L0 的路徑、每區的名稱與區檔、一行導覽指令，以及是否已有審閱戳記；
  最多 40 行。沒有 code map 時只給一行，建議執行 `topomark map --tokens 2000`。
- **PreToolUse（Read）**：讀超過 400 行的檔案前，提示先用 `outline` 與 `symbol --skeleton`；第一次讀到某區的檔案時，
  指出它的區檔。同一個提示每個 session 只出現一次，指定行數範圍的讀取不會收到提示。
- **PostToolUse（Edit、Write、MultiEdit）**：對改過的檔案做 `syntax` 檢查，只有這次修改讓檔案無法解析時才回報。

每個 hook 只啟動一個短暫的行程（在 3,000 個檔案的 repo 上約 0.15 到 0.3 秒 CPU 時間）。Codex 沒有 hook，技能會要求
每次改檔後自己執行 `topomark syntax --diff`。細節見
[adoption.md](../skills/topomark/reference/adoption.md#claude-code-plugin-hooks)（英文）。

## 致謝

topomark 借用的是想法，不是程式碼：排名式 repo 地圖參考 Aider 的 repo map（Apache-2.0）、符號層級的工具參考
Serena（MIT）、影響範圍摘要的概念來自 GitNexus（PolyForm Noncommercial，只借概念）。**topomark 沒有複製任何
一個專案的程式碼。** 詳見 [ACKNOWLEDGMENTS.md](../ACKNOWLEDGMENTS.md)。

## 授權

MIT，見 [LICENSE](../LICENSE)。Copyright (c) 2026 Li, ching yu.
