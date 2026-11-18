# topomark

**あなたのエージェントは、関数ひとつを探すために 2,000 行のファイルを読んでいる。代わりに地図を渡そう。**

topomark は AI コーディングエージェントのための、依存ゼロのコードマップである。どこを読むべきかを示す階層ドキュメント、
要約が古くなると CI を失敗させるレビュースタンプ、そしてシンボル・影響範囲・テストをすばやくたどるナビゲーションを、
あらゆる git リポジトリで提供する。Python 3.11 以上の標準ライブラリのみ。オフラインで動き、あなたのコードに対しては読み取り専用。

![license: MIT](https://img.shields.io/badge/license-MIT-blue)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)

[English](../README.md) · [繁體中文](README.zh-Hant.md) · [简体中文](README.zh-Hans.md)

## エージェントにインストールさせる

リポジトリの中で、次の文章を Claude Code、Codex、またはターミナルを使えるコーディングエージェントに貼り付ける。

```text
topomark（https://github.com/tipoLi5890/topomark）をインストールしてください。依存ゼロのコードマップと
ナビゲーションの CLI です。そのうえで、このリポジトリで使えるように設定してください。

1. clone する：git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
   （そのディレクトリがすでにあれば、代わりに git -C ~/tools/topomark pull を実行する）。
2. PATH に通す：ln -sf ~/tools/topomark/bin/topomark ~/.local/bin/topomark を実行し、~/.local/bin が
   PATH に入っていることを確かめる。topomark --version で確認する（Python 3.11 以上と git が必要）。
3. このリポジトリで topomark doctor を実行し、報告された問題があれば教えてください。
4. ~/tools/topomark/skills/topomark/SKILL.md を読み、以後はそのとおりに作業する。
5. 次の 1 行を AGENTS.md に追加する。このリポジトリが CLAUDE.md を使っているなら CLAUDE.md に追加する：
   "Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
   `topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before
   an edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and
   keep `topomark check` green."
6. topomark init --dry-run を実行し、提案されたエリアを見せてください。私が同意するまでは何も書かないこと。
   同意したら topomark init を実行し、エリアごとに topomark draft <area> --write を実行して、各行を埋める。
```

コードマップができるまでの間も、`topomark map --tokens 2000` などのナビゲーションコマンドはすでに使える。
`check` とレビュースタンプを使えるようにするのが手順 6 である。

## 30 秒で試す

ナビゲーションには、セットアップも設定ファイルも事前のインデックス作成も要らない。clone して、任意の git リポジトリに向けるだけでよい。

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
cd your-repo
~/tools/topomark/bin/topomark map --tokens 2000      # token 予算内に収めた、重要度順のリポジトリマップ
```

何もインストールされず、リポジトリにも何も書き込まれない。

## topomark を使う理由

### 干し草の山ではなく、はしごを

エージェントは関数ひとつを探すためにファイル全体を読み、多くの context を費やしている。topomark ははしごの段を用意する。
どの段も全体を読み切れる大きさである。

```text
L0  docs/codemap/README.md     索引ひとつ：リポジトリのエリアと、それぞれが受け持つもの
L1  docs/codemap/<area>.md     ファイルごとに 1 行：何をするか、何個のファイルが依存しているか、
                               変更時に何を更新すべきか
L2  シンボル単位のコード       topomark outline / symbol / refs：ファイルではなく関数ひとつ
```

### タイムスタンプではなくレビュースタンプ

手書きのマップは気づかないうちに古くなる。そこで topomark はファイルごとに、その行がレビューされた時点の
*インターフェース*（ヘッダーコメント、公開シグネチャ、定数）のハッシュを記録する。

- インターフェースを変えたのに、その行をレビューしていない：`topomark check` が失敗する。
- 関数の本体だけを変えた：何も言わない。

「最終更新日」ではこの 2 つを区別できない。スタンプならできる。だからマップは最新であるか、そうでなければ
どの行が古いかを CI が正確に示す。

### 本当に依存ゼロ

tree-sitter も言語サーバーもネットワークも使わない。`git clone` と Python 3.11 のインタープリターがあれば動き、
CI でも pre-commit hook でもエージェントのサンドボックスでも同じように振る舞う。

### 毎ステップ実行できる速さ

3,000 ファイルの合成リポジトリでキャッシュが温まった状態なら、`outline` と `symbol` は CPU 時間でおよそ 0.05 秒、
`map`、`search`、`impact`、`brief` は 0.16〜0.28 秒（Apple silicon のノートパソコンで計測。表と計測方法は
[docs/pilots.md](../docs/pilots.md) にある）。

### 書き写さず、リンクする

`init` はリポジトリにある既存のルールファイル（CLAUDE.md、AGENTS.md、ARCHITECTURE.md、REPO_MAP.md など）を見つけ、
内容をコピーせずにリンクする。

## インストール

次のどちらでもよい。

```bash
git clone https://github.com/tipoLi5890/topomark ~/tools/topomark
~/tools/topomark/bin/topomark --version     # 自分の場所を見つけるランチャー。インストール手順は不要
```

`~/tools/topomark/bin` を `PATH` に加える（例：`ln -s ~/tools/topomark/bin/topomark ~/.local/bin/topomark`）。
pipx で PyPI からコマンドとしてインストールしてもよい（pipx は必須ではなく、`pip install topomark` でもよい）。

```bash
pipx install topomark
```

`bin/topomark` は Python 3.11 以上のインタープリターを自分で探す（`python3.14` から `python3` まで順に）。
`PATH` に `git` が必要。

**エージェントのプラグインとして。** このリポジトリ自体が Claude Code のプラグイン兼 marketplace（`.claude-plugin/`）であり、
Codex のプラグイン（`.codex-plugin/`）でもあって、スキル [`skills/topomark`](../skills/topomark/SKILL.md) を 1 つ同梱している。
Claude Code では `/plugin marketplace add tipoLi5890/topomark` を実行し、続いて `/plugin install topomark@topomark` を実行する。
プラグインには 3 つの hook も付いている。セッション開始時のコードマップへの短い案内、大きなファイルや初めてのエリアを
読む前のヒント、編集のたびの構文チェックである（[エージェントから使う](#エージェントから使う)を参照）。

## クイックスタート

**ナビゲーション**（設定はまったく不要）：

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

**古くならないコードマップを作る**：

```bash
cd your-repo
topomark doctor                 # Python、git、設定ファイル、git が追跡している機密ファイル
topomark init --dry-run         # 提案するエリア、除外ルール、書き出すファイル。何も書かない
topomark init                   # topomark.toml とコードマップの骨組みを書き出す
topomark draft backend --write  # 1 エリア分の行。要約とファンインは記入済みなので、あとは人が直す
topomark gen                    # ファンイン表とモジュール依存図を生成する
topomark stamp --baseline       # すべての行を読んだあとに一度だけ
topomark check                  # 以後は毎回：マップとコードは同期しているか
topomark hook install           # 任意の pre-commit チェック
```

## エージェントから使う

同梱のスキルは次の流れを教える。L0 を読み、エリアファイルを 1 つ読み、`outline`、`symbol`。編集の前に `brief`、
あとに `syntax`。`tests-for` が示したコマンドを実行し、コミット前に `changes`、最後に `check`、`diff`、`stamp`。
スラッシュコマンドやプラグインの実行環境は要らない。どの手順も shell コマンドなので、同じ手順が Claude Code でも
Codex でも、ターミナルを使えるどのエージェントでも使える。`AGENTS.md` か `CLAUDE.md` に 1 行書けば足りる
（エージェントは英語を読むので、この行は原文のまま）。

```text
Navigate with topomark: read docs/codemap/README.md first, then `topomark outline <file>` and
`topomark symbol <file>#<Name>` instead of reading whole files; `topomark brief <file>` before an
edit. After editing, run `topomark syntax`, run what `topomark tests-for --diff` prints and keep
`topomark check` green.
```

**Claude Code プラグインの hook。** プラグインとしてインストールすると、topomark は 3 つの hook（`hooks/hooks.json`）も
登録する。context を補うだけで、ツールの呼び出しを止めることはない。

- **SessionStart**（startup、clear、compact）：L0 のパス、各エリアの名前とファイル、ナビゲーションコマンドの 1 行、
  レビュースタンプの有無。最大 40 行。コードマップがなければ、`topomark map --tokens 2000` を勧める 1 行だけ。
- **PreToolUse（Read）**：400 行を超えるファイルには `outline` と `symbol --skeleton` への案内を、あるエリアで最初に読むファイルには
  そのエリアファイルへの案内を出す。どのヒントもセッションごとに一度だけで、行範囲を指定した読み込みには出さない。
- **PostToolUse（Edit、Write、MultiEdit）**：編集したファイルの `syntax` チェック。今回の編集で壊れたときだけ報告する。

hook 1 回あたりに起動するのは短命なプロセス 1 つだけ（3,000 ファイルのリポジトリで CPU 時間およそ 0.15〜0.3 秒）。
topomark が hook を提供するのは Claude Code だけで、ほかのエージェントでは、編集のたびに `topomark syntax --diff` を
実行するようスキルが指示する。詳しくは
[adoption.md](../skills/topomark/reference/adoption.md#claude-code-plugin-hooks)（英語）。

## コマンド

**ナビゲーション**：読み取り専用で、どの git リポジトリでも設定なしで使える。エージェントが出会う順に並べている。
全体をつかみ、場所を見つけ、編集の前に確認し、編集のあとにチェックする。

| コマンド | 役割 |
|---|---|
| `map` | token 予算内に収めた、重要度順のリポジトリマップ。コードマップのないリポジトリ向け（`--focus`、`--tokens`、`--area`） |
| `outline <path>..` | シンボルとその行範囲、種類、シグネチャ、ドキュメントの要約。複数のファイルやディレクトリを一度に渡せ、トップレベルを token 予算内で示す（`--exported-only`、`--kinds`、`--depth`、`--tokens`） |
| `symbol <file>#<Name>`／`symbol <Name>` | 1 つのシンボルのソースを表示する（`--signature`、本体を省いて宣言だけを残す `--skeleton`、`--context N`） |
| `find <Name>` | 名前で定義を探す（`--kind`、`--exact`、`--limit`） |
| `search <keywords>` | 内容からコードを探す。シンボル名、シグネチャ、ドキュメント、パスに対する BM25 で、一致したテストからはそのテストが使うコードにたどり着く。issue を丸ごと貼らず、キーワードを渡す（`--limit`、`--area`、`--tokens`） |
| `locate "<メッセージ>"`／`locate --trace [FILE]` | エラーメッセージ（文字どおりの語の並びで照合するので、埋め込まれた値は影響しない）やスタックトレース（Python、Node、Java/Kotlin、C#、Dart、Go、Rust、`path:line`）の元になったコード。コード、テスト、ドキュメントの順に並べる（`--regex`、`--limit`） |
| `owner <path>` | 所属エリア、ユニット、ファンイン、スタンプの状態 |
| `refs <Name>` | 参照箇所。コメントと文字列は除く。テキスト出力はグループごとの件数と最初の 20 件を示す（`--area`、`--no-tests`、`--limit`） |
| `impact <Name またはファイル>` | 変更が及ぶ呼び出し元、それを import するファイル、ほかのエリアの利用者、テスト、ドキュメント（`--top`） |
| `brief <ファイルまたは Name>` | 編集前の 1 回分の説明を token 予算内で：エリアファイルの該当行、outline、結合の強い呼び出し元、テストとその実行コマンド（`--tokens`） |
| `syntax [paths]` | 編集したファイルがまだ解析できるか。Python、JSON、TOML は厳密に、波括弧言語は括弧の対応を調べる（HEAD で対応が取れていた場合のみ）。検出があれば終了コード 1（`--diff`、既定） |
| `tests-for [paths]` | 変更したファイルをカバーするテスト。どのテストも名前を挙げていなければ呼び出し元を経由して探し、実行できるコマンドとして示す（`--diff`、`--staged`、`--since REV`、`--depth N`） |
| `changes` | diff が触れたシンボル。インターフェース（追加、削除、新しいシグネチャ）か本体か、変わったインターフェースをまだ参照している箇所、実行すべきテスト、レビューすべきコードマップの行（`--staged`、`--since REV`、`--top`） |

**コードマップ**：書き込むのは `topomark.toml` と `docs_dir` だけ。

| コマンド | 役割 |
|---|---|
| `init` | 技術スタックを検出し、コードマップの骨組みを書き出す（`--dry-run`、`--docs-dir`、`--force`） |
| `draft <area>` | エリアファイルに足りない行を、記入済みの状態で出す（`--write`） |
| `check` | カバレッジ、無効なパス、所属、行数の上限、ファンイン、生成ファイル、スタンプ（`--area`、`--no-stamps`） |
| `stale` | レビューが必要な行（ブロック）と、本体だけが変わったファイル（通知）（`--area`） |
| `diff <unit>` | そのユニットのレビュースタンプ以降に何が変わったか。インターフェースを先に示す |
| `stamp` | レビューを記録する（`<units>`、`--area`、`--edges`、`--prune`、`--baseline`。後者には `--force` を併用可） |
| `gen` | `<docs_dir>/_generated/` を再生成する |
| `sync` | エリアファイルに書かれたファンインの数を書き直す |

**Hook とツール**

| コマンド | 役割 |
|---|---|
| `hook install\|uninstall\|status` | 任意の git pre-commit チェック。`check` を実行する |
| `agent-hook session-start\|pre-read\|post-edit` | Claude Code プラグインの hook が実行するもの。stdin から hook の JSON を読み、hook のプロトコルで応答し、終了コードは常に 0 |
| `doctor` | 環境とリポジトリの健全性 |
| `capabilities` | 実際のパーサーから得た全コマンドとフラグ（`--json` と併用） |

グローバルフラグはコマンドの前にも後にも置ける：`--json`、`-C/--repo DIR`、`--config PATH`、`-q`、`-v`、`--debug`。

## 対応言語

| | |
|---|---|
| **シンボル**（`outline`、`symbol`、`find`） | Python、JavaScript と TypeScript（JSX、TSX を含む）、C#、Java、Kotlin、Swift、Dart、Go、Rust、C、C++ と Objective-C、shell、SQL、データファイル（JSON、JSONC、JSON5、TOML、YAML、Unity `.asmdef`）、Markdown |
| **import のエッジ**（このファイルを import しているのは誰か、変更したファイルからテストへの経路） | Python、JS/TS、C 系の `#include "x.h"`、Dart、Go、Rust、Java、Kotlin。C# と Swift の import はファイルではなく名前空間やモジュールを指すため、そこでは名前による参照だけになる |
| **プレーンテキスト** | `required_ext` に挙げたそれ以外の拡張子。シンボルはなく、ファイル全体がレビューの対象面になる |
| **アダプターなし** | Ruby、PHP、Scala、Lua、Elixir など。`outline`、`symbol`、`find` は何も示せないが、`locate` とパスに対する `search` は使える |

## 設定

すべて任意。リポジトリのルートに置く `topomark.toml`：

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

エリアはここでは設定しない。各エリアファイルの frontmatter（`scope`、`granularity`）が唯一の拠り所である。
詳しくは [docs/config.md](../docs/config.md)、概念（階層、所属、ユニット、スタンプ、ファンイン）は
[docs/concepts.md](../docs/concepts.md) を参照（英語）。

## スクリプトから使うために：終了コードと JSON

| 終了コード | 意味 |
|---|---|
| 0 | 正常 |
| 1 | 検出あり（`check`、`stale`、`doctor`、`syntax`）：ツールは正常に動き、問題を見つけた |
| 2 | 使い方の誤り、または情報を失う操作の拒否 |
| 3 | `topomark.toml` が無効 |
| 4 | パス、シンボル、エリアが見つからない |
| 5 | その操作に対応する言語アダプターがない |
| 6 | git の作業ツリーの中ではない |
| 7 | 内部エラー（`--debug` を付けて再実行） |

`--json` は stdout に JSON オブジェクトを 1 つだけ出力し、`"schema_version": "topomark/1"` と `"command"` を付ける。
エラーは `{"error": {"code", "message", "exit", "remediation"}}` を、やはり stdout に出す。`agent-hook` だけは例外で、
Claude Code の hook プロトコルで応答し、終了コードは常に 0。

## 設計メモと、正直な限界

- **ファイルは git から取る。** ディレクトリを走査することはないので、`.gitignore` が除外したものは最初から対象外になる。
- **機密らしいパスは決して読まない**（`.env`、`*.pem`、`keys/`、`credentials*` など）。このリストは無効にできない。
  `doctor` は git が追跡している機密ファイルを警告する。
- **解析は意味ではなく字句のレベル。** アダプターはコメントと文字列を伏せ、スコープを追い、宣言を読む。参照は識別子の一致である。
  そのため `refs` は実際の参照の上位集合になり、`fan-in` は近似値になる。その代わりツールは速く、依存がなく、
  コンパイルできないコードにも耐える。
- **インターフェースのハッシュは本体を無視する。** 関数の中のリファクタリングはレビューを求めないが、新しい公開メソッド、
  変わった定数、書き直したヘッダーコメントはレビューを求める。
- **キャッシュはリポジトリの外に置く**（`$TOPOMARK_CACHE`、`$XDG_CACHE_HOME/topomark`、Windows では
  `%LOCALAPPDATA%\topomark\Cache`、それ以外は `~/.cache/topomark`）。ファイルの mtime とサイズをキーにし、
  アダプターが変わると破棄する。シャードに分けて保存するので、1 ファイルの `outline` は 3,000 ファイルのリポジトリでも
  小さなリポジトリでも同じコストで済み、大きなリポジトリで最初にリポジトリ全体を扱うコマンドはワーカープロセスで
  並列に解析する（`TOPOMARK_JOBS`）。プラグインの hook が使う「セッションごとに一度」の印もここに置く。

## 謝辞

topomark が借りたのは考え方であり、コードではない。重要度順のリポジトリマップは
[Aider の repo map](https://aider.chat/docs/repomap.html)（Apache-2.0）に、シンボル単位のツールは
[Serena](https://github.com/oraios/serena)（GPL-3.0-or-later）にならい、影響範囲の要約は
[GitNexus](https://github.com/abhigyanpatwari/GitNexus) の影響分析から着想を得た（PolyForm Noncommercial、概念のみ）。
**topomark はどのプロジェクトのコードもコピーしていない。** 詳しくは [ACKNOWLEDGMENTS.md](../ACKNOWLEDGMENTS.md) を参照。

## コントリビュート、セキュリティ、ライセンス

[CONTRIBUTING.md](../CONTRIBUTING.md) · [SECURITY.md](../SECURITY.md) · [CHANGELOG.md](../CHANGELOG.md) ·
MIT。[LICENSE](../LICENSE) を参照。Copyright (c) 2026 Li, ching yu.
