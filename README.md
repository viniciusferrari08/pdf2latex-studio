# PDF2LaTeX Studio

Ferramenta completa para transcrição e diagramação de **qualquer PDF** (notas manuscritas, listas ou documentos digitais) para **LaTeX acadêmico** com suporte a IA multimodal (Google Gemini), numeração automática de equações por seção, referências cruzadas clicáveis, geração de gráficos vetoriais (**TikZ**, **pgfplots**, **tikz-feynman** e **quantikz**), revisão inteligente de erros de compilação, contexto de livros-texto, versionamento de projetos e interface gráfica local em **Streamlit**.

---

## Principais Recursos

- **Documento Único ou Compêndio Multi-PDF**: Converta 1 PDF avulso (`article_preset.tex`) ou monte uma apostila/livro completo ordenando múltiplos PDFs como capítulos (`cap12_preset.tex` em algarismos romanos `I, II, III...`).
- **Design Editorial Profissional**: Fontes Linux Libertine/Biolinum, cabeçalhos dinâmicos `fancyhdr`, caixas de destaque (`destaquebox`), seletor de cores (padrão `#42A3FB`), aviso editorial opcional e editor de preâmbulo LaTeX integrado.
- **Equações & Referências Cruzadas**: Enumera equações por seção `(I.1), (I.2)...`, converte equações não numeradas opcionalmente e gera links clicáveis `Eq.~\eqref{...}` automaticamente.
- **Diagramas Científicos Nativos**: Suporte a `tikz` (incluindo `circuits.ee.IEC`), `pgfplots`, `tikz-feynman` e `quantikz`, além de fallback automático de recorte de imagem (`CROP_FALLBACK`) para figuras fotográficas complexas.
- **Contexto de Livros-Texto**: Indexação local via `pdftotext` + busca TF-IDF (`core/reference_context.py`) para manter consistência de notação com a bibliografia da disciplina.
- **Revisor de Erros LaTeX com IA e Aprendizado**: Localiza automaticamente a página causadora de falhas no log do `pdflatex`, propõe a correção via Gemini e aprende novas regras de prevenção em `core/learned_prompt_rules.json`.
- **Revisão Lado a Lado & Versionamento**: Compare a imagem original com o código LaTeX editável, recompile prévias de uma única página, regere páginas pontuais com instruções personalizadas e salve/restaure snapshots versionados (`v1.0`, `v1.1`, ...).
- **Exportação Completa**: Download do PDF compilado e de pacote `.zip` com código-fonte TeX, figuras e script `compile.sh`.
- **Modo CLI Independente**: Script `pdf2latex.py` para transcrição em lote via linha de comando.

---

## Estrutura do Repositório

```text
pdf2latex-studio/
├── app.py                           # Interface web local em Streamlit
├── pdf2latex.py                     # CLI independente para transcrição em lote
├── run_app.sh                       # Script de inicialização local (127.0.0.1)
├── requirements.txt                 # Dependências Python
├── .env.example                     # Modelo de configuração da GEMINI_API_KEY
├── core/
│   ├── config.py                    # Configurações, metadados, cores e persistência
│   ├── renderer.py                  # Renderização PDF -> PNG (Poppler) e recorte de figuras
│   ├── transcriber.py               # Cliente Gemini multimodal com fallback de modelos
│   ├── postprocessor.py             # Higienização LaTeX/TikZ, \eqref e montagem do master.tex
│   ├── latex_compiler.py            # Wrapper pdflatex (-no-shell-escape) e prévia de página
│   ├── error_reviewer.py            # Diagnóstico/correção de erros LaTeX via IA
│   ├── learned_prompt_rules.json    # Regras aprendidas injetadas no SYSTEM_PROMPT
│   ├── reference_context.py         # Indexação TF-IDF de livros-texto de referência
│   ├── versioning.py                # Snapshots versionados de projetos
│   └── packager.py                  # Empacotamento .zip (master.tex, imagens e compile.sh)
└── templates/
    ├── cap12_preset.tex             # Preâmbulo report/livro (capa, sumário e capítulos)
    └── article_preset.tex           # Preâmbulo article compacto para documento único
```

---

## Requisitos do Sistema

- **Python 3.10+**
- **Poppler** (`pdftoppm`, `pdfinfo`, `pdftotext`)
- **TeX Live / LaTeX** (`pdflatex` com pacotes `libertine`, `newtxmath`, `physics`, `tcolorbox`, `multirow`, `tikz`, `pgfplots`, `tikz-feynman`, `quantikz`, `titlesec`, `fancyhdr`)
- **Chave de API do Google Gemini**

---

## Instalação e Execução

1. Crie e ative o ambiente virtual:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure sua chave de API localmente (o arquivo `.env` é ignorado pelo Git):
   ```bash
   cp .env.example .env
   # Edite .env e insira sua GEMINI_API_KEY
   ```

3. Inicie a interface gráfica local:
   ```bash
   ./run_app.sh
   ```
   *(A aplicação escuta exclusivamente em `127.0.0.1` por segurança e executa `pdflatex` com `-no-shell-escape`.)*

4. **(Opcional) Uso via linha de comando (CLI):**
   ```bash
   .venv/bin/python pdf2latex.py -i caminho/do/arquivo_ou_pasta -o transcricoes_latex --compile
   ```
