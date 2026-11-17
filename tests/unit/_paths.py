"""Caminhos usados pelos testes (o projeto fica uma pasta acima de tests/)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AIROOTFS = REPO / "airootfs"
LIB = AIROOTFS / "usr/lib/lainos"
BIN = AIROOTFS / "usr/local/bin"

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
