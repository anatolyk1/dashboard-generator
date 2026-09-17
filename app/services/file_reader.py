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
import re
from pathlib import Path

import pandas as pd
import pdfplumber

# Nome de aba que parece um mês (ex.: "JAN25", "FEV/25", "AGO 2024") — usado
# para detectar planilhas com uma aba por mês/período, um padrão comum em
# controles financeiros pessoais. Só combinamos abas assim automaticamente
# quando o NOME da aba deixa claro que é um período (e não, por exemplo, uma
# aba de resumo/consolidado, que já soma outras abas e duplicaria valores).
_MONTH_TAB_RE = re.compile(
    r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*[\-/]?\s*(\d{2}|\d{4})$",
    re.IGNORECASE,
)


class FileReadError(Exception):
    """Erro amigável para exibir ao usuário quando o arquivo não pode ser lido."""


def read_uploaded_file(filename: str, content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """
    Ponto de entrada único: recebe o nome do arquivo e os bytes, devolve um
    DataFrame e uma lista de avisos (ex.: "encontrei 3 abas, usei a X") para
    mostrar no dashboard.

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

    df, warnings = reader(content)

    if df is None or df.empty:
        raise FileReadError(
            "Não encontrei dados utilizáveis nesse arquivo. "
            "Verifique se ele tem ao menos uma linha de cabeçalho e uma linha de dados."
        )

    # Normaliza nomes de coluna: remove espaços nas pontas e colunas totalmente vazias
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")

    return df.reset_index(drop=True), warnings


def _read_csv(content: bytes) -> tuple[pd.DataFrame, list[str]]:
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
        return pd.read_csv(io.StringIO(text), sep=None, engine="python"), []
    except Exception as exc:  # noqa: BLE001 - queremos uma mensagem amigável única
        raise FileReadError(f"Erro ao ler o CSV: {exc}") from exc


def _read_excel(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """
    Lê um arquivo Excel — inclusive quando ele tem várias abas/planilhas.

    Estratégia (da mais específica pra mais genérica):
      1. 1 aba só (ou só uma com dados): comportamento de sempre.
      2. Várias abas cujo NOME é claramente um mês/período (ex.: "JAN25",
         "FEV/25", "AGO 2024") — comum em planilhas de controle financeiro
         pessoal com uma aba por mês. Junta essas abas em uma tabela só, com
         uma coluna "Mês" pra identificar a origem de cada linha, e ignora de
         propósito abas de resumo/consolidado (ex.: "MENSAL 2025",
         "SEMANADIA") — juntar essas também somaria os mesmos valores duas
         vezes. Essas abas costumam não ter cabeçalho de coluna de verdade
         (célula A1 já é dado), então lemos por posição em vez de por nome de
         coluna, pra não perder colunas por causa da linha errada virar
         "cabeçalho".
      3. Várias abas com as MESMAS colunas (mesmo cabeçalho): junta todas,
         mantendo o nome da aba de origem em uma coluna extra "Aba".
      4. Várias abas com colunas diferentes e sem padrão de mês: usa a maior
         delas (mais linhas x colunas) — mesma ideia já usada para escolher a
         melhor tabela dentro de um PDF com várias tabelas — e avisa quais
         abas ficaram de fora.
    """
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    except Exception as exc:  # noqa: BLE001
        raise FileReadError(f"Erro ao ler a planilha Excel: {exc}") from exc

    non_empty = {
        name: sheet_df for name, sheet_df in sheets.items()
        if sheet_df is not None and not sheet_df.dropna(how="all").empty
    }

    if not non_empty:
        return None, []

    if len(non_empty) == 1:
        return next(iter(non_empty.values())), []

    warnings: list[str] = []

    # ---- Caso 2: abas nomeadas por mês/período ---------------------------
    month_names = [name for name in non_empty if _MONTH_TAB_RE.match(name.strip())]
    if len(month_names) >= 2:
        # Relê só essas abas sem tratar nenhuma linha como cabeçalho — assim
        # as colunas ficam alinhadas por posição (0, 1, 2, ...) entre meses
        # com quantidade de colunas ligeiramente diferente, em vez de virarem
        # "Unnamed: N" por causa de uma célula de dado que calhou de cair na
        # primeira linha.
        try:
            month_sheets_raw = pd.read_excel(
                io.BytesIO(content), sheet_name=month_names, header=None
            )
        except Exception as exc:  # noqa: BLE001
            raise FileReadError(f"Erro ao ler a planilha Excel: {exc}") from exc

        combined = pd.concat(
            [
                sheet_df.assign(Mês=name)
                for name, sheet_df in month_sheets_raw.items()
                if not sheet_df.dropna(how="all").empty
            ],
            ignore_index=True,
        )

        left_out = [name for name in non_empty if name not in month_names]
        msg = (
            f"Este arquivo tem {len(month_names)} abas de meses/períodos "
            f"({', '.join(month_names)}) — juntei todas em uma única tabela "
            "(coluna \"Mês\" indica de qual aba cada linha veio), já que essas "
            "abas não têm cabeçalho de coluna, os dados são identificados pela posição."
        )
        if left_out:
            msg += (
                f" Deixei de fora as abas ({', '.join(left_out)}) porque parecem ser "
                "resumos/consolidados — juntar elas também somaria os mesmos valores de novo."
            )
        warnings.append(msg)
        return combined, warnings

    # ---- Caso 3: mesmas colunas em todas as abas --------------------------
    column_sets = {tuple(sheet_df.columns) for sheet_df in non_empty.values()}

    if len(column_sets) == 1:
        combined = pd.concat(
            [sheet_df.assign(Aba=name) for name, sheet_df in non_empty.items()],
            ignore_index=True,
        )
        warnings.append(
            f"Este arquivo tem {len(non_empty)} abas com a mesma estrutura de colunas — "
            "combinei todas em uma única tabela (coluna \"Aba\" indica a origem de cada linha)."
        )
        return combined, warnings

    # ---- Caso 4: abas diferentes, sem padrão reconhecível -----------------
    best_name, best_df = max(non_empty.items(), key=lambda kv: kv[1].shape[0] * kv[1].shape[1])
    other_names = [name for name in non_empty if name != best_name]
    warnings.append(
        f"Este arquivo tem {len(non_empty)} abas com estruturas diferentes — usei a maior "
        f"delas (\"{best_name}\") para montar o dashboard. As outras "
        f"({', '.join(other_names)}) foram ignoradas porque têm colunas diferentes; "
        "se quiser tudo junto, deixe as abas com as mesmas colunas ou envie uma por vez."
    )
    return best_df, warnings


def _read_pdf(content: bytes) -> tuple[pd.DataFrame, list[str]]:
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

    return df, []
