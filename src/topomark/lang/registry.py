"""Extension → adapter. Adapters are stateless except for per-call scratch, so
one instance per call is cheap and avoids cross-file leakage."""

from __future__ import annotations

from typing import Callable

from .base import FileInfo

_FACTORIES: dict[str, Callable[[], object]] = {}


def _register(exts: tuple[str, ...], factory: Callable[[], object]) -> None:
    for e in exts:
        _FACTORIES[e] = factory


def _load() -> None:
    if _FACTORIES:
        return
    from .cfamily import CFamily
    from .csharp import CSharp, Java
    from .dart import Dart
    from .go import Go
    from .js_ts import JsTs
    from .kotlin import Kotlin
    from .python import Python
    from .rust import Rust
    from .simple import Data, Markdown, Shell, Sql
    from .swift import Swift

    _register((".cs",), CSharp)
    _register((".java",), Java)
    _register((".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"), JsTs)
    _register((".py", ".pyi"), Python)
    _register((".sh", ".bash", ".zsh"), Shell)
    _register((".sql",), Sql)
    _register((".json", ".jsonc", ".json5", ".asmdef", ".asmref", ".toml", ".yaml", ".yml"), Data)
    _register((".md", ".markdown"), Markdown)
    _register((".dart",), Dart)
    _register((".kt", ".kts"), Kotlin)
    _register((".swift",), Swift)
    _register((".go",), Go)
    _register((".rs",), Rust)
    _register((".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".m", ".mm"), CFamily)


def adapter_for(path: str) -> object:
    _load()
    from .simple import Plain

    low = path.lower()
    dot = low.rfind(".")
    ext = low[dot:] if dot > low.rfind("/") else ""
    factory = _FACTORIES.get(ext)
    return factory() if factory else Plain()


def supported_extensions() -> list[str]:
    _load()
    return sorted(_FACTORIES)


def analyze(path: str, text: str) -> FileInfo:
    return adapter_for(path).analyze(path, text)  # type: ignore[attr-defined]
