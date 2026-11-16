#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wrapper de compilação pdflatex com captura detalhada de erros, logs e prévia de página única."""

import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

from core.config import ProjectConfig
from core.postprocessor import process_page_tex, render_preamble


def is_pdflatex_available() -> bool:
    return shutil.which("pdflatex") is not None


def compile_tex_to_pdf(tex_path: Path, passes: int = 2) -> Tuple[bool, Path, str]:
    """
    Compila um arquivo .tex executando o pdflatex múltiplas passagens
    para resolver sumário, equações numeradas e referências cruzadas.
    """
    if not is_pdflatex_available():
        return False, tex_path.with_suffix(".pdf"), "pdflatex não encontrado no PATH do sistema."

    workdir = tex_path.parent
    pdf_path = tex_path.with_suffix(".pdf")
    full_log = []

    last_code = 1
    for p in range(1, passes + 1):
        res = subprocess.run(
            ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        last_code = res.returncode
        full_log.append(f"=== PASSAGEM {p} (código {last_code}) ===\n{res.stdout}")
        if last_code != 0:
            break

    log_text = "\n".join(full_log)
    if last_code != 0:
        err_lines = [
            line for line in log_text.splitlines()
            if line.startswith("!") or "Error" in line or "Undefined" in line or line.startswith("l.")
        ]
        summary = "\n".join(err_lines[-25:]) if err_lines else log_text[-2000:]
        return False, pdf_path, summary

    success = pdf_path.exists()
    return success, pdf_path, log_text[-2500:]


def compile_single_page_preview(
    cfg: ProjectConfig,
    chapter_slug: str,
    page_num: int,
    raw_tex: str,
) -> Tuple[bool, List[Path], str]:
    """
    Compila uma única página isolada para pré-visualização rápida na aba de revisão,
    renderizando o resultado em PNG(s).
    """
    pdir = cfg.project_dir()
    preview_dir = pdir / "_preview"
    preview_dir.mkdir(exist_ok=True)

    # Limpa prévia anterior
    for f in preview_dir.glob("preview_page*"):
        f.unlink()

    # Usa apenas o preâmbulo até \begin{document}, pulando capa/sumário para agilizar prévia
    full_preamble = render_preamble(cfg)
    doc_idx = full_preamble.find(r"\begin{document}")
    clean_preamble = full_preamble[:doc_idx] if doc_idx != -1 else full_preamble
    # Corrige graphicspath relativo a partir de _preview/
    clean_preamble = clean_preamble.replace("{images/}", "{../images/}").replace("{page_images/}", "{../page_images/}")
    clean_preamble = clean_preamble.replace(f"{{images/{chapter_slug}/}}", f"{{../images/{chapter_slug}/}}")

    page_png = pdir / "page_images" / chapter_slug / f"page_{page_num:03d}.png"
    images_dir = pdir / "images"
    processed = process_page_tex(
        raw_tex,
        page_png,
        images_dir,
        chapter_slug,
        page_num,
        auto_number_equations=cfg.auto_number_equations,
    )
    # Ajusta caminhos relativos gerados para _preview/
    processed = processed.replace(f"images/{chapter_slug}/", f"../images/{chapter_slug}/")

    preview_tex = preview_dir / "preview_page.tex"
    preview_content = (
        clean_preamble
        + "\n\\begin{document}\n"
        + f"\\setcounter{{section}}{{1}}\n"
        + processed
        + "\n\\end{document}\n"
    )
    preview_tex.write_text(preview_content, encoding="utf-8")

    ok, pdf_path, log_msg = compile_tex_to_pdf(preview_tex, passes=1)
    if not ok or not pdf_path.exists():
        return False, [], log_msg

    # Renderiza as páginas geradas do preview para PNG
    subprocess.run(
        ["pdftoppm", "-png", "-r", "160", str(pdf_path), str(preview_dir / "preview_out")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    rendered_imgs = sorted(preview_dir.glob("preview_out*.png"))
    return True, rendered_imgs, log_msg
