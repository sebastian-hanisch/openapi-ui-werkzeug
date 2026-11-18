import sys
from pathlib import Path

ORDNER = Path(__file__).resolve().parent.parent
if str(ORDNER) not in sys.path:
    sys.path.insert(0, str(ORDNER))
