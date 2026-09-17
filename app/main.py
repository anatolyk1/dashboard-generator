"""
Gerador de Dashboard — ponto de entrada da aplicação FastAPI.

Fluxo:
    1. GET  /         -> tela de upload
    2. POST /upload    -> lê o arquivo, analisa os dados e renderiza o dashboard
    3. GET  /health     -> healthcheck simples (útil para deploy)

Para rodar localmente:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import time

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.config import (
    ALLOWED_EXTENSIONS,
    BASE_DIR,
    BRAND_NAME,
    BRAND_TAGLINE,
    MAX_UPLOAD_SIZE,
)
from app.services.data_analyzer import analyze
from app.services.file_reader import FileReadError, read_uploaded_file

app = FastAPI(title=BRAND_NAME, version="1.0.0")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Disponíveis em todos os templates sem precisar passar em cada TemplateResponse —
# é o que permite trocar o nome/tagline da marca em um único lugar (config.py).
templates.env.globals["BRAND_NAME"] = BRAND_NAME
templates.env.globals["BRAND_TAGLINE"] = BRAND_TAGLINE


@app.get("/", response_class=HTMLResponse)
async def upload_page(request: Request):
    return templates.TemplateResponse(request, "upload.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"error": f"Formato '{ext or file.filename}' não suportado. Use .csv, .xlsx, .xls ou .pdf."},
            status_code=400,
        )

    content = await file.read()

    if len(content) > MAX_UPLOAD_SIZE:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"error": f"Arquivo muito grande. O limite é {MAX_UPLOAD_SIZE // (1024 * 1024)} MB."},
            status_code=400,
        )

    start = time.perf_counter()
    try:
        df, reader_warnings = read_uploaded_file(file.filename, content)
        dashboard = analyze(df)
        dashboard.warnings = reader_warnings + dashboard.warnings
    except FileReadError as exc:
        return templates.TemplateResponse(
            request, "upload.html", {"error": str(exc)}, status_code=400
        )
    except Exception as exc:  # noqa: BLE001 - nunca deixar o usuário ver um 500 "cru"
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"error": f"Não consegui processar esse arquivo ({exc}). Tente exportá-lo como CSV."},
            status_code=400,
        )
    elapsed_ms = round((time.perf_counter() - start) * 1000)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "filename": file.filename,
            "elapsed_ms": elapsed_ms,
            "dashboard": dashboard,
        },
    )
