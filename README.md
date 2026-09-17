# Gerador de Dashboard

Sistema web que recebe uma planilha (CSV/XLSX/XLS) ou um PDF com dados em
formato de tabela, analisa o conteúdo automaticamente e gera um dashboard
profissional (KPIs, gráfico de série temporal, ranking por categoria e
tabela de dados) — sem precisar configurar nada previamente.

## Como funciona

1. O usuário abre a página e envia um arquivo.
2. O backend (FastAPI) lê o arquivo com o leitor apropriado (`app/services/file_reader.py`).
   Se o Excel tiver **várias abas**, o sistema decide o que fazer sozinho: se
   os nomes das abas parecem meses/períodos (ex.: "JAN25", "FEV/25"), junta
   todas em uma tabela só com uma coluna "Mês" (e ignora de propósito abas de
   resumo/consolidado, pra não somar os mesmos valores duas vezes); se as
   abas têm exatamente as mesmas colunas, junta todas com uma coluna "Aba"; se
   não há um padrão seguro, usa a maior aba e avisa quais ficaram de fora. Em
   todos os casos aparece um aviso no topo do dashboard explicando o que foi
   feito.
3. O motor de análise (`app/services/data_analyzer.py`) detecta sozinho:
   - qual coluna é **data** (aceita formatos brasileiros, dd/mm/aaaa etc.);
   - quais colunas são **numéricas** (inclusive valores como `R$ 1.234,56` ou `12,5%`);
   - quais colunas são **categóricas** (bons candidatos para agrupar/comparar).
4. A partir disso, calcula KPIs, série temporal, ranking por categoria e
   renderiza o dashboard (`app/templates/dashboard.html`) com Chart.js.
5. Junto com o dashboard, o backend manda um payload enxuto (`records`) com
   os dados linha a linha. É esse payload que alimenta o **filtro
   interativo**: clicar em uma barra, fatia da rosca ou item da legenda
   filtra o dashboard inteiro (KPIs, gráfico de série temporal e resumo
   numérico) inteiramente no navegador, sem voltar ao servidor — clicar de
   novo na mesma categoria limpa o filtro. Além do clique, há também um
   **menu suspenso** logo acima dos KPIs para escolher a categoria direto
   (mais rápido quando há muitas categorias), com um botão "Limpar filtro" —
   os dois jeitos de filtrar ficam sincronizados entre si. Os próprios
   gráficos de categoria continuam mostrando todas as categorias (são o
   controle do filtro, não o resultado dele) — só a fatia/barra selecionada
   fica em destaque.
6. No topo do dashboard há um botão **"Salvar dashboard em HTML"** — gera e
   baixa um arquivo `.html` único, com o CSS e o Chart.js já embutidos
   dentro do arquivo. Esse arquivo abre em qualquer navegador sem precisar
   do sistema rodando (é só dar duplo clique nele), e o filtro por clique
   continua funcionando normalmente offline. Ótimo para mandar por e-mail
   pro cliente ou guardar como registro de um período.

Se o arquivo não tiver data, ou não tiver categoria, o dashboard se adapta e
mostra só o que faz sentido para aqueles dados (testado com arquivos
somente numéricos, sem data, etc. — ver seção de testes abaixo).

O dashboard sempre abre com o **tema escuro** — é fixo, não depende da
configuração de claro/escuro do sistema operacional de quem estiver vendo
(bom pra manter a identidade visual consistente ao apresentar/vender o
sistema). Pra reverter isso, é só remover `data-theme="dark"` da tag
`<html>` em `app/templates/base.html`.

## Estrutura do projeto

```
dashboard-generator/
├── app/
│   ├── main.py                  # Rotas FastAPI (/, /upload, /health)
│   ├── core/
│   │   └── config.py            # Configurações (extensões aceitas, limites)
│   ├── services/
│   │   ├── file_reader.py       # CSV / Excel / PDF -> DataFrame
│   │   └── data_analyzer.py     # DataFrame -> KPIs + dados dos gráficos
│   ├── templates/
│   │   ├── base.html
│   │   ├── upload.html
│   │   └── dashboard.html
│   └── static/
│       ├── css/style.css
│       └── js/chart.min.js      # Chart.js embutido (funciona 100% offline)
├── sample_data/                 # Arquivos de exemplo para testar (faturamento de app)
├── requirements.txt
└── README.md
```

## Como rodar localmente

```bash
cd dashboard-generator
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Depois abra **http://localhost:8000** no navegador e envie um dos arquivos
de `sample_data/` para ver o dashboard funcionando (ou use seus próprios
dados).

## Reskinar para vender a um cliente (white-label)

O visual foi separado do código pra você poder entregar isso pra diferentes
clientes sem reescrever nada:

- **Nome e frase de efeito**: `app/core/config.py` → `BRAND_NAME` e `BRAND_TAGLINE`.
- **Cores da marca**: `app/static/css/style.css`, bem no topo, na seção
  "Marca / white-label" → troque `--brand-1` e `--brand-2` (o degradê do
  cabeçalho e dos botões é gerado a partir dessas duas cores).
- **Logo**: hoje é um ícone de barras em SVG dentro de `app/templates/base.html`
  (`.brand-mark`) — dá pra substituir por uma tag `<img>` com o logo do cliente.

Nenhum outro arquivo precisa mudar pra trocar a cara do sistema.

## Formatos suportados

| Formato | Como é lido |
|---|---|
| `.csv` | `pandas.read_csv` com detecção automática de separador (`,` ou `;`) e encoding |
| `.xlsx` / `.xls` | `pandas.read_excel` |
| `.pdf` | `pdfplumber` extrai todas as tabelas do PDF e usa a maior encontrada |

Limite de upload: 20 MB (ajustável em `app/core/config.py`).

Acima de 20.000 linhas (`MAX_INTERACTIVE_ROWS` em `app/core/config.py`), o
filtro por clique é desativado automaticamente (com um aviso no dashboard)
para não deixar a página pesada — o resto do dashboard continua funcionando.

## Testes feitos

Antes da entrega, o fluxo completo foi testado com:
- CSV e XLSX com datas, categorias (plataformas) e valores em `R$ 0,00` (pt-BR) — dashboard completo com série temporal, ranking e KPIs.
- PDF com tabela (gerado com `reportlab`) — extração e dashboard funcionando.
- Arquivo sem coluna de data — o gráfico de linha é omitido automaticamente.
- Arquivo só com colunas numéricas — KPIs e tabela aparecem, gráficos de categoria somem, com aviso amigável.
- Arquivo com extensão não suportada e arquivo vazio — mensagens de erro claras, sem quebrar a aplicação.
- Filtro interativo com clique em barra, fatia da rosca e legenda, em datasets com granularidade diária, semanal e mensal — os valores recalculados no navegador foram comparados numericamente com os valores originais (bateram exatamente) e o alternar/limpar filtro foi testado várias vezes em sequência.
- Dataset com mais de 8 categorias — confirma o agrupamento em "Outros" e o filtro por ele.
- Renderização visual (Playwright) simulando sistema operacional em modo
  claro — confirmado que o dashboard força o tema escuro mesmo assim
  (`data-theme="dark"` e cor de fundo escura), sem erros de console.
- Filtro por menu suspenso (dropdown): selecionar uma categoria recalcula
  KPIs, gráfico de série temporal e resumo numérico corretamente, o botão
  "Limpar filtro" reativa/desativa junto com o estado do filtro, e o
  dropdown fica sincronizado quando o filtro é ativado clicando direto no
  gráfico (e vice-versa).
- Exportação do dashboard em HTML: arquivo baixado, aberto direto do disco
  (`file://`, servidor desligado) em uma aba nova sem nenhum erro de
  console, com o tema escuro preservado e com o filtro (clique e dropdown)
  testado e funcionando normalmente dentro desse arquivo exportado (KPIs
  recalculados corretamente ao filtrar e ao limpar o filtro).
- Planilha real "bagunçada" (sem cabeçalho, várias tabelas soltas na mesma
  aba, colunas misturando texto/número/data na mesma coluna) — corrigido um
  erro (`expected string or bytes-like object, got 'float'`) que acontecia
  ao tentar detectar colunas numéricas nesse tipo de arquivo; agora o motor
  de análise trata valores ausentes de forma segura antes de qualquer
  operação de texto/regex, então esses arquivos geram um dashboard (mesmo
  que mais simples, já que faltam nomes de coluna) em vez de quebrar.
- Excel real com 20 abas (uma por mês/período, ex. "JAN25"..."OUT25", mais
  abas de resumo como "MENSAL 2025") — confirmado que o sistema junta
  automaticamente só as abas de mês (ignorando as de resumo, pra não somar
  valor em duplicidade) e avisa isso no dashboard. **Limitação conhecida**:
  quando uma aba de mês mistura, na mesma coluna, valores do dia a dia com
  linhas que já são um subtotal daquela própria aba (ex.: uma linha "TOTAL"
  somando as linhas de cima, na mesma coluna) — comum em planilhas pessoais
  desenhadas à mão — o motor de análise não tem como saber que aquela linha
  é um subtotal, e os KPIs de Soma/Média acabam contando o valor "de novo".
  Isso não é um bug de leitura (o arquivo é lido e combinado certinho); é uma
  limitação de qualquer motor genérico de detecção de colunas diante de um
  layout manual com sub-totais embutidos. Pra números 100% corretos nesse
  tipo de arquivo seria preciso um leitor feito à mão pro layout específico
  daquela planilha (reconhecendo as linhas "TOTAL"/"SALDO"/"GASTO" como
  rótulos, não como dado).

## Próximos passos sugeridos

- **Deploy**: como você já usa Railway/Cloudflare em outros projetos, dá pra containerizar isso com um `Dockerfile` simples (`FROM python:3.12-slim`, copia o projeto, `pip install -r requirements.txt`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`) e subir no Railway.
- **Múltiplas tabelas em um PDF**: hoje o sistema pega a maior tabela do PDF; se seus PDFs tiverem várias tabelas relevantes, dá pra evoluir para deixar o usuário escolher qual usar.
- **Exportar em PDF/PNG**: já é possível salvar o dashboard inteiro como HTML (botão no topo); se quiser também um PDF ou imagem prontos para imprimir, dá pra evoluir com `weasyprint` ou captura via Playwright no próprio backend.
- **Persistência**: se quiser comparar dashboards de uploads anteriores, seria necessário guardar os resultados (ex: SQLite/Postgres) — hoje cada upload é processado na hora e nada fica salvo.
- **Colunas específicas do seu negócio**: se quiser, dá pra ensinar o motor de análise a reconhecer nomes de colunas específicos do seu domínio (ex: "corrida", "gorjeta", "plataforma") para KPIs ainda mais direcionados.
