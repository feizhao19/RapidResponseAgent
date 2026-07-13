from __future__ import annotations

import unittest
from pathlib import Path

from geoagent.tools.python_env import resolve_vipde_python


class PythonEnvTests(unittest.TestCase):
    def test_resolve_vipde_python(self) -> None:
        try:
            python = resolve_vipde_python()
        except RuntimeError:
            self.skipTest("segment_anything not installed in any candidate env")
        self.assertTrue(Path(python).is_file())


if __name__ == "__main__":
    unittest.main()
