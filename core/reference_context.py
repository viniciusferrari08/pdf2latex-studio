#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Indexação local (pdftotext) e recuperação de trechos relevantes de livros-texto de referência."""

import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List


STOPWORDS_PT_EN = {
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "um", "uma",
    "o", "a", "os", "as", "e", "ou", "que", "para", "com", "por", "como", "se",
    "the", "of", "and", "in", "to", "is", "are", "for", "with", "on", "by", "that",
}


def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", text.lower())
    return [t for t in tokens if t not in STOPWORDS_PT_EN]


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extrai texto bruto de um PDF usando pdftotext (Poppler)."""
    res = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return res.stdout


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """Divide o texto em blocos contínuos com pequena sobreposição."""
    clean = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not clean:
        return []
    chunks: List[str] = []
    start = 0
    step = max(200, chunk_size - overlap)
    while start < len(clean):
        piece = clean[start : start + chunk_size].strip()
        if len(piece) > 80:
            chunks.append(piece)
        start += step
    return chunks


def index_reference_pdf(pdf_path: Path, index_dir: Path) -> Dict:
    """Extrai e indexa um livro-texto de referência em JSON local."""
    index_dir.mkdir(parents=True, exist_ok=True)
    raw_text = extract_text_from_pdf(pdf_path)
    chunks = chunk_text(raw_text)

    records = []
    for idx, ch in enumerate(chunks, start=1):
        records.append({
            "source": pdf_path.name,
            "chunk_id": idx,
            "text": ch,
            "tokens": dict(Counter(_tokenize(ch))),
        })

    out_json = index_dir / f"{pdf_path.stem}.index.json"
    out_json.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    return {
        "filename": pdf_path.name,
        "chunks_count": len(records),
        "chars_count": len(raw_text),
        "index_file": out_json.name,
    }


def retrieve_relevant_context(
    project_dir: Path,
    query_hint: str,
    top_k: int = 3,
    max_chars: int = 2400,
) -> str:
    """
    Busca os trechos mais relevantes dos livros-texto indexados usando pontuação TF-IDF leve.
    Retorna string formatada pronta para injeção no prompt do Gemini.
    """
    ref_dir = project_dir / "references"
    if not ref_dir.exists():
        return ""

    index_files = sorted(ref_dir.glob("*.index.json"))
    if not index_files:
        return ""

    all_records: List[Dict] = []
    for idx_file in index_files:
        try:
            data = json.loads(idx_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                all_records.extend(data)
        except Exception:
            continue

    if not all_records:
        return ""

    query_tokens = _tokenize(query_hint)
    if not query_tokens:
        # Fallback: devolve os primeiros trechos (sumário/introdução do livro)
        selected = all_records[:top_k]
    else:
        n_docs = len(all_records)
        df: Counter = Counter()
        for rec in all_records:
            toks = rec.get("tokens", {})
            for qt in set(query_tokens):
                if qt in toks:
                    df[qt] += 1

        scored = []
        for rec in all_records:
            toks = rec.get("tokens", {})
            score = 0.0
            for qt in query_tokens:
                tf = toks.get(qt, 0)
                if tf > 0:
                    idf = math.log((n_docs + 1) / (df[qt] + 1)) + 1.0
                    score += (1.0 + math.log(tf)) * idf
            if score > 0:
                scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [item[1] for item in scored[:top_k]] if scored else all_records[:1]

    parts: List[str] = []
    used = 0
    for rec in selected:
        snippet = f"[Referência: {rec.get('source', 'Livro')}]\n{rec.get('text', '').strip()}"
        if used + len(snippet) > max_chars:
            remaining = max_chars - used
            if remaining > 200:
                parts.append(snippet[:remaining] + "...")
            break
        parts.append(snippet)
        used += len(snippet) + 2

    return "\n\n".join(parts)
