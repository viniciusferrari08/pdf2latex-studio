# PDF2LaTeX Studio

Ferramenta completa para transcrição e diagramação de **qualquer PDF** (notas manuscritas, listas ou documentos digitais) para **LaTeX acadêmico** com suporte a IA multimodal (Google Gemini), numeração automática de equações por seção, referências cruzadas, geração de gráficos vetoriais em **TikZ** e interface gráfica local em **Streamlit**.

---

## Principais Recursos

- **Documento Único ou Múltiplos PDFs**: Converta 1 PDF avulso ou monte uma apostila completa ordenando múltiplos PDFs como capítulos (`I, II, III...`).
- **Design Profissional**: Fontes Linux Libertine/Biolinum, cabeçalhos dinâmicos `fancyhdr`, caixas de destaque (`destaquebox`), seletor de cores (padrão `#42A3FB`) e editor de preâmbulo LaTeX integrado.
- **Numeração de Equações & TikZ**: Enumera equações por seção `(I.1), (I.2)...`, incentiva referências `Eq.~\eqref{...}` no texto e sintetiza diagramas em TikZ nativo (com fallback automático de recorte de imagem para figuras complexas).
- **Revisão Lado a Lado**: Compare a imagem original com o código LaTeX editável, recompile prévias de uma única página ou regere páginas pontuais com instruções personalizadas.
- **Exportação Completa**: Download do PDF compilado e de pacote `.zip` com código-fonte TeX, figuras e script `compile.sh`.

---

## Requisitos do Sistema

- **Python 3.10+**
- **Poppler** (`pdftoppm`, `pdfinfo`)
- **TeX Live / LaTeX** (`pdflatex` com pacotes `libertine`, `newtxmath`, `physics`, `tcolorbox`, `tikz`, `titlesec`, `fancyhdr`)
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
