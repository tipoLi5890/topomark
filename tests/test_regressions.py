"""Regressions found by the prototype parity run (old prototype surface vs topomark)."""

from __future__ import annotations

import unittest

from tests.harness import SRC  # noqa: F401  (puts src/ on sys.path)
from topomark.lang import registry


class ParityRegressions(unittest.TestCase):
    def test_export_default_expression_is_in_the_surface(self) -> None:
        src = ('import { index, route } from "@react-router/dev/routes";\n\n'
               'export default [\n  index("routes/home.tsx"),\n  route("buy", "routes/buy.tsx"),\n] satisfies RouteConfig;\n')
        before = registry.analyze("app/routes.ts", src).surface
        after = registry.analyze("app/routes.ts", src.replace('  route("buy"', '  route("faq", "routes/faq.tsx"),\n  route("buy"')).surface
        self.assertIn('route("buy", "routes/buy.tsx")', before)
        self.assertNotEqual(before, after, "adding a route must change the surface")

    def test_export_default_call_is_in_the_surface(self) -> None:
        info = registry.analyze("vitest.config.mjs", "export default defineConfig({ test: { setupFiles: ['a.js'] } });\n")
        self.assertIn("defineConfig", info.surface)


if __name__ == "__main__":
    unittest.main()
