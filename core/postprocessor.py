#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pós-processamento LaTeX: higienização, numeração de equações, fallback de figuras e montagem do documento mestre."""

import re
from pathlib import Path
from typing import List

from core.config import ProjectConfig, TEMPLATES_DIR, darken_hex, hex_to_rgb
from core.renderer import crop_region_from_page


def escape_latex_text(s: str) -> str:
    """Escapa caracteres básicos em campos de texto de metadados mantendo acentos."""
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    for k, v in replacements.items():
        # Evita escapar se já estiver escapado
        s = re.sub(r"(?<!\\)" + re.escape(k), lambda _: v, s)
    return s


def build_ai_disclaimer_block(cfg: ProjectConfig) -> str:
    """Constrói a caixa de aviso sobre uso de IA e contato para erratas."""
    if not cfg.include_ai_disclaimer:
        return ""
    email = cfg.contact_email.strip() or "contato@exemplo.edu.br"
    professor = escape_latex_text(cfg.professor)
    institution = escape_latex_text(cfg.institution)
    semester = escape_latex_text(cfg.semester)
    course = escape_latex_text(cfg.course_code)

    return rf"""
\thispagestyle{{empty}}
\vspace*{{1.2cm}}

\begin{{tcolorbox}}[
    colback=orange!4!white,
    colframe=orange!80!black,
    arc=2.5mm,
    boxrule=0.8pt,
    title={{\sffamily\bfseries Nota Editorial e Uso de Inteligência Artificial}}
]
\small
\textbf{{Contexto do Documento:}}\\
Este material foi estruturado para apoiar o acompanhamento de \textbf{{{course}}} ({institution}, período \textbf{{{semester}}}), com base no conteúdo didático de \textbf{{{professor}}}.

\vspace{{0.3cm}}
\textbf{{Transcrição com Inteligência Artificial:}}\\
O texto, as deduções matemáticas e as figuras vetoriais foram transcritos e diagramados a partir dos documentos originais com auxílio de modelos de Inteligência Artificial multimodal. Apesar da revisão estrutural e tipográfica:
\begin{{center}}
\textit{{\textbf{{O texto transcrito pode conter imprecisões pontuais, lapsos de interpretação de escrita manual ou erros tipográficos.}}}}
\end{{center}}

\vspace{{0.2cm}}
\textbf{{Colaboração e Erratas:}}\\
Caso identifique qualquer erro matemático, físico ou problema de formatação, por favor envie uma notificação indicando a página e o trecho para:
\begin{{center}}
\href{{mailto:{email}}}{{\textbf{{\texttt{{{email}}}}}}}
\end{{center}}
\end{{tcolorbox}}
"""


def get_default_template_text(preset: str) -> str:
    """Lê o arquivo de template base ('cap12_preset' ou 'article')."""
    fname = "cap12_preset.tex" if preset == "cap12_report" else "article_preset.tex"
    path = TEMPLATES_DIR / fname
    return path.read_text(encoding="utf-8")


def render_preamble(cfg: ProjectConfig) -> str:
    """Renderiza o preâmbulo substituindo metadados, cores e caminhos de imagens."""
    template = cfg.custom_preamble.strip() if cfg.custom_preamble.strip() else get_default_template_text(cfg.preset)

    pr, pg, pb = hex_to_rgb(cfg.primary_color_hex)
    dark_hex = cfg.dark_color_hex.strip() or darken_hex(cfg.primary_color_hex)
    dr, dg, db = hex_to_rgb(dark_hex)

    # Caminhos extras de imagens do projeto (sem linhas em branco dentro de \graphicspath)
    extra_paths = []
    for ch in cfg.chapters:
        slug = ch.get("slug", "")
        if slug:
            extra_paths.append(f"    {{images/{slug}/}}")
            extra_paths.append(f"    {{page_images/{slug}/}}")
    graphics_paths = "\n".join(extra_paths) if extra_paths else "    % sem subpastas extras"

    replacements = {
        "__PRIMARY_R__": str(pr),
        "__PRIMARY_G__": str(pg),
        "__PRIMARY_B__": str(pb),
        "__DARK_R__": str(dr),
        "__DARK_G__": str(dg),
        "__DARK_B__": str(db),
        "__TITLE__": escape_latex_text(cfg.title),
        "__SUBTITLE__": escape_latex_text(cfg.subtitle),
        "__COURSE_CODE__": escape_latex_text(cfg.course_code),
        "__INSTITUTION__": escape_latex_text(cfg.institution),
        "__DEPARTMENT__": escape_latex_text(cfg.department),
        "__PROGRAM__": escape_latex_text(cfg.program),
        "__SEMESTER__": escape_latex_text(cfg.semester),
        "__PROFESSOR__": escape_latex_text(cfg.professor),
        "__TRANSCRIBER__": escape_latex_text(cfg.transcriber),
        "__CONTACT_EMAIL__": cfg.contact_email.strip(),
        "__DOC_VERSION__": escape_latex_text(cfg.doc_version or "v1.0"),
        "__AI_DISCLAIMER_BLOCK__": build_ai_disclaimer_block(cfg),
        "__GRAPHICS_PATH__": graphics_paths,
    }

    result = template
    for k, v in replacements.items():
        result = result.replace(k, v)
    return result


def convert_unnumbered_equations(tex: str, chapter_slug: str, page_num: int) -> str:
    r"""Converte ambientes \[ ... \] e equation* para equation numerados com labels únicos."""
    eq_idx = 0

    def _next_label() -> str:
        nonlocal eq_idx
        eq_idx += 1
        return f"eq:{chapter_slug}_p{page_num:03d}_{eq_idx}"

    # Converte \begin{equation*} ... \end{equation*}
    def _repl_eq_star(m: re.Match) -> str:
        body = m.group(1).strip()
        if not body or r"\tag{" in body:
            return m.group(0)
        lbl = "" if r"\label{" in body else f"\n\\label{{{_next_label()}}}"
        return f"\\begin{{equation}}{lbl}\n{body}\n\\end{{equation}}"

    tex = re.sub(r"\\begin\{equation\*\}([\s\S]*?)\\end\{equation\*\}", _repl_eq_star, tex)

    # Converte \[ ... \] fora de ambientes especiais
    def _repl_brackets(m: re.Match) -> str:
        body = m.group(1).strip()
        if not body or r"\tag{" in body:
            return m.group(0)
        lbl = "" if r"\label{" in body else f"\n\\label{{{_next_label()}}}"
        return f"\\begin{{equation}}{lbl}\n{body}\n\\end{{equation}}"

    tex = re.sub(r"\\\[([\s\S]*?)\\\]", _repl_brackets, tex)
    return tex


def resolve_crop_fallbacks(
    tex: str,
    page_png: Path,
    images_dir: Path,
    chapter_slug: str,
    page_num: int,
) -> str:
    """Substitui marcadores % [CROP_FALLBACK: ...] pelo recorte real da imagem da página."""
    pattern = re.compile(
        r"%\s*\[CROP_FALLBACK:\s*([^\]]+)\]"
    )
    crop_idx = 0

    def _parse_and_crop(m: re.Match) -> str:
        nonlocal crop_idx
        crop_idx += 1
        attrs = m.group(1)

        def _get_float(key: str, default: float) -> float:
            km = re.search(rf"{key}\s*=\s*([0-9]*\.?[0-9]+)", attrs)
            return float(km.group(1)) if km else default

        xmin = _get_float("xmin", 0.08)
        ymin = _get_float("ymin", 0.15)
        xmax = _get_float("xmax", 0.92)
        ymax = _get_float("ymax", 0.85)
        cap_m = re.search(r'caption\s*=\s*"([^"]*)"', attrs)
        caption = cap_m.group(1) if cap_m else f"Figura extraída da página {page_num}"

        out_dir = images_dir / chapter_slug
        out_name = f"fig_p{page_num:03d}_{crop_idx}.png"
        dest_png = out_dir / out_name

        if page_png.exists():
            crop_region_from_page(page_png, dest_png, xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax)
            rel_path = f"images/{chapter_slug}/{out_name}"
            return (
                "\\begin{center}\n"
                f"\\includegraphics[width=0.82\\textwidth]{{{rel_path}}}\n"
                f"\\captionof{{figure}}{{{caption}}}\n"
                "\\end{center}"
            )
        return f"% [Figura não recortada - imagem da página ausente: {caption}]"

    return pattern.sub(_parse_and_crop, tex)


def sanitize_latex_body(tex: str) -> str:
    """Corrige artefatos comuns de transcrições automáticas e compatibilidade TikZ/LaTeX."""
    # Remove cabeçalhos/rodapés de página manuscritos isolados
    tex = re.sub(r"\\marginpar\{[^\}]*\}", "", tex)
    tex = re.sub(r"\\hfill\s*\\textcircled\{[^\}]*\}", "", tex)
    tex = re.sub(r"\\hfill\s*\\textbf\{\(\d+\)\}", "", tex)

    # Correções de ambientes ou comandos incompatíveis gerados por LLMs
    tex = tex.replace(r"\begin{noindent}", r"\noindent ").replace(r"\end{noindent}", "")
    tex = re.sub(r"\brect\b(?=\s*\()", "rectangle", tex)
    tex = tex.replace(r"\item[\rightarrow]", r"\item[$\rightarrow$]")
    tex = re.sub(r"\\section\*\{", r"\\section{", tex)
    tex = re.sub(r"\\subsection\*\{", r"\\subsection{", tex)
    tex = re.sub(r"\\subsubsection\*\{", r"\\subsubsection{", tex)

    # Corrige chaves inválidas comuns em nós TikZ (ex: 'bottom' -> 'below', 'top' -> 'above', 'style=pos=' -> 'pos=')
    def _fix_tikz_node_opts(m: re.Match) -> str:
        opts = m.group(1)
        opts = re.sub(r"\bstyle\s*=\s*pos\s*=", "pos=", opts)
        opts = re.sub(r"(?<![a-zA-Z0-9_=])\bbottom\b(?![a-zA-Z0-9_=])", "below", opts)
        opts = re.sub(r"(?<![a-zA-Z0-9_=])\btop\b(?![a-zA-Z0-9_=])", "above", opts)
        return f"node[{opts}]"

    tex = re.sub(r"node\s*\[([^\]]*)\]", _fix_tikz_node_opts, tex)

    # Corrige chaves de espessura de linha inválidas comuns em comandos TikZ (\draw, \filldraw, \path)
    def _fix_tikz_draw_opts(m: re.Match) -> str:
        cmd = m.group(1)
        opts = m.group(2)
        opts = re.sub(r"(?<![a-zA-Z0-9_=])\bheavy\b(?![a-zA-Z0-9_=])", "very thick", opts)
        opts = re.sub(r"(?<![a-zA-Z0-9_=])\bbold\b(?![a-zA-Z0-9_=])", "thick", opts)
        return f"\\{cmd}[{opts}]"

    tex = re.sub(r"\\(draw|filldraw|path|fill)\s*\[([^\]]*)\]", _fix_tikz_draw_opts, tex)

    # Corrige âncoras inválidas de nós TikZ (ex: (nome.left) -> (nome.west))
    anchor_map = {"left": "west", "right": "east", "top": "north", "bottom": "south"}
    tex = re.sub(
        r"\(([A-Za-z0-9_-]+)\.(left|right|top|bottom)\)",
        lambda m: f"({m.group(1)}.{anchor_map[m.group(2)]})",
        tex,
    )

    # Garante modo matemático ao usar \left\{ \begin{tabular} ... \end{tabular} \right. dentro de nós TikZ
    tex = re.sub(
        r"\{\s*\\left\\\{\s*(\\begin\{tabular\}[\s\S]*?\\end\{tabular\})\s*\\right\.\s*\}",
        r"{$\\left\\{\1\\right.$}",
        tex,
    )

    # Substitui macro não-padrão de Griffiths (\gr) por \mathfrak{r}
    tex = re.sub(r"\\gr(?![a-zA-Z])", r"\\mathfrak{r}", tex)

    # Remove resets manuais de contadores que quebram hiperlinks
    tex = re.sub(r"\\setcounter\{(?:equation|footnote|page)\}\{\d+\}", "", tex)
    return tex.strip()


def process_page_tex(
    raw_tex: str,
    page_png: Path,
    images_dir: Path,
    chapter_slug: str,
    page_num: int,
    auto_number_equations: bool = True,
) -> str:
    """Aplica todas as etapas de limpeza, fallback de figuras e enumeração de equações."""
    tex = sanitize_latex_body(raw_tex)
    tex = resolve_crop_fallbacks(tex, page_png, images_dir, chapter_slug, page_num)
    if auto_number_equations:
        tex = convert_unnumbered_equations(tex, chapter_slug, page_num)
    # Auto-linka referências literais a equações com \tag{...} (ex: (I.1) ou \textcolor{...}{(II.8)})
    found_tags = set(re.findall(r"\\tag\{([A-Za-z0-9._-]+)\}", tex))
    if found_tags:
        def _add_tag_label(m: re.Match) -> str:
            t = m.group(1)
            safe_t = re.sub(r"[^A-Za-z0-9_]", "_", t)
            return f"\\tag{{{t}}}\\label{{eq:{chapter_slug}_tag_{safe_t}}}"

        tex = re.sub(r"\\tag\{([A-Za-z0-9._-]+)\}(?!\s*\\label\{)", _add_tag_label, tex)
        sorted_tags = sorted(found_tags, key=len, reverse=True)
        tag_alt = "|".join(re.escape(t) for t in sorted_tags)
        tex = re.sub(
            rf"\\textcolor\{{[^\}}]+\}}\{{\(({tag_alt})\)\}}",
            lambda m: f"\\eqref{{eq:{chapter_slug}_tag_{re.sub(r'[^A-Za-z0-9_]', '_', m.group(1))}}}",
            tex,
        )
        tex = re.sub(
            rf"(?<!\\tag\{{)(?<!\\label\{{)\(({tag_alt})\)(?!\}})",
            lambda m: f"\\eqref{{eq:{chapter_slug}_tag_{re.sub(r'[^A-Za-z0-9_]', '_', m.group(1))}}}",
            tex,
        )

    return tex


def assemble_master_tex(cfg: ProjectConfig) -> Path:
    """Monta o arquivo master.tex consolidado pronto para compilação com pdflatex."""
    pdir = cfg.project_dir()
    preamble = render_preamble(cfg)
    images_dir = pdir / "images"
    images_dir.mkdir(exist_ok=True)

    body_parts: List[str] = []
    chapters = sorted(cfg.chapters, key=lambda c: c.get("order", 0))

    for ch in chapters:
        slug = ch["slug"]
        title = escape_latex_text(ch.get("title", slug))
        total_pages = int(ch.get("total_pages", 0))

        if cfg.preset == "cap12_report":
            body_parts.append(f"\\chapter{{{title}}}")
        elif cfg.mode == "multi":
            body_parts.append(f"\\section{{{title}}}")

        tex_dir = pdir / "page_tex" / slug
        img_dir = pdir / "page_images" / slug

        for pnum in range(1, total_pages + 1):
            pfile = tex_dir / f"page_{pnum:03d}.tex"
            ppng = img_dir / f"page_{pnum:03d}.png"
            if pfile.exists():
                raw = pfile.read_text(encoding="utf-8")
                cleaned = process_page_tex(
                    raw,
                    ppng,
                    images_dir,
                    slug,
                    pnum,
                    auto_number_equations=cfg.auto_number_equations,
                )
                body_parts.append(f"% --- {slug} | Página {pnum} ---\n{cleaned}")

    master_content = preamble + "\n\n" + "\n\n".join(body_parts) + "\n\n\\end{document}\n"
    master_path = pdir / "master.tex"
    master_path.write_text(master_content, encoding="utf-8")
    return master_path
