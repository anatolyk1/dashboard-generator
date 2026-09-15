"""
Motor de análise automática.

Recebe um DataFrame "bruto" (vindo do file_reader) e devolve uma estrutura
já pronta para o dashboard: tipos de coluna detectados, KPIs, séries para
gráficos, uma amostra dos dados e um payload "enxuto" (`records`) que o
JavaScript do dashboard usa para refiltrar tudo no navegador, sem precisar
voltar ao servidor a cada clique.

A ideia central é NÃO exigir que o usuário diga quais colunas são o quê —
o sistema tenta descobrir sozinho:
  - qual coluna é data
  - quais colunas são numéricas (mesmo que estejam formatadas como "R$ 1.234,56")
  - quais colunas são categóricas (bons candidatos para agrupar/comparar/filtrar)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from app.core.config import MAX_INTERACTIVE_ROWS, PREVIEW_ROWS, TOP_N_CATEGORIES

# Palavras-chave usadas para priorizar qual coluna numérica/data é a "principal"
# quando existe mais de uma candidata.
_VALUE_KEYWORDS = ("valor", "total", "receita", "preco", "preço", "faturamento", "amount", "price", "revenue")
_DATE_KEYWORDS = ("data", "date", "dia", "periodo", "período", "mes", "mês")

_CURRENCY_CHARS = re.compile(r"[R$€£\s%]")


@dataclass
class ColumnProfile:
    name: str
    kind: str  # "date" | "numeric" | "categorical" | "text"


@dataclass
class DashboardData:
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    kpis: list[dict] = field(default_factory=list)
    time_series: dict | None = None
    category_breakdown: dict | None = None
    numeric_summary: list[dict] = field(default_factory=list)
    preview_columns: list[str] = field(default_factory=list)
    preview_rows: list[list] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ---- suporte ao filtro interativo no navegador ------------------------
    primary_numeric: str | None = None
    primary_category: str | None = None
    has_date: bool = False
    numeric_columns: list[str] = field(default_factory=list)
    interactive: bool = False
    records: list[dict] = field(default_factory=list)


def _try_parse_numeric(series: pd.Series) -> pd.Series | None:
    """
    Tenta converter uma coluna (possivelmente texto) em números.

    Trata formatos comuns em planilhas brasileiras: "R$ 1.234,56", "12,5%",
    espaços, etc. Retorna None se a coluna não parecer numérica.
    """
    if pd.api.types.is_numeric_dtype(series):
        return series

    # pandas 3.x passou a usar um dtype "str" nativo (não mais "object") para
    # colunas de texto por padrão — aceitamos os dois casos.
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return None

    cleaned = series.astype(str).str.strip()
    non_empty = cleaned[cleaned.ne("") & cleaned.str.lower().ne("nan")]
    if non_empty.empty:
        return None

    stripped = non_empty.apply(lambda v: _CURRENCY_CHARS.sub("", v))

    # Formato pt-BR: "1.234,56" -> "1234.56"
    def normalize(value: str) -> str:
        if "," in value and "." in value:
            # último separador decide qual é o decimal
            if value.rfind(",") > value.rfind("."):
                value = value.replace(".", "").replace(",", ".")
            else:
                value = value.replace(",", "")
        elif "," in value:
            value = value.replace(",", ".")
        return value

    normalized = stripped.apply(normalize)
    converted = pd.to_numeric(normalized, errors="coerce")

    # Só aceitamos a coluna como numérica se conseguirmos converter a maioria dos valores
    success_rate = converted.notna().sum() / len(converted)
    if success_rate < 0.8:
        return None

    result = pd.to_numeric(
        series.astype(str).str.strip().apply(lambda v: normalize(_CURRENCY_CHARS.sub("", v))),
        errors="coerce",
    )
    return result


def _try_parse_date(series: pd.Series, column_name: str) -> pd.Series | None:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series

    if series.dtype != object and not pd.api.types.is_string_dtype(series):
        return None

    sample = series.dropna().astype(str).head(50)
    if sample.empty:
        return None

    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True)
    success_rate = parsed.notna().sum() / max(series.notna().sum(), 1)

    name_hints_date = any(k in column_name.lower() for k in _DATE_KEYWORDS)

    threshold = 0.6 if name_hints_date else 0.9
    if success_rate < threshold:
        return None
    return parsed


def _profile_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[ColumnProfile]]:
    """
    Detecta o tipo de cada coluna e devolve um novo DataFrame com as colunas
    já convertidas (datas como datetime, números como float).
    """
    working = df.copy()
    profiles: list[ColumnProfile] = []

    for col in working.columns:
        date_parsed = _try_parse_date(working[col], col)
        if date_parsed is not None:
            working[col] = date_parsed
            profiles.append(ColumnProfile(col, "date"))
            continue

        numeric_parsed = _try_parse_numeric(working[col])
        if numeric_parsed is not None:
            working[col] = numeric_parsed
            profiles.append(ColumnProfile(col, "numeric"))
            continue

        nunique = working[col].nunique(dropna=True)
        if 0 < nunique <= max(TOP_N_CATEGORIES * 4, 30) and nunique < len(working) * 0.8:
            profiles.append(ColumnProfile(col, "categorical"))
        else:
            profiles.append(ColumnProfile(col, "text"))

    return working, profiles


def _pick_primary(profiles: list[ColumnProfile], kind: str, keywords: tuple[str, ...]) -> str | None:
    candidates = [p.name for p in profiles if p.kind == kind]
    if not candidates:
        return None
    for candidate in candidates:
        if any(k in candidate.lower() for k in keywords):
            return candidate
    return candidates[0]


#  Alias de período (usado em .dt.to_period, estável) vs. alias de offset
#  (usado em .resample — pandas >= 2.2 pede "ME" no lugar de "M" para fim de mês).
_RESAMPLE_ALIAS = {"D": "D", "W": "W", "M": "ME"}


def _pick_freq_and_format(dates: pd.Series) -> tuple[str, str]:
    span_days = (dates.max() - dates.min()).days
    freq = "D" if span_days <= 60 else ("W" if span_days <= 400 else "M")
    label_fmt = "%d/%m/%Y" if freq == "D" else ("Semana %d/%m/%y" if freq == "W" else "%m/%Y")
    return freq, label_fmt


def _bucket_timestamps(dates: pd.Series, freq: str) -> pd.Series:
    """
    Calcula, para cada linha, o início do "balde" de tempo (dia/semana/mês) ao
    qual ela pertence — usando exatamente a mesma convenção de ancoragem que
    o `.resample()` usa para agrupar o gráfico. Isso garante que o rótulo
    calculado aqui, linha a linha, bata com os rótulos do gráfico (essencial
    para o filtro no navegador conseguir re-somar por balde).

    Semanas usam a mesma âncora de `.resample('W')` (semana terminando no
    domingo); dia e mês só mostram a própria data / mês-ano no rótulo final,
    então não há ambiguidade de borda para eles.
    """
    if freq == "W":
        return dates.dt.to_period("W-SUN").dt.end_time.dt.normalize()
    if freq == "M":
        return dates.dt.to_period("M").dt.start_time
    return dates.dt.normalize()


def analyze(df: pd.DataFrame) -> DashboardData:
    working, profiles = _profile_columns(df)

    numeric_cols = [p.name for p in profiles if p.kind == "numeric"]
    date_cols = [p.name for p in profiles if p.kind == "date"]
    categorical_cols = [p.name for p in profiles if p.kind == "categorical"]

    warnings: list[str] = []

    data = DashboardData(
        row_count=len(working),
        column_count=len(working.columns),
        columns=profiles,
        numeric_columns=numeric_cols,
    )

    primary_numeric = _pick_primary(profiles, "numeric", _VALUE_KEYWORDS)
    primary_date = _pick_primary(profiles, "date", _DATE_KEYWORDS)
    primary_category = categorical_cols[0] if categorical_cols else None

    data.primary_numeric = primary_numeric
    data.primary_category = primary_category
    data.has_date = primary_date is not None

    # ---- KPIs -----------------------------------------------------------
    data.kpis.append({"key": "total", "label": "Total de registros", "value": f"{len(working):,}".replace(",", ".")})

    if primary_numeric:
        col = working[primary_numeric].dropna()
        data.kpis.append({"key": "sum", "label": f"Soma de {primary_numeric}", "value": _fmt_number(col.sum())})
        data.kpis.append({"key": "mean", "label": f"Média de {primary_numeric}", "value": _fmt_number(col.mean())})
        data.kpis.append({"key": "max", "label": f"Máximo de {primary_numeric}", "value": _fmt_number(col.max())})

    if primary_date:
        col = working[primary_date].dropna()
        if not col.empty:
            data.kpis.append({
                "key": "period",
                "label": "Período",
                "value": f"{col.min().strftime('%d/%m/%Y')} – {col.max().strftime('%d/%m/%Y')}",
            })

    # ---- Resumo de todas as colunas numéricas ----------------------------
    for col_name in numeric_cols:
        series = working[col_name].dropna()
        if series.empty:
            continue
        data.numeric_summary.append({
            "column": col_name,
            "sum": _fmt_number(series.sum()),
            "mean": _fmt_number(series.mean()),
            "min": _fmt_number(series.min()),
            "max": _fmt_number(series.max()),
        })

    # ---- Bucket de tempo por linha (usado no gráfico E no filtro) --------
    # Calculamos a mesma "caixinha" de tempo (dia/semana/mês) tanto para o
    # gráfico agregado quanto para cada linha individual, usando o MESMO
    # formato de rótulo — assim o JavaScript consegue re-somar por bucket
    # ao filtrar, sem reimplementar a lógica de datas do pandas.
    bucket_by_row: pd.Series | None = None
    time_labels_order: list[str] = []

    if primary_date:
        valid_dates = working[primary_date].dropna()
        if not valid_dates.empty:
            freq, label_fmt = _pick_freq_and_format(valid_dates)
            resample_freq = _RESAMPLE_ALIAS[freq]
            bucket_ts = _bucket_timestamps(working[primary_date], freq)
            bucket_by_row = bucket_ts.dt.strftime(label_fmt).where(working[primary_date].notna())

            if primary_numeric:
                ts = working[[primary_date, primary_numeric]].dropna(subset=[primary_date])
                grouped = (
                    ts.set_index(primary_date)[primary_numeric]
                    .resample(resample_freq)
                    .sum()
                    .reset_index()
                )
                time_labels_order = [d.strftime(label_fmt) for d in grouped[primary_date]]
                data.time_series = {
                    "title": f"{primary_numeric} ao longo do tempo",
                    "labels": time_labels_order,
                    "values": [round(float(v), 2) for v in grouped[primary_numeric]],
                }
            else:
                ts = working[[primary_date]].dropna()
                grouped = ts.set_index(primary_date).resample(resample_freq).size().reset_index(name="count")
                time_labels_order = [d.strftime(label_fmt) for d in grouped[primary_date]]
                data.time_series = {
                    "title": "Registros ao longo do tempo",
                    "labels": time_labels_order,
                    "values": [int(v) for v in grouped["count"]],
                }

    # ---- Categorias (gráfico de barras / pizza) ---------------------------
    if primary_category:
        if primary_numeric:
            grouped = (
                working.groupby(primary_category, dropna=True)[primary_numeric]
                .sum()
                .sort_values(ascending=False)
            )
        else:
            grouped = working[primary_category].value_counts()

        top = grouped.head(TOP_N_CATEGORIES)
        rest_sum = grouped.iloc[TOP_N_CATEGORIES:].sum()

        labels = [str(x) for x in top.index]
        values = [round(float(v), 2) for v in top.values]
        if rest_sum > 0:
            labels.append("Outros")
            values.append(round(float(rest_sum), 2))

        metric_label = primary_numeric if primary_numeric else "quantidade"
        data.category_breakdown = {
            "title": f"{primary_category} por {metric_label}",
            "labels": labels,
            "values": values,
        }

    # ---- Amostra dos dados (tabela) ---------------------------------------
    preview = df.head(PREVIEW_ROWS)
    data.preview_columns = [str(c) for c in preview.columns]
    data.preview_rows = preview.astype(str).values.tolist()

    # ---- Payload enxuto para o filtro interativo no navegador -------------
    # Só monta se o arquivo não for gigante, pra não estourar o tamanho da
    # página — acima disso o dashboard continua funcionando, só sem o filtro
    # por clique (ver aviso abaixo).
    if len(working) <= MAX_INTERACTIVE_ROWS and (primary_category or primary_date or numeric_cols):
        records: list[dict] = []
        for i in range(len(working)):
            row = working.iloc[i]
            record: dict = {}
            if primary_category:
                val = row[primary_category]
                record["category"] = None if pd.isna(val) else str(val)
            if primary_date:
                val = row[primary_date]
                record["date"] = None if pd.isna(val) else val.strftime("%Y-%m-%d")
                record["bucket"] = None if bucket_by_row is None else bucket_by_row.iloc[i]
                if isinstance(record["bucket"], float):  # NaN vira float
                    record["bucket"] = None
            if numeric_cols:
                record["numeric"] = {
                    col: (None if pd.isna(row[col]) else round(float(row[col]), 4)) for col in numeric_cols
                }
            records.append(record)

        data.records = records
        data.interactive = True
    elif len(working) > MAX_INTERACTIVE_ROWS:
        warnings.append(
            f"Arquivo com mais de {MAX_INTERACTIVE_ROWS:,} linhas — o filtro por clique foi "
            "desativado nesta visualização para manter a performance.".replace(",", ".")
        )

    if not numeric_cols:
        warnings.append("Não encontrei colunas numéricas — alguns gráficos podem não aparecer.")
    if not date_cols and not categorical_cols:
        warnings.append("Não encontrei colunas de data ou categoria para agrupar os dados.")

    data.warnings = warnings
    return data


def _fmt_number(value: float) -> str:
    if pd.isna(value):
        return "-"
    if abs(value) >= 1000:
        return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{value:,.2f}".replace(".", ",")
