# main.py — ponto de entrada do executável
# Coloque este arquivo na raiz do projeto (mesmo nível que configs/)
from __future__ import annotations

import sys
from pathlib import Path

# Garante que o src/ seja encontrado quando rodando como .exe
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_PATH = BASE_DIR / "configs" / "default.yaml"

from xauusd_ia_trader.gui import launch_gui  # noqa: E402

launch_gui(CONFIG_PATH)
