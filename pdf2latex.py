#!/usr/bin/env python3
"""
pdf2latex.py - Transcritor de Notas de Aula e Documentos Manuscritos/PDF para LaTeX.
Utiliza a API do Google Gemini com suporte a visão e compreensão de física/matemática.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from PIL import Image

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Erro: A biblioteca 'google-genai' não está instalada.")
    print("Execute: pip install google-genai pillow tqdm")
    sys.exit(1)


SYSTEM_PROMPT = r"""Você é um especialista em transcrição acadêmica, física teórica e LaTeX.
Sua tarefa é transcrever fielmente esta imagem de notas de aula manuscritas/fotografadas para código LaTeX de altíssima qualidade.

DIRETRIZES FUNDAMENTAIS:
1. FORMATO DO CÓDIGO:
   - Forneça APENAS o corpo em LaTeX correspondente ao conteúdo da página (não inclua \documentclass nem \begin{document}, pois este trecho será incluído em um documento mestre).
   - Não envolva a resposta em blocos markdown com ```latex ... ```. Envie código LaTeX puro.

2. FÍSICA E NOTAÇÃO MATEMÁTICA:
   - Use o pacote 'physics' sempre que apropriado:
     * Kets, bras e produtos internos: \ket{\psi}, \bra{\phi}, \braket{\phi}{\psi}, \mel{\phi}{\hat{A}}{\psi}
     * Comutadores: \comm{\hat{A}}{\hat{B}}
     * Derivadas e diferenciais: \dd{x}, \dv{f}{x}, \pdv{\psi}{t}
     * Operadores: use chapéu (\hat{H}, \hat{p}, \hat{x}) conforme as anotações originais.
   - Para equações em linha, use $...$.
   - Para equações destacadas ou deduções, use os ambientes \[ ... \], equation, ou align* quando houver múltiplos passos alinhados com &.
   - Se houver fórmulas destacadas em caixas no manuscrito, use \boxed{...}.

3. TEXTO E ESTRUTURA:
   - Preserve todo o texto em português, corrigindo eventuais pequenos erros ortográficos ou lapsos da escrita manual se o sentido for evidente pelo contexto físico.
   - Use títulos de seções/subseções apropriados (\section*, \subsection*, \paragraph*) se a página introduzir um novo tópico.
   - Use listas (itemize, enumerate) quando o manuscrito listar tópicos, postulados ou propriedades.

4. DIAGRAMAS, GRÁFICOS E DESENHOS:
   - O preâmbulo conta com 'tikz', 'pgfplots' (compat=1.18), 'tikz-feynman' (compat=1.1.0) e 'quantikz'.
   - Para curvas e potenciais físicos $V(x)$: use pgfplots (\begin{axis} ... \end{axis}).
   - Para espalhamento e partículas: use tikz-feynman (\diagram* { ... } compatível com pdflatex).
   - Para portas e circuitos quânticos: use quantikz (\begin{quantikz} ... \end{quantikz}).
   - Para geometrias e esquemas gerais: use tikz standard limpo.
   - Caso seja impossível recriar em código: inclua um comentário descritivo: % [DIAGRAMA: descrição do gráfico/desenho presente nas anotações].
"""


def load_env_file(filepath: Path = Path(".env")):
    """Carrega variáveis de um arquivo .env se existir."""
    if not filepath.exists():
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k not in os.environ:
                os.environ[k] = v


def get_api_key(cli_key: Optional[str]) -> str:
    """Busca a chave de API em ordem de prioridade: argumento CLI > GEMINI_API_KEY > GOOGLE_API_KEY > .env."""
    load_env_file()
    key = cli_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("\n[!] Chave da API do Google Gemini não encontrada!")
        print("Você pode fornecer a chave de 3 formas:")
        print("  1. Passar via argumento: --api-key AIzaSy...")
        print("  2. Definir a variável de ambiente: export GEMINI_API_KEY='AIzaSy...'")
        print("  3. Criar um arquivo .env no diretório com: GEMINI_API_KEY=AIzaSy...\n")
        print("Obtenha sua chave gratuita em: https://aistudio.google.com/app/apikey\n")
        sys.exit(1)
    return key


def get_pdf_page_count(pdf_path: Path) -> int:
    """Obtém o número de páginas usando pdfinfo."""
    try:
        res = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        for line in res.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except Exception:
        pass
    return 0


def render_page_to_png(pdf_path: Path, page_num: int, output_dir: Path, dpi: int = 200) -> Path:
    """Renderiza uma página do PDF para imagem PNG de alta resolução."""
    output_prefix = output_dir / f"page_{page_num:03d}"
    expected_png = output_dir / f"page_{page_num:03d}.png"
    
    if expected_png.exists():
        return expected_png

    cmd = [
        "pdftoppm",
        "-png",
        "-r", str(dpi),
        "-f", str(page_num),
        "-l", str(page_num),
        str(pdf_path),
        str(output_prefix)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    generated = list(output_dir.glob(f"page_{page_num:03d}-*.png"))
    if generated:
        generated[0].rename(expected_png)
        return expected_png
    elif expected_png.exists():
        return expected_png
    else:
        raise FileNotFoundError(f"Falha ao gerar PNG para página {page_num} de {pdf_path.name}")


def clean_latex_response(text: str) -> str:
    """Remove eventuais blocos de formatação markdown como ```latex ... ```."""
    text = text.strip()
    match = re.search(r"```(?:latex)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    return text


FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
]


def transcribe_image(client: genai.Client, model: str, image_path: Path, max_retries: int = 5) -> str:
    """Envia a imagem para a API do Gemini e retorna o código LaTeX da página, com fallback e retry."""
    with Image.open(image_path) as raw_img:
        img = raw_img.copy()
    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    
    last_exception = None
    for m in models_to_try:
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=[
                        SYSTEM_PROMPT,
                        "Transcreva com máxima precisão física e matemática o conteúdo desta imagem para LaTeX:",
                        img
                    ]
                )
                if response and response.text:
                    time.sleep(1.5)  # Respeita o rate limit
                    return clean_latex_response(response.text)
            except Exception as e:
                last_exception = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait_time = 10 * (attempt + 1)
                    print(f"    [!] Quota excedida temporariamente (429). Aguardando {wait_time}s antes de tentar novamente...")
                    time.sleep(wait_time)
                    continue
                elif "503" in err_str or "high demand" in err_str or "UNAVAILABLE" in err_str:
                    wait_time = 4 * (attempt + 1)
                    print(f"    [!] Servidor ocupado (503). Aguardando {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    # Outro erro (ex: modelo incompatível), tenta o próximo modelo
                    break
    raise last_exception or RuntimeError("Falha ao obter resposta do modelo após tentativas.")


MASTER_HEADER = r"""\documentclass[12pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[brazil]{babel}
\usepackage{amsmath,amssymb,amsfonts,amsthm}
\usepackage{physics}
\usepackage{geometry}
\geometry{a4paper, margin=2cm}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage{tcolorbox}
\usepackage{cancel}
\usepackage{bm}
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usepackage[compat=1.1.0]{tikz-feynman}
\usepackage{quantikz}
\usepackage{hyperref}
\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    urlcolor=blue,
    citecolor=blue
}

\title{\textbf{TITLE_PLACEHOLDER}}
\author{Notas de Aula transcritas}
\date{\today}

\begin{document}
\maketitle
\tableofcontents
\newpage
"""

MASTER_FOOTER = r"""
\end{document}
"""


def process_pdf(
    pdf_path: Path,
    client: genai.Client,
    model: str,
    output_base: Path,
    dpi: int = 200,
    force: bool = False,
    compile_tex: bool = False
):
    """Processa um PDF completo, página por página, e monta o documento compilável."""
    doc_slug = pdf_path.stem
    doc_dir = output_base / doc_slug
    images_dir = doc_dir / "images"
    pages_dir = doc_dir / "pages"
    
    images_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    total_pages = get_pdf_page_count(pdf_path)
    if total_pages == 0:
        print(f"[!] Aviso: Não foi possível determinar o número de páginas para {pdf_path.name}")
        return

    print(f"\n=======================================================")
    print(f"📄 Processando: {pdf_path.name} ({total_pages} páginas)")
    print(f"📁 Diretório de saída: {doc_dir}")
    print(f"=======================================================")

    page_tex_files = []

    for page_num in range(1, total_pages + 1):
        tex_file = pages_dir / f"page_{page_num:03d}.tex"
        page_tex_files.append(tex_file)

        if tex_file.exists() and not force:
            print(f"  [Pág {page_num}/{total_pages}] Já transcrita. Pulando...")
            continue

        print(f"  [Pág {page_num}/{total_pages}] Renderizando imagem...")
        img_path = render_page_to_png(pdf_path, page_num, images_dir, dpi=dpi)

        print(f"  [Pág {page_num}/{total_pages}] Transcrevendo com Gemini ({model})...")
        try:
            latex_code = transcribe_image(client, model, img_path)
            with open(tex_file, "w", encoding="utf-8") as f:
                f.write(f"% --- Início da Página {page_num} ---\n")
                f.write(latex_code)
                f.write(f"\n% --- Fim da Página {page_num} ---\n")
            print(f"  [Pág {page_num}/{total_pages}] ✓ Concluída e salva!")
        except Exception as e:
            print(f"  [Pág {page_num}/{total_pages}] ✗ Erro ao transcrever: {e}")

    # Monta o documento completo consolidado
    print(f"\n-> Montando documento final consolidado: {doc_slug}.tex")
    master_file = doc_dir / f"{doc_slug}.tex"
    
    with open(master_file, "w", encoding="utf-8") as master_out:
        header = MASTER_HEADER.replace("TITLE_PLACEHOLDER", doc_slug)
        master_out.write(header)

        for i, tex_file in enumerate(page_tex_files, 1):
            if tex_file.exists():
                master_out.write(f"\n\n% ==========================================\n")
                master_out.write(f"% NOTAS DA PÁGINA {i}\n")
                master_out.write(f"% ==========================================\n")
                with open(tex_file, "r", encoding="utf-8") as pf:
                    master_out.write(pf.read())
                master_out.write("\n\\vspace{0.8cm}\n\\hrule\n\\vspace{0.8cm}\n")

        master_out.write(MASTER_FOOTER)

    print(f"✓ Documento consolidado gerado: {master_file}")

    if compile_tex:
        print(f"\n-> Compilando com pdflatex...")
        try:
            res = subprocess.run(
                ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", master_file.name],
                cwd=str(doc_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            compiled_pdf = doc_dir / f"{doc_slug}.pdf"
            if compiled_pdf.exists():
                print(f"✓ PDF compilado com sucesso: {compiled_pdf}")
            else:
                print(f"[!] AVISO: Compilação gerou alertas ou erros. Verifique o log em {doc_dir / (doc_slug + '.log')}")
        except Exception as e:
            print(f"[!] Erro ao invocar pdflatex: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Transcritor universal de PDFs e notas manuscritas para LaTeX usando Google Gemini."
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Caminho para o arquivo PDF ou pasta contendo arquivos PDF."
    )
    parser.add_argument(
        "-o", "--output",
        default="transcricoes_latex",
        help="Diretório onde os arquivos LaTeX e imagens serão salvos (padrão: transcricoes_latex)."
    )
    parser.add_argument(
        "--api-key",
        help="Chave de API do Google Gemini (se omitida, usa GEMINI_API_KEY ou .env)."
    )
    parser.add_argument(
        "-m", "--model",
        default="gemini-3.5-flash",
        help="Modelo do Gemini a utilizar (padrão: gemini-3.5-flash)."
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="Resolução da renderização das páginas (padrão: 200 DPI)."
    )
    parser.add_argument(
        "-c", "--compile",
        action="store_true",
        help="Tentar compilar automaticamente o .tex gerado para PDF com pdflatex."
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Forçar re-transcrição de páginas já existentes."
    )

    args = parser.parse_args()

    # Validações iniciais
    if not shutil.which("pdftoppm"):
        print("Erro: O utilitário 'pdftoppm' (poppler-utils) não está instalado no sistema.")
        sys.exit(1)

    api_key = get_api_key(args.api_key)
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120000))

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        pdf_list = [input_path]
    elif input_path.is_dir():
        pdf_list = sorted(list(input_path.glob("*.pdf")))
    else:
        print(f"Erro: O caminho especificado '{input_path}' não é um PDF nem um diretório válido.")
        sys.exit(1)

    if not pdf_list:
        print(f"Nenhum arquivo PDF encontrado em: {input_path}")
        sys.exit(0)

    print(f"Encontrado(s) {len(pdf_list)} arquivo(s) PDF para processar.")
    for pdf in pdf_list:
        process_pdf(
            pdf_path=pdf,
            client=client,
            model=args.model,
            output_base=output_dir,
            dpi=args.dpi,
            force=args.force,
            compile_tex=args.compile
        )

    print("\n🎉 Todas as transcrições foram finalizadas com sucesso!")


if __name__ == "__main__":
    main()
