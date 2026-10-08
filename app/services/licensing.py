"""
Licença por código — sem banco de dados.

Cada código é "GDP-<id>-<assinatura>", onde a assinatura é um HMAC-SHA256 do id
feito com a SECRET_KEY. Assim qualquer servidor com a mesma chave consegue
validar um código sem guardar nada, e ninguém consegue inventar códigos sem
conhecer a chave. Para cancelar um código (reembolso), coloque ele em
REVOKED_CODES.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "GDP"
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I para evitar confusão ao digitar


def _sign(code_id: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), f"{PREFIX}-{code_id}".encode(), hashlib.sha256).digest()
    n = int.from_bytes(digest[:8], "big")
    out = []
    for _ in range(8):
        n, r = divmod(n, len(_ALPHABET))
        out.append(_ALPHABET[r])
    return "".join(out)


def generate_code(secret: str) -> str:
    code_id = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    sig = _sign(code_id, secret)
    return f"{PREFIX}-{code_id[:4]}-{code_id[4:]}-{sig[:4]}-{sig[4:]}"


def normalize(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def is_valid_code(code: str, secret: str, revoked: set[str] | None = None) -> bool:
    if not secret:
        return False
    code = normalize(code)
    if revoked and code in revoked:
        return False
    parts = code.split("-")
    if len(parts) != 5 or parts[0] != PREFIX:
        return False
    code_id = parts[1] + parts[2]
    given_sig = parts[3] + parts[4]
    if len(code_id) != 8 or len(given_sig) != 8:
        return False
    return hmac.compare_digest(_sign(code_id, secret), given_sig)
