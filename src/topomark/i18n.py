"""Strings that end up inside generated documents (not CLI messages, which are English).
The project's ``lang`` picks the table; missing keys fall back to English."""

from __future__ import annotations

_T = {
    "en": {
        "fanin.title": "# C# / code fan-in (generated, do not edit; approximate)",
        "fanin.intro": ("Production fan-in = how many non-test files mention a name this file declares (coupling: "
                        "the callers to check when you change it). Test fan-in = how many test files mention it "
                        "(guard rails). Cross-area = which other code-map areas the production callers live in."),
        "fanin.rules": ("Only top-level declarations count. Names shorter than {min} characters (except {keep}) and "
                        "names declared in more than one file (unless partial) are ignored; see the end of this file. "
                        "Test files only ever reference."),
        "fanin.header": "| prod | test | file | area | cross-area callers |",
        "fanin.excluded": "Names not counted ({short} short, {amb} declared in several files):",
        "fanin.tests_title": "## Test file → production files it mentions",
        "fanin.tests_header": "| test file | count | production files (by fan-in) |",
        "fanin.more": "… {n} more",
        "modules.title": "# Module graph (generated, do not edit)",
        "modules.asmdef": "## Unity assembly definitions",
        "modules.asmdef_header": "| assembly | file | depends on | used by | notes |",
        "modules.npm": "## npm packages in this repo",
        "modules.npm_header": "| package | file | depends on (in repo) | used by (in repo) |",
        "modules.none": "(no module manifests found)",
        "modules.pure": "pure C#",
        "modules.only": "only {p}",
    },
    "zh-Hant": {
        "fanin.title": "# 扇入表（產生檔，勿手改；近似值）",
        "fanin.intro": ("「正式扇入」= 有多少個正式程式檔提到這個檔案宣告的名字（耦合，改它要看的呼叫端數）；"
                        "「測試扇入」= 有多少個測試檔提到它（護欄）。「跨區」= 正式呼叫端分布在哪些其他 code map 區。"),
        "fanin.rules": ("只計頂層宣告。短於 {min} 字元（{keep} 除外）、或在多個檔案重複宣告（partial 除外）的名字不計，"
                        "見表尾。測試檔只算引用方。"),
        "fanin.header": "| 正式扇入 | 測試扇入 | 檔案 | 區 | 跨區呼叫端 |",
        "fanin.excluded": "不計入的名字（短名 {short} 個、重複宣告 {amb} 個）：",
        "fanin.tests_title": "## 測試檔 → 它提到的正式檔",
        "fanin.tests_header": "| 測試檔 | 數量 | 正式檔（依扇入排序） |",
        "fanin.more": "…（另 {n} 個）",
        "modules.title": "# 模組依賴圖（產生檔，勿手改）",
        "modules.asmdef": "## Unity 組件（asmdef）",
        "modules.asmdef_header": "| 組件 | 檔案 | 依賴（往下） | 被誰依賴（往上） | 備註 |",
        "modules.npm": "## repo 內的 npm 套件",
        "modules.npm_header": "| 套件 | 檔案 | 依賴（repo 內） | 被誰依賴（repo 內） |",
        "modules.none": "（找不到模組資訊清單）",
        "modules.pure": "純 C#",
        "modules.only": "只在 {p}",
    },
}
_T["zh-Hans"] = _T["zh-Hant"]


def t(lang: str, key: str, **kw: object) -> str:
    table = _T.get(lang) or _T["en"]
    s = table.get(key) or _T["en"][key]
    return s.format(**kw) if kw else s
