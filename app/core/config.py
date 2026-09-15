"""
Configurações centrais da aplicação.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Extensões de arquivo aceitas no upload
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf"}

# Tamanho máximo de upload (em bytes) — 20 MB
MAX_UPLOAD_SIZE = 20 * 1024 * 1024

# Quantas linhas mostrar na tabela de pré-visualização do dashboard
PREVIEW_ROWS = 15

# Quantas categorias mostrar nos gráficos de "Top N" antes de agrupar o resto em "Outros"
TOP_N_CATEGORIES = 8

# Acima desse número de linhas, o filtro interativo (clicar pra filtrar) é
# desativado — o dashboard continua funcionando normalmente, só sem o filtro,
# para não deixar a página pesada demais no navegador.
MAX_INTERACTIVE_ROWS = 20_000

# ---------------------------------------------------------------------------
# Marca / white-label
# ---------------------------------------------------------------------------
# Troque só estes valores (e as cores em app/static/css/style.css, na seção
# "Marca") para reskinar o sistema para um cliente diferente.
BRAND_NAME = "Gerador de Dashboard"
BRAND_TAGLINE = "Transforme planilhas e PDFs em dashboards profissionais em segundos"
