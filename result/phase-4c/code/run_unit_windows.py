"""Run the existing Python suite where TCP loopback is unavailable on Windows."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import unittest


def run(root):
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


if __name__ == "__main__":
    support = str(Path(__file__).resolve().with_name("windows_test_support"))
    sys.path.insert(0, support)
    os.environ["PYTHONPATH"] = os.pathsep.join(
        filter(None, (support, os.environ.get("PYTHONPATH")))
    )
    from sitecustomize import install

    install()
    root = Path(__file__).resolve().parents[3]
    with ThreadPoolExecutor(max_workers=1) as pool:
        passed = pool.submit(run, root).result()
    raise SystemExit(int(not passed))
