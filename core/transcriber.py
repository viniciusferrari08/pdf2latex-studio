#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cliente de transcrição multimodal Gemini otimizado para LaTeX, equações numeradas e TikZ."""

import json
import re
import time
from pathlib import Path
from typing import List, Optional
from PIL import Image

from google import genai

LEARNED_RULES_FILE = Path(__file__).resolve().parent / "learned_prompt_rules.json"

AVAILABLE_MODELS = [
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
]

SYSTEM_PROMPT = r"""Você é um especialista sênior em transcrição acadêmica, física/matemática teórica e diagramação científica em LaTeX.
Sua tarefa é transcrever fielmente esta página (manuscrita ou digitalizada) para código LaTeX de altíssima qualidade, seguindo exatamente o estilo de livro didático rigoroso.

DIRETRIZES FUNDAMENTAIS:
1. FORMATO DO CÓDIGO:
   - Retorne APENAS o corpo em LaTeX correspondente ao conteúdo desta página (NÃO inclua \documentclass, \usepackage, \begin{document}, \end{document}, nem cabeçalhos/rodapés de numeração de página da folha original).
   - NÃO envolva a resposta em blocos markdown (```latex ... ```). Envie código LaTeX puro.

2. ESTRUTURA E TIPOGRAFIA:
   - Use \section{...}, \subsection{...}, \subsubsection{...} ou \paragraph{...} para títulos e tópicos novos (a classe e o preâmbulo já formatam tudo em algarismos romanos automaticamente; NÃO escreva "I.", "II.", "1." manualmente dentro do título).
   - Utilize \begin{destaquebox} ... \end{destaquebox} ou \boxed{...} para teoremas, resultados finais importantes ou definições centrais.
   - Use o pacote 'physics' (\ket{\psi}, \bra{\phi}, \braket{\phi}{\psi}, \mel{\phi}{\hat{A}}{\psi}, \dd{x}, \dv{f}{x}, \pdv{\psi}{t}).

3. ENUMERAÇÃO DE EQUAÇÕES E REFERÊNCIAS NO TEXTO (ESSENCIAL):
   - Enumere todas as equações importantes e passos-chave usando \begin{equation}\label{eq:pPAGE_NUM_NOME} ... \end{equation} ou \begin{align}\label{...} ... \end{align}.
   - Use labels únicos e descritivos prefixados pelo número da página ou contexto (ex: \label{eq:p03_schroedinger}).
   - Sempre que uma equação for substituída, projetada, integrada ou comentada em seguida, INCLUA referências explícitas clicáveis usando SEMPRE \eqref{eq:...} (NUNCA escreva o número literal "(I.1)" no texto, use sempre Eq.~\eqref{eq:...} para gerar hiperlink), como:
     "Substituindo a Eq.~\eqref{eq:...} na Eq.~\eqref{eq:...}, obtemos..." ou "A partir da definição expressa na Eq.~\eqref{eq:...}...".
   - Para passagens meramente auxiliares que não precisam de número, use \nonumber ou \[ ... \].

4. DIAGRAMAS, GRÁFICOS E DESENHOS CIENTÍFICOS:
   O preâmbulo possui suporte nativo a 'tikz' (positioning, arrows.meta, decorations.pathreplacing, decorations.pathmorphing, calc, patterns, shapes), 'pgfplots' (compat=1.18), 'tikz-feynman' (compat=1.1.0) e 'quantikz'. Escolha a ferramenta mais adequada para cada tipo de figura:
   - GRÁFICOS DE FUNÇÕES E POTENCIAIS (PGFPLOTS):
     * Para poços de potencial $V(x)$, funções de onda, curvas de probabilidade, dispersão ou qualquer gráfico com eixos e funções contínuas, use SEMPRE:
       \begin{center}\begin{tikzpicture}\begin{axis}[xlabel={$x$}, ylabel={$V(x)$}, domain=-3:3, samples=100, width=8cm, height=5cm] \addplot[very thick, darkblue] {...}; \end{axis}\end{tikzpicture}\captionof{figure}{Descrição clara.}\end{center}.
   - ESPALHAMENTO E PARTÍCULAS (TIKZ-FEYNMAN):
     * Para colisões, espalhamento, fótons, propagadores ou vértices de interação quântica, use:
       \begin{center}\begin{tikzpicture}\begin{feynman} ... \diagram* { ... }; \end{feynman}\end{tikzpicture}\captionof{figure}{Descrição clara.}\end{center}.
       (ATENÇÃO: Use a sintaxe de vértices e \diagram* com posicionamento relativo compatível com pdflatex; NUNCA use layout automático de grafos LuaTeX).
   - CIRCUITOS E OPERADORES QUÂNTICOS (QUANTIKZ):
     * Para sequências de portas quânticas, fios quânticos, medições e estados entrelaçados, use:
       \begin{center}\begin{quantikz} ... \end{quantikz}\captionof{figure}{Descrição clara.}\end{center}.
   - GEOMETRIA, VETORES E ESQUEMAS GERAIS (TIKZ PADRÃO):
     * Para diagramas de blocos, vetores de estado, esferas, cones ou esquemas de níveis de energia: use \begin{center}\begin{tikzpicture}[>=Stealth, scale=1.0] ... \end{tikzpicture}\captionof{figure}{Descrição clara.}\end{center}.
     * Use as cores 'darkblue' e 'destaqueblue' (além de red!80!black e gray) definidas no preâmbulo.
     * Em opções de posicionamento de nós TikZ (\node[...]), use sempre 'above', 'below', 'left', 'right' (NUNCA use 'bottom' ou 'top') e use 'pos=0.5' diretamente (NUNCA 'style=pos=0.5'). Para âncoras de nós use apenas pontos cardeais (.north, .south, .east, .west), nunca .top/.bottom/.left/.right.
     * Para espessuras de linha em \draw[...], use apenas chaves válidas do TikZ ('thin', 'thick', 'very thick', 'ultra thick' — NUNCA use 'heavy' ou 'bold').
     * Todo símbolo ou delimitador matemático dentro de \node{...} (como \left\{ ... \right.) deve estar explicitamente envolvido em $ ... $.
   - IMAGENS OU FOTOGRAFIAS COMPLEXAS (CROP FALLBACK):
     * SOMENTE se houver uma imagem fotográfica ou gráfico raster denso impossível de reproduzir com código (NUNCA para diagramas conceituais, gráficos ou circuitos), emita o marcador de fallback com bounding box estrito ao redor APENAS da figura (nunca 0.05 a 0.95 da página inteira):
       % [CROP_FALLBACK: xmin=0.10, ymin=0.20, xmax=0.90, ymax=0.65, caption="Descrição da figura original"]
"""


def clean_latex_response(text: str) -> str:
    """Remove cercas markdown e preâmbulos acidentais."""
    text = text.strip()
    match = re.search(r"```(?:latex|tex)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    # Remove \begin{document} / \end{document} caso o modelo insira por engano
    text = re.sub(r"\\documentclass[^\n]*\n?", "", text)
    text = re.sub(r"\\usepackage[^\n]*\n?", "", text)
    text = text.replace("\\begin{document}", "").replace("\\end{document}", "")
    return text.strip()


def get_effective_system_prompt() -> str:
    """Retorna o SYSTEM_PROMPT base acrescido de eventuais regras aprendidas pelo revisor."""
    if not LEARNED_RULES_FILE.exists():
        return SYSTEM_PROMPT
    try:
        rules: List[str] = json.loads(LEARNED_RULES_FILE.read_text(encoding="utf-8"))
        valid = [str(r).strip() for r in rules if str(r).strip()]
        if not valid:
            return SYSTEM_PROMPT
        extra_block = "\n\n5. REGRAS ADICIONAIS APRENDIDAS (OBRIGATÓRIO SEGUIR):\n" + "\n".join(
            f"   - {r}" for r in valid
        )
        return SYSTEM_PROMPT + extra_block
    except Exception:
        return SYSTEM_PROMPT


def transcribe_page_image(
    api_key: str,
    image_path: Path,
    page_num: int,
    chapter_slug: str = "doc",
    model: str = "gemini-3.5-flash",
    extra_instruction: str = "",
    reference_context: str = "",
    max_retries: int = 4,
) -> str:
    """Envia a imagem da página para o Gemini e retorna o código LaTeX estruturado."""
    client = genai.Client(api_key=api_key)
    img = Image.open(image_path)

    effective_prompt = get_effective_system_prompt()
    models_to_try = [model] + [m for m in AVAILABLE_MODELS if m != model]
    user_prompt = (
        f"Transcreva a página {page_num} do documento '{chapter_slug}'. "
        f"Use labels únicos iniciando com 'eq:{chapter_slug}_p{page_num:03d}_' para todas as equações numeradas. "
        "Conecte as equações no texto explicativo com Eq.~\\eqref{...}."
    )
    if reference_context.strip():
        user_prompt += (
            "\n\nCONTEXTO DO LIVRO-TEXTO DE REFERÊNCIA DA DISCIPLINA "
            "(use para manter consistência de notação, símbolos e desambiguar escrita manual):\n"
            f"{reference_context.strip()}"
        )
    if extra_instruction.strip():
        user_prompt += f"\n\nInstrução adicional do usuário: {extra_instruction.strip()}"

    last_exception: Optional[Exception] = None
    for m in models_to_try:
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=[effective_prompt, user_prompt, img],
                )
                if response and response.text:
                    time.sleep(0.8)
                    return clean_latex_response(response.text)
            except Exception as e:
                last_exception = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(8 * (attempt + 1))
                    continue
                elif "503" in err_str or "high demand" in err_str or "UNAVAILABLE" in err_str:
                    time.sleep(4 * (attempt + 1))
                    continue
                else:
                    # Modelo indisponível (404) ou erro permanente -> tenta próximo modelo
                    break
    raise last_exception or RuntimeError("Falha ao transcrever imagem com todos os modelos configurados.")
