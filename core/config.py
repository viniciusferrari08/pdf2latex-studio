#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gerenciamento de configurações, metadados, cores e persistência de projetos."""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE_DIR / "projects"
TEMPLATES_DIR = BASE_DIR / "templates"


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Converte cor hexadecimal (#42A3FB) para tupla RGB (66, 163, 251)."""
    clean = hex_color.strip().lstrip("#")
    if len(clean) != 6:
        return (66, 163, 251)
    try:
        return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
    except ValueError:
        return (66, 163, 251)


def darken_hex(hex_color: str, factor: float = 0.55) -> str:
    """Escurece uma cor hex para uso em títulos e links."""
    r, g, b = hex_to_rgb(hex_color)
    dr = max(0, min(255, int(r * factor)))
    dg = max(0, min(255, int(g * factor)))
    db = max(0, min(255, int(b * factor)))
    return f"#{dr:02X}{dg:02X}{db:02X}"


def sanitize_slug(text: str) -> str:
    """Gera identificador seguro de pasta para projetos."""
    slug = re.sub(r"[^\w\s-]", "", text.strip().lower())
    slug = re.sub(r"[\s_-]+", "_", slug).strip("_")
    return slug or f"projeto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def load_env_api_key(env_path: Optional[Path] = None) -> str:
    """Carrega chave da API Gemini do ambiente ou de .env sem encerrar o processo."""
    target = env_path or (BASE_DIR / ".env")
    if target.exists():
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


@dataclass
class ChapterInfo:
    """Representa um PDF de entrada (ou capítulo em modo compêndio)."""
    filename: str
    slug: str
    title: str
    order: int
    total_pages: int = 0


@dataclass
class ProjectConfig:
    """Configurações e metadados persistidos de um projeto PDF2LaTeX Studio."""
    project_id: str
    mode: str = "single"  # "single" ou "multi"
    preset: str = "cap12_report"  # "cap12_report" ou "article"
    title: str = "Notas de Aula Transcritas"
    subtitle: str = "Compêndio Digital em LaTeX"
    course_code: str = "Código -- Nome da Disciplina"
    institution: str = "Nome da Instituição"
    department: str = "Centro / Departamento"
    program: str = "Programa de Graduação / Pós-Graduação"
    semester: str = "2026/02"
    professor: str = "Nome do Docente / Autor"
    transcriber: str = "Responsável pela Transcrição"
    contact_email: str = "contato@exemplo.com"
    include_ai_disclaimer: bool = True
    primary_color_hex: str = "#42A3FB"
    dark_color_hex: str = "#145AA0"
    model: str = "gemini-3.5-flash"
    dpi: int = 200
    auto_number_equations: bool = True
    doc_version: str = "v1.0"
    custom_preamble: str = ""
    chapters: List[Dict] = field(default_factory=list)
    reference_books: List[Dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def project_dir(self) -> Path:
        if not self.project_id or "/" in self.project_id or "\\" in self.project_id or ".." in self.project_id:
            raise ValueError(f"ID de projeto inválido: {self.project_id}")
        target = (PROJECTS_DIR / self.project_id).resolve()
        if not target.is_relative_to(PROJECTS_DIR.resolve()):
            raise ValueError("Caminho de projeto fora do diretório permitido.")
        return target

    def save(self) -> Path:
        pdir = self.project_dir()
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "raw_pdfs").mkdir(exist_ok=True)
        (pdir / "page_images").mkdir(exist_ok=True)
        (pdir / "page_tex").mkdir(exist_ok=True)
        (pdir / "references").mkdir(exist_ok=True)
        (pdir / "versions").mkdir(exist_ok=True)
        meta_path = pdir / "metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        return meta_path

    @classmethod
    def load(cls, project_id: str) -> Optional["ProjectConfig"]:
        if not project_id or "/" in project_id or "\\" in project_id or ".." in project_id:
            return None
        meta_path = (PROJECTS_DIR / project_id / "metadata.json").resolve()
        if not meta_path.is_relative_to(PROJECTS_DIR.resolve()) or not meta_path.exists():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def list_projects() -> List[ProjectConfig]:
    """Lista todos os projetos salvos em disco ordenados por data de criação."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    items: List[ProjectConfig] = []
    for entry in PROJECTS_DIR.iterdir():
        if entry.is_dir() and (entry / "metadata.json").exists():
            cfg = ProjectConfig.load(entry.name)
            if cfg:
                items.append(cfg)
    items.sort(key=lambda c: c.created_at, reverse=True)
    return items
