"""
Proteções para rodar o sistema aberto na internet:
  - limite de requisições por IP (anti-abuso e anti força-bruta nos códigos)
  - validação do conteúdo real do arquivo (não só a extensão)
  - cabeçalhos de segurança HTTP
"""
from __future__ import annotations

import io
import time
import zipfile
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import MAX_UNCOMPRESSED_SIZE


class RateLimiter:
    """Janela deslizante em memória (1 processo). Suficiente para um único container."""

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        # limpeza ocasional para a tabela não crescer sem limite
        if len(self._hits) > 5000:
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                self._hits.pop(k, None)
        return True


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


_XLSX_MAGIC = b"PK\x03\x04"
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"


def validate_file_content(ext: str, content: bytes) -> str | None:
    """Devolve uma mensagem de erro (str) se o conteúdo não bate com a extensão; None se ok."""
    if not content:
        return "O arquivo está vazio."

    if ext in {".xlsx", ".xls"}:
        if content.startswith(_XLSX_MAGIC):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    total = sum(i.file_size for i in zf.infolist())
            except zipfile.BadZipFile:
                return "O arquivo Excel está corrompido ou não é um Excel de verdade."
            if total > MAX_UNCOMPRESSED_SIZE:
                return "Esse arquivo Excel é grande demais depois de descompactado."
            return None
        if content.startswith(_XLS_MAGIC):
            return None
        return "O conteúdo não parece ser uma planilha Excel (.xlsx/.xls) de verdade."

    if ext == ".pdf":
        return None if content[:1024].lstrip().startswith(b"%PDF") else "O conteúdo não parece ser um PDF de verdade."

    if ext == ".csv":
        return "O conteúdo não parece ser um CSV de texto." if b"\x00" in content[:8192] else None

    return "Formato não suportado."


def apply_security_headers(response) -> None:
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    h.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'",
    )
    h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
