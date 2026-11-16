#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Empacotamento de projeto completo em ZIP com código-fonte LaTeX e script de compilação."""

import zipfile
from pathlib import Path

from core.config import ProjectConfig


COMPILE_SH_CONTENT = """#!/usr/bin/env bash
set -e
echo "Compilando master.tex (Passagem 1)..."
pdflatex -interaction=nonstopmode master.tex
echo "Compilando master.tex (Passagem 2 - Sumário e Referências)..."
pdflatex -interaction=nonstopmode master.tex
echo "Concluído! Arquivo gerado: master.pdf"
"""


def create_source_zip(cfg: ProjectConfig) -> Path:
    """Cria um arquivo ZIP contendo master.tex, páginas, imagens recortadas e compile.sh."""
    pdir = cfg.project_dir()
    zip_path = pdir / f"{cfg.project_id}_latex_completo.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        master_tex = pdir / "master.tex"
        if master_tex.exists():
            zf.write(master_tex, arcname="master.tex")

        master_pdf = pdir / "master.pdf"
        if master_pdf.exists():
            zf.write(master_pdf, arcname="master.pdf")

        meta = pdir / "metadata.json"
        if meta.exists():
            zf.write(meta, arcname="metadata.json")

        for folder_name in ["page_tex", "images"]:
            folder = pdir / folder_name
            if folder.exists():
                for file in folder.rglob("*"):
                    if file.is_file():
                        zf.write(file, arcname=str(file.relative_to(pdir)))

        zf.writestr("compile.sh", COMPILE_SH_CONTENT)

    return zip_path
