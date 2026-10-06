import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PLANOVAC_DATA", str(ROOT / ".pytest_cache" / "data"))
