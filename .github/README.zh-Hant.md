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
（`.codex-plugin/`），內含一個技能 [`skills/topomark`](../skills/topomark/SKILL.md)。

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
topomark find Router --exact
topomark refs Router --no-tests
topomark impact Router
topomark tests-for --since main
```

## 指令

| 指令 | 用途 |
|---|---|
| `outline <file>` | 列出符號與行號範圍、種類、簽章、文件摘要 |
| `symbol <file>#<Name>` | 只印出一個符號的原始碼 |
| `find <Name>` | 依名字找定義 |
| `refs <Name>` | 引用位置（排除註解與字串） |
| `impact <Name 或檔案>` | 改動會牽動的呼叫端、跨區使用者、測試、文件 |
| `tests-for [paths]` | 涵蓋這次改動的測試，印成可以直接跑的指令 |
| `map` | 在 token 預算內的 repo 排名地圖 |
| `owner <path>` | 歸屬的區、單元、扇入、戳記狀態 |
| `init` | 偵測技術組成並寫出 code map 骨架（`--dry-run`、`--lang zh-Hant`） |
| `draft <area>` | 區檔缺的列，先填好摘要與扇入（`--write`） |
| `check` | 覆蓋率、死路徑、歸屬、行數上限、扇入、產生檔、戳記 |
| `stale` | 需要審的列（擋關）與只改內容的檔（提示） |
| `diff <unit>` | 從上次審閱到現在改了什麼，先列介面 |
| `stamp` | 記錄一次審閱 |
| `gen`、`sync` | 重產 `_generated/`；更新區檔裡的扇入數字 |
| `hook`、`doctor`、`capabilities` | pre-commit 檢查；環境健康檢查；機器可讀的指令清單 |

`--json` 在 stdout 只印一個 JSON 物件，帶 `"schema_version": "topomark/1"`。結束碼：0 正常、1 有發現、
2 用法錯誤或拒絕執行、3 設定檔錯誤、4 找不到、5 不支援的語言、6 不是 git repo、7 內部錯誤。

設定檔說明見 [docs/config.md](../docs/config.md)，概念見 [docs/concepts.md](../docs/concepts.md)（英文）。

## 中文 code map

`topomark init --lang zh-Hant` 會用繁體中文範本寫出 L0 與區檔，影響範圍欄寫成 `扇入 P／T`，
`topomark sync` 會維持這個格式。範本用台灣慣用語、全形標點、不用破折號。

## 致謝

topomark 借用的是想法，不是程式碼：排名式 repo 地圖參考 Aider 的 repo map（Apache-2.0）、符號層級的工具參考
Serena（MIT）、影響範圍摘要的概念來自 GitNexus（PolyForm Noncommercial，只借概念）。**topomark 沒有複製任何
一個專案的程式碼。** 詳見 [ACKNOWLEDGMENTS.md](../ACKNOWLEDGMENTS.md)。

## 授權

MIT，見 [LICENSE](../LICENSE)。Copyright (c) 2026 Li, ching yu.
