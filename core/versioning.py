#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sistema de versionamento de livros: criação, listagem e restauração de snapshots."""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.config import ProjectConfig


def sanitize_version_tag(tag: str) -> str:
    """Normaliza uma tag de versão (ex: 'v1.0', 'v1.2-revisado') para nome seguro de diretório."""
    clean = re.sub(r"[^\w.\-]", "_", tag.strip())
    clean = clean.strip("._-")
    if not clean or ".." in clean:
        return f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return clean


def create_version_snapshot(cfg: ProjectConfig, version_tag: str, notes: str = "") -> Path:
    """
    Salva um snapshot completo (master.pdf, master.tex, metadata.json e page_tex/)
    dentro de projects/<id>/versions/<version_tag>/.
    """
    pdir = cfg.project_dir()
    safe_tag = sanitize_version_tag(version_tag)
    vdir = (pdir / "versions" / safe_tag).resolve()
    if not vdir.is_relative_to((pdir / "versions").resolve()):
        raise ValueError("Tag de versão inválida.")

    if vdir.exists():
        shutil.rmtree(vdir)
    vdir.mkdir(parents=True, exist_ok=True)

    # Atualiza a versão ativa na configuração do projeto
    cfg.doc_version = safe_tag
    cfg.save()

    for fname in ["master.tex", "master.pdf", "metadata.json"]:
        src = pdir / fname
        if src.exists():
            shutil.copy2(src, vdir / fname)

    src_pages = pdir / "page_tex"
    if src_pages.exists():
        shutil.copytree(src_pages, vdir / "page_tex")

    info = {
        "version_tag": safe_tag,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes": notes.strip(),
        "has_pdf": (vdir / "master.pdf").exists(),
        "has_tex": (vdir / "master.tex").exists(),
    }
    (vdir / "version_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return vdir


def list_versions(cfg: ProjectConfig) -> List[Dict]:
    """Lista todas as versões salvas do projeto ordenadas da mais recente para a mais antiga."""
    vroot = cfg.project_dir() / "versions"
    if not vroot.exists():
        return []

    versions: List[Dict] = []
    for entry in vroot.iterdir():
        info_path = entry / "version_info.json"
        if entry.is_dir() and info_path.exists():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
                info["dir"] = str(entry)
                versions.append(info)
            except Exception:
                continue

    versions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return versions


def restore_version_snapshot(cfg: ProjectConfig, version_tag: str) -> None:
    """Restaura os arquivos page_tex/, master.tex, master.pdf e doc_version a partir de um snapshot."""
    pdir = cfg.project_dir()
    safe_tag = sanitize_version_tag(version_tag)
    vdir = (pdir / "versions" / safe_tag).resolve()
    if not vdir.is_relative_to((pdir / "versions").resolve()) or not vdir.exists():
        raise FileNotFoundError(f"Snapshot de versão '{safe_tag}' não encontrado.")

    snap_pages = vdir / "page_tex"
    if snap_pages.exists():
        dst_pages = pdir / "page_tex"
        if dst_pages.exists():
            shutil.rmtree(dst_pages)
        shutil.copytree(snap_pages, dst_pages)

    for fname in ["master.tex", "master.pdf"]:
        src = vdir / fname
        if src.exists():
            shutil.copy2(src, pdir / fname)

    cfg.doc_version = safe_tag
    cfg.save()
