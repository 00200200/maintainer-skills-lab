"""Run the independent test in a child process and report failures vs errors."""

import contextlib
import io
import json
import unittest
from pathlib import Path


def main():
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            import slug
            import test_slug

            if Path(slug.__file__).resolve() != Path("slug.py").resolve():
                raise RuntimeError("Test imported a different slug module")
            suite = unittest.defaultTestLoader.loadTestsFromModule(test_slug)
            result = unittest.TextTestRunner(stream=stderr, verbosity=2).run(suite)
        payload = {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "successful": result.wasSuccessful(),
            "source_file": "slug.py",
            "details": stderr.getvalue(),
            "stdout": stdout.getvalue(),
        }
    except Exception as exc:
        # Import/runtime failures in the fixture are a reportable outcome.
        payload = {
            "tests_run": 0,
            "failures": 0,
            "errors": 1,
            "skipped": 0,
            "successful": False,
            "details": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
