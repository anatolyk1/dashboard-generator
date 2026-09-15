"""
Camada de leitura de arquivos.

Responsável por transformar um arquivo enviado pelo usuário (CSV, XLSX/XLS ou PDF)
em um pandas DataFrame "bruto", sem nenhuma análise ainda — isso é feito depois
pelo data_analyzer.

Mantemos essa camada isolada porque, no futuro, adicionar suporte a um novo
formato (ex: .json, .txt) significa só criar uma nova função `_read_xxx` e
registrá-la no dicionário de leitores.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pdfplumber


class FileReadError(Exception):
    """Erro amigável para exibir ao usuário quando o arquivo não pode ser lido."""


def read_uploaded_file(filename: str, content: bytes) -> pd.DataFrame:
    """
    Ponto de entrada único: recebe o nome do arquivo e os bytes, devolve um DataFrame.

    Levanta FileReadError com uma mensagem clara quando algo dá errado
    (formato não suportado, arquivo vazio, PDF sem tabela, etc).
    """
    ext = Path(filename).suffix.lower()

    readers = {
        ".csv": _read_csv,
        ".xlsx": _read_excel,
        ".xls": _read_excel,
        ".pdf": _read_pdf,
    }

    reader = readers.get(ext)
    if reader is None:
        raise FileReadError(
            f"Formato '{ext}' não suportado. Envie um arquivo .csv, .xlsx, .xls ou .pdf."
        )

    df = reader(content)

    if df is None or df.empty:
        raise FileReadError(
            "Não encontrei dados utilizáveis nesse arquivo. "
            "Verifique se ele tem ao menos uma linha de cabeçalho e uma linha de dados."
        )

    # Normaliza nomes de coluna: remove espaços nas pontas e colunas totalmente vazias
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")

    return df.reset_index(drop=True)


def _read_csv(content: bytes) -> pd.DataFrame:
    # Tenta detectar automaticamente o separador (',' ou ';', comum em exports pt-BR)
    # e o encoding (utf-8 primeiro, depois latin-1 como fallback).
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileReadError("Não consegui identificar a codificação do arquivo CSV.")

    try:
        return pd.read_csv(io.StringIO(text), sep=None, engine="python")
    except Exception as exc:  # noqa: BLE001 - queremos uma mensagem amigável única
        raise FileReadError(f"Erro ao ler o CSV: {exc}") from exc


def _read_excel(content: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        raise FileReadError(f"Erro ao ler a planilha Excel: {exc}") from exc


def _read_pdf(content: bytes) -> pd.DataFrame:
    """
    Extrai a maior tabela encontrada no PDF.

    Estratégia: percorre todas as páginas, usa pdfplumber.extract_tables() em cada
    uma e fica com a tabela que tiver mais células (linhas x colunas). Isso cobre
    bem relatórios/extratos exportados como PDF com layout de tabela.
    """
    best_table: list[list] | None = None
    best_score = 0

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    score = len(table) * len(table[0])
                    if score > best_score:
                        best_score = score
                        best_table = table
    except Exception as exc:  # noqa: BLE001
        raise FileReadError(f"Erro ao abrir o PDF: {exc}") from exc

    if best_table is None:
        raise FileReadError(
            "Não encontrei nenhuma tabela dentro do PDF. "
            "Este leitor funciona melhor com relatórios/extratos que têm dados em "
            "formato de tabela. Se possível, exporte o arquivo como CSV ou Excel."
        )

    header, *rows = best_table
    header = [str(h).strip() if h else f"Coluna {i + 1}" for i, h in enumerate(header)]
    df = pd.DataFrame(rows, columns=header)

    # Remove linhas totalmente vazias que o extrator de PDF às vezes gera
    df = df.replace(r"^\s*$", pd.NA, regex=True)
    df = df.dropna(how="all")

    return df
