#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Revisor inteligente de erros LaTeX: localiza a página culpada, corrige via IA e sugere regras para o SYSTEM_PROMPT."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from google import genai
from google.genai import types

from core.config import BASE_DIR
from core.transcriber import AVAILABLE_MODELS, clean_latex_response, get_effective_system_prompt

LEARNED_RULES_PATH = BASE_DIR / "core" / "learned_prompt_rules.json"


@dataclass
class ErrorLocation:
    master_line: int
    error_message: str
    chapter_slug: str
    page_num: int
    page_tex_path: Path
    master_context: str


def load_learned_prompt_rules() -> List[str]:
    """Carrega regras aprendidas persistidas em JSON."""
    if not LEARNED_RULES_PATH.exists():
        return []
    try:
        data = json.loads(LEARNED_RULES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return []


def save_learned_prompt_rules(rules: List[str]) -> None:
    """Salva a lista de regras aprendidas evitando duplicatas."""
    unique: List[str] = []
    for r in rules:
        clean = r.strip()
        if clean and clean not in unique:
            unique.append(clean)
    LEARNED_RULES_PATH.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_prompt_rule(rule: str) -> List[str]:
    """Adiciona uma nova regra aprendida ao SYSTEM_PROMPT persistente."""
    rules = load_learned_prompt_rules()
    clean = rule.strip()
    if clean and clean not in rules:
        rules.append(clean)
        save_learned_prompt_rules(rules)
    return rules


def locate_error_source(
    master_tex: Path,
    log_text: str,
    project_dir: Path,
) -> Optional[ErrorLocation]:
    """
    Analisa o log do pdflatex para identificar a linha (l.XXX) em master.tex
    e mapeia para o arquivo page_tex/<slug>/page_<N>.tex correspondente.
    """
    if not master_tex.exists():
        return None

    # Busca linha de erro (l.123 ...)
    line_match = re.search(r"^l\.(\d+)\s*(.*)$", log_text, flags=re.MULTILINE)
    if not line_match:
        return None

    err_line = int(line_match.group(1))
    # Captura também a mensagem "! ..." imediatamente anterior, se presente
    err_msgs = re.findall(r"^!\s+(.+)$", log_text, flags=re.MULTILINE)
    err_summary = err_msgs[-1] if err_msgs else line_match.group(2).strip()
    if line_match.group(2).strip():
        err_summary = f"{err_summary} | Trecho: {line_match.group(2).strip()}"

    master_lines = master_tex.read_text(encoding="utf-8").splitlines()
    idx = min(max(0, err_line - 1), len(master_lines) - 1)

    marker_re = re.compile(r"^%\s*---\s*([^\s|]+)\s*\|\s*Página\s*(\d+)\s*---\s*$")
    found_slug = ""
    found_page = 0
    for i in range(idx, -1, -1):
        m = marker_re.match(master_lines[i].strip())
        if m:
            found_slug = m.group(1).strip()
            found_page = int(m.group(2))
            break

    if not found_slug or found_page <= 0:
        return None

    page_tex_path = project_dir / "page_tex" / found_slug / f"page_{found_page:03d}.tex"
    start = max(0, idx - 5)
    end = min(len(master_lines), idx + 6)
    ctx = "\n".join(f"{k + 1}: {master_lines[k]}" for k in range(start, end))

    return ErrorLocation(
        master_line=err_line,
        error_message=err_summary,
        chapter_slug=found_slug,
        page_num=found_page,
        page_tex_path=page_tex_path,
        master_context=ctx,
    )


def review_and_fix_error(
    api_key: str,
    model: str,
    error_location: ErrorLocation,
    log_excerpt: str,
) -> Dict:
    """
    Envia o erro LaTeX, a página problemática e o SYSTEM_PROMPT atual para o Gemini,
    retornando diagnóstico, código corrigido e eventual sugestão de melhoria no SYSTEM_PROMPT.
    """
    if not error_location.page_tex_path.exists():
        raise FileNotFoundError(f"Arquivo da página não encontrado: {error_location.page_tex_path}")

    page_code = error_location.page_tex_path.read_text(encoding="utf-8")
    current_prompt = get_effective_system_prompt()

    reviewer_instruction = r"""Você é um engenheiro especialista em compilação LaTeX (pdflatex, TikZ, pgfplots, physics, amsmath) e engenharia de prompts.
Analise o erro de compilação ocorrido e devolva EXCLUSIVAMENTE um objeto JSON válido com estas 4 chaves:
{
  "diagnosis": "Explicação clara e concisa em português da causa raiz do erro LaTeX.",
  "fixed_page_tex": "O código completo e corrigido do arquivo page_XXX.tex (sem ```latex e sem preâmbulo).",
  "should_update_prompt": true ou false,
  "suggested_prompt_rule": "Se should_update_prompt for true, escreva uma regra curta e objetiva em português para adicionar ao SYSTEM_PROMPT evitando que a IA cometa esse erro em páginas futuras. Caso contrário, string vazia."
}
"""
    user_payload = (
        f"ERRO DO PDFLATEX:\n{error_location.error_message}\n\n"
        f"TRECHO DO LOG:\n{log_excerpt[-1200:]}\n\n"
        f"CONTEXTO EM master.tex (linha {error_location.master_line}):\n{error_location.master_context}\n\n"
        f"CÓDIGO ATUAL DE {error_location.page_tex_path.name}:\n{page_code}\n\n"
        f"SYSTEM_PROMPT ATUAL USADO NA TRANSCRIÇÃO:\n{current_prompt}"
    )

    client = genai.Client(api_key=api_key)
    models_to_try = [model] + [m for m in AVAILABLE_MODELS if m != model]
    last_exc: Optional[Exception] = None

    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=[reviewer_instruction, user_payload],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            if resp and resp.text:
                parsed = json.loads(resp.text)
                parsed["fixed_page_tex"] = clean_latex_response(str(parsed.get("fixed_page_tex", "")))
                parsed["diagnosis"] = str(parsed.get("diagnosis", "")).strip()
                parsed["should_update_prompt"] = bool(parsed.get("should_update_prompt", False))
                parsed["suggested_prompt_rule"] = str(parsed.get("suggested_prompt_rule", "")).strip()
                return parsed
        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc or RuntimeError("Não foi possível revisar o erro LaTeX com os modelos Gemini.")
