from __future__ import annotations

import sys
from pathlib import Path


# Keep the repository root importable so `pytest` works without manual PYTHONPATH setup.
REPO_ROOT = Path(__file__).resolve().parent
repo_root_str = str(REPO_ROOT)
if repo_root_str not in sys.path:
    sys.path.insert(0, repo_root_str)
