"""Stable output for the executable evidence document; failures keep their full diagnostics."""

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
suite = unittest.defaultTestLoader.discover(
    str(Path(__file__).parent), pattern="test_*.py"
)
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
if not result.wasSuccessful():
    print(stream.getvalue())
    raise SystemExit(1)
print(
    f"PASS: {result.testsRun} relay, isolation, recovery and independent-worker checks"
)
