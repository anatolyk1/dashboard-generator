"""
Gera códigos de licença para vender (ex.: colar na área de membros da Hotmart).

Uso:
    SECRET_KEY="a-mesma-chave-do-railway" python scripts/gerar_codigos.py 20

A SECRET_KEY precisa ser IGUAL à configurada no servidor, senão os códigos
não vão ser aceitos.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.licensing import generate_code  # noqa: E402

secret = os.getenv("SECRET_KEY", "")
if len(secret) < 16:
    sys.exit("Defina SECRET_KEY (mínimo 16 caracteres) — a mesma usada no servidor.")

quantidade = int(sys.argv[1]) if len(sys.argv) > 1 else 1
for _ in range(quantidade):
    print(generate_code(secret))
