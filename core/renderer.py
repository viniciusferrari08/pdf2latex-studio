#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renderização de páginas de PDF para PNG e recorte de fallback para figuras complexas."""

import subprocess
from pathlib import Path
from typing import List, Optional
from PIL import Image


def get_pdf_page_count(pdf_path: Path) -> int:
    """Obtém o número total de páginas do PDF usando pdfinfo."""
    try:
        res = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        for line in res.stdout.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":")[1].strip())
    except Exception:
        pass
    return 0


def render_page_to_png(
    pdf_path: Path,
    page_num: int,
    output_dir: Path,
    dpi: int = 200,
    force: bool = False,
) -> Path:
    """Renderiza uma página específica do PDF para PNG de alta resolução."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = output_dir / f"page_{page_num:03d}"
    expected_png = output_dir / f"page_{page_num:03d}.png"

    if expected_png.exists() and not force:
        return expected_png

    # Remove arquivos antigos do mesmo prefixo se force=True
    for old in output_dir.glob(f"page_{page_num:03d}*.png"):
        old.unlink()

    cmd = [
        "pdftoppm",
        "-png",
        "-r", str(dpi),
        "-f", str(page_num),
        "-l", str(page_num),
        str(pdf_path),
        str(output_prefix),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    generated = sorted(output_dir.glob(f"page_{page_num:03d}-*.png"))
    if generated:
        generated[0].rename(expected_png)
        return expected_png
    if expected_png.exists():
        return expected_png
    raise FileNotFoundError(f"Falha ao renderizar página {page_num} de {pdf_path.name}")


def render_all_pages(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 200,
    force: bool = False,
) -> List[Path]:
    """Renderiza todas as páginas de um PDF para PNG."""
    total = get_pdf_page_count(pdf_path)
    paths: List[Path] = []
    for p in range(1, total + 1):
        paths.append(render_page_to_png(pdf_path, p, output_dir, dpi=dpi, force=force))
    return paths


def crop_region_from_page(
    page_png: Path,
    dest_png: Path,
    xmin: float = 0.05,
    ymin: float = 0.10,
    xmax: float = 0.95,
    ymax: float = 0.90,
) -> Path:
    """Recorta uma região normalizada [0..1] da imagem da página para fallback gráfico."""
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(page_png) as img:
        w, h = img.size
        left = max(0, min(w - 1, int(xmin * w)))
        top = max(0, min(h - 1, int(ymin * h)))
        right = max(left + 10, min(w, int(xmax * w)))
        bottom = max(top + 10, min(h, int(ymax * h)))
        cropped = img.crop((left, top, right, bottom))
        cropped.save(dest_png, format="PNG")
    return dest_png
