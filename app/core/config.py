"""
Configurações centrais da aplicação.
"""
import os
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
BRAND_NAME = os.getenv("BRAND_NAME", "Gerador de Dashboard Profissional")
BRAND_TAGLINE = "Transforme planilhas e PDFs em dashboards profissionais em segundos"


# ---------------------------------------------------------------------------
# Produção: licença, sessão e limites de uso
# Tudo vem de variáveis de ambiente — no Railway, é só preencher em "Variables".
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "sim", "on"}


# Chave secreta: assina os códigos de licença E o cookie de sessão. Em produção
# DEVE ser definida (string longa e aleatória) e nunca mudar — se mudar, todos
# os códigos já vendidos deixam de valer.
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Quando True, só entra quem digitar um código de licença válido. Fica False por
# padrão para o uso local continuar igual; no Railway defina LICENSE_REQUIRED=true.
LICENSE_REQUIRED = _env_bool("LICENSE_REQUIRED", False)

# Códigos cancelados/reembolsados (separados por vírgula). Basta adicionar o
# código aqui para bloquear — não precisa de banco de dados.
REVOKED_CODES = {c.strip().upper() for c in os.getenv("REVOKED_CODES", "").split(",") if c.strip()}

# Quantos dias a pessoa fica logada depois de digitar o código.
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))

# Limites por IP (janela de 60 s): uploads e tentativas de código de licença.
RATE_LIMIT_UPLOADS_PER_MIN = int(os.getenv("RATE_LIMIT_UPLOADS_PER_MIN", "10"))
RATE_LIMIT_ACCESS_PER_MIN = int(os.getenv("RATE_LIMIT_ACCESS_PER_MIN", "8"))

# Proteção contra .xlsx "bomba" (zip pequeno que descompacta em gigabytes).
MAX_UNCOMPRESSED_SIZE = 200 * 1024 * 1024

# Link de compra mostrado na tela de acesso (ex.: página do produto na Hotmart).
PURCHASE_URL = os.getenv("PURCHASE_URL", "")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "")
