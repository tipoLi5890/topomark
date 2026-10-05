# Acknowledgments

topomark stands on ideas from these projects. **It copies no code from any of them**; everything
here is an independent implementation on the Python standard library.

## Design references

| Project | License | What topomark took |
|---|---|---|
| [Aider](https://github.com/Aider-AI/aider), its [repo map](https://aider.chat/docs/repomap.html) | Apache-2.0 | The idea of a ranked repository map: rank files by a PageRank over the reference graph, show their most important signatures, stop at a token budget (`topomark map`). |
| [Serena](https://github.com/oraios/serena) | MIT | Symbol-level tools for agents: outline a file, read one symbol by name path, find references, instead of reading whole files (`outline`, `symbol`, `find`, `refs`). |
| [GitNexus](https://github.com/abhigyanpatwari/GitNexus) | PolyForm Noncommercial 1.0.0 | The concept of a one-shot impact summary before an edit (callers, affected areas, tests). **Concepts only**: no code, text or data from GitNexus is used, and topomark's implementation (`impact`) is unrelated to it. |

## Origin

topomark generalises an in-repo prototype written for one of the author's projects (a Python script
plus a Traditional Chinese L0/L1 code map with per-file review stamps).

## Tooling (CI only, not shipped)

- [ruff](https://github.com/astral-sh/ruff) (MIT) for linting.
- [mypy](https://github.com/python/mypy) (MIT) for type checking.
