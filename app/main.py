"""
Gerador de Dashboard — ponto de entrada da aplicação FastAPI.

Fluxo:
    1. GET  /          -> tela de upload (exige licença quando LICENSE_REQUIRED=true)
    2. POST /upload    -> lê o arquivo, analisa os dados e renderiza o dashboard
    3. GET  /acesso    -> tela para digitar o código de licença
    4. GET  /privacidade, /health

Para rodar localmente:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import secrets
import time

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import (
    ALLOWED_EXTENSIONS,
    BASE_DIR,
    BRAND_NAME,
    BRAND_TAGLINE,
    LICENSE_REQUIRED,
    MAX_UPLOAD_SIZE,
    PURCHASE_URL,
    RATE_LIMIT_ACCESS_PER_MIN,
    RATE_LIMIT_UPLOADS_PER_MIN,
    REVOKED_CODES,
    SECRET_KEY,
    SESSION_DAYS,
    SUPPORT_EMAIL,
    _env_bool,
)
from app.services.data_analyzer import analyze
from app.services.file_reader import FileReadError, read_uploaded_file
from app.services.licensing import is_valid_code, normalize
from app.services.security import RateLimiter, apply_security_headers, client_ip, validate_file_content

if LICENSE_REQUIRED and len(SECRET_KEY) < 16:
    raise RuntimeError(
        "LICENSE_REQUIRED=true exige SECRET_KEY com pelo menos 16 caracteres "
        "(defina nas variáveis de ambiente do servidor)."
    )

app = FastAPI(title=BRAND_NAME, version="1.1.0", docs_url=None, redoc_url=None, openapi_url=None)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Disponíveis em todos os templates sem precisar passar em cada TemplateResponse —
# é o que permite trocar o nome/tagline da marca em um único lugar (config.py).
templates.env.globals["BRAND_NAME"] = BRAND_NAME
templates.env.globals["BRAND_TAGLINE"] = BRAND_TAGLINE
templates.env.globals["PURCHASE_URL"] = PURCHASE_URL
templates.env.globals["SUPPORT_EMAIL"] = SUPPORT_EMAIL
templates.env.globals["LICENSE_REQUIRED"] = LICENSE_REQUIRED

limiter = RateLimiter(window_seconds=60)

# Rotas que não pedem licença (o resto pede quando LICENSE_REQUIRED=true).
_PUBLIC_PATHS = {"/health", "/acesso", "/sair", "/privacidade"}


def _has_license(request: Request) -> bool:
    code = request.session.get("license")
    return bool(code) and is_valid_code(code, SECRET_KEY, REVOKED_CODES)


# --- Middlewares: o último adicionado é o mais externo --------------------------
@app.middleware("http")
async def license_gate(request: Request, call_next):
    path = request.url.path
    if LICENSE_REQUIRED and path not in _PUBLIC_PATHS and not path.startswith("/static/"):
        if not _has_license(request):
            return RedirectResponse("/acesso", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    apply_security_headers(response)
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY or secrets.token_urlsafe(32),
    session_cookie="gd_session",
    max_age=SESSION_DAYS * 24 * 3600,
    same_site="lax",
    https_only=_env_bool("COOKIE_SECURE", LICENSE_REQUIRED),
)


# --- Páginas ----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse(request, "upload.html", {"show_logout": LICENSE_REQUIRED})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/privacidade", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacidade.html", {})


@app.get("/acesso", response_class=HTMLResponse)
async def access_page(request: Request):
    if not LICENSE_REQUIRED or _has_license(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "acesso.html", {})


@app.post("/acesso", response_class=HTMLResponse)
async def access_submit(request: Request, code: str = Form("")):
    if not LICENSE_REQUIRED:
        return RedirectResponse("/", status_code=303)

    if not limiter.allow(f"acesso:{client_ip(request)}", RATE_LIMIT_ACCESS_PER_MIN):
        return templates.TemplateResponse(
            request, "acesso.html",
            {"error": "Muitas tentativas. Aguarde um minuto e tente de novo."},
            status_code=429,
        )

    if not is_valid_code(code, SECRET_KEY, REVOKED_CODES):
        return templates.TemplateResponse(
            request, "acesso.html",
            {"error": "Código inválido ou cancelado. Confira se digitou igual ao que você recebeu."},
            status_code=401,
        )

    request.session["license"] = normalize(code)
    return RedirectResponse("/", status_code=303)


@app.get("/sair")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/acesso" if LICENSE_REQUIRED else "/", status_code=303)


# --- Upload -----------------------------------------------------------------
def _upload_error(request: Request, message: str, status_code: int = 400):
    return templates.TemplateResponse(
        request, "upload.html", {"error": message, "show_logout": LICENSE_REQUIRED}, status_code=status_code
    )


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    if not limiter.allow(f"upload:{client_ip(request)}", RATE_LIMIT_UPLOADS_PER_MIN):
        return _upload_error(request, "Muitos envios em sequência. Aguarde um minuto e tente de novo.", 429)

    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        return _upload_error(request, f"Formato '{ext or filename}' não suportado. Use .csv, .xlsx, .xls ou .pdf.")

    # Lê no máximo o limite + 1 byte: se passou, rejeita sem carregar o resto na memória.
    content = await file.read(MAX_UPLOAD_SIZE + 1)

    if len(content) > MAX_UPLOAD_SIZE:
        return _upload_error(request, f"Arquivo muito grande. O limite é {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.", 413)

    content_error = validate_file_content(ext, content)
    if content_error:
        return _upload_error(request, content_error)

    start = time.perf_counter()
    try:
        df, reader_warnings = read_uploaded_file(filename, content)
        dashboard = analyze(df)
        dashboard.warnings = reader_warnings + dashboard.warnings
    except FileReadError as exc:
        return _upload_error(request, str(exc))
    except Exception as exc:  # noqa: BLE001 - nunca deixar o usuário ver um 500 "cru"
        return _upload_error(
            request, f"Não consegui processar esse arquivo ({str(exc)[:200]}). Tente exportá-lo como CSV."
        )
    elapsed_ms = round((time.perf_counter() - start) * 1000)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "filename": filename,
            "elapsed_ms": elapsed_ms,
            "dashboard": dashboard,
            "show_logout": LICENSE_REQUIRED,
        },
    )
