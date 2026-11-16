#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF2LaTeX Studio - Aplicação Web Local (Streamlit)
Converte qualquer PDF (notas manuscritas, listas, livros ou artigos) para código LaTeX
estruturado com numeração de equações por seção, referências no texto, diagramas TikZ
e diagramação acadêmica padrão Capítulo 12.
"""

import shutil
import time
from pathlib import Path
from typing import Dict, List

import streamlit as st

from core.config import (
    BASE_DIR,
    ProjectConfig,
    darken_hex,
    list_projects,
    load_env_api_key,
    sanitize_slug,
)
from core.latex_compiler import (
    compile_single_page_preview,
    compile_tex_to_pdf,
    is_pdflatex_available,
)
from core.packager import create_source_zip
from core.postprocessor import assemble_master_tex, get_default_template_text
from core.renderer import get_pdf_page_count, render_all_pages, render_page_to_png
from core.transcriber import AVAILABLE_MODELS, transcribe_page_image

# ---------------------------------------------------------------------------
# Configuração da Página & Estilo Visual
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="PDF2LaTeX Studio",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .studio-banner {
        background: linear-gradient(90deg, #145AA0 0%, #42A3FB 100%);
        padding: 1.1rem 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1.2rem;
    }
    .studio-banner h1 {
        margin: 0;
        font-size: 1.8rem;
        color: white;
    }
    .studio-banner p {
        margin: 0.25rem 0 0 0;
        opacity: 0.92;
        font-size: 0.95rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    if "api_key" not in st.session_state:
        st.session_state["api_key"] = load_env_api_key()
    if "active_project_id" not in st.session_state:
        existing = list_projects()
        st.session_state["active_project_id"] = existing[0].project_id if existing else None
    if "rev_chapter_idx" not in st.session_state:
        st.session_state["rev_chapter_idx"] = 0
    if "rev_page_num" not in st.session_state:
        st.session_state["rev_page_num"] = 1
    if "preview_imgs" not in st.session_state:
        st.session_state["preview_imgs"] = []


def get_active_project() -> ProjectConfig | None:
    pid = st.session_state.get("active_project_id")
    if not pid:
        return None
    return ProjectConfig.load(pid)


def count_transcribed_pages(cfg: ProjectConfig) -> tuple[int, int]:
    pdir = cfg.project_dir()
    total = 0
    done = 0
    for ch in cfg.chapters:
        slug = ch["slug"]
        tp = int(ch.get("total_pages", 0))
        total += tp
        tex_dir = pdir / "page_tex" / slug
        for p in range(1, tp + 1):
            if (tex_dir / f"page_{p:03d}.tex").exists():
                done += 1
    return done, total


# ---------------------------------------------------------------------------
# Sidebar: Gestão de Sessões & Diagnóstico do Sistema
# ---------------------------------------------------------------------------
def render_sidebar() -> ProjectConfig | None:
    with st.sidebar:
        st.markdown("### 📚 Projetos Salvos")
        projects = list_projects()
        if projects:
            options = {f"{p.title} ({p.project_id})": p.project_id for p in projects}
            labels = list(options.keys())
            current_pid = st.session_state.get("active_project_id")
            default_idx = 0
            for idx, lbl in enumerate(labels):
                if options[lbl] == current_pid:
                    default_idx = idx
                    break
            chosen_lbl = st.selectbox("Selecionar projeto ativo", labels, index=default_idx)
            chosen_pid = options[chosen_lbl]
            if chosen_pid != current_pid:
                st.session_state["active_project_id"] = chosen_pid
                st.session_state["rev_chapter_idx"] = 0
                st.session_state["rev_page_num"] = 1
                st.session_state["preview_imgs"] = []
                st.rerun()
        else:
            st.info("Nenhum projeto criado ainda. Comece na aba **Novo Projeto**.")

        cfg = get_active_project()
        if cfg:
            done, total = count_transcribed_pages(cfg)
            st.markdown("---")
            st.markdown("### 📊 Progresso do Projeto")
            col1, col2 = st.columns(2)
            col1.metric("Capítulos/PDFs", len(cfg.chapters))
            col2.metric("Páginas", f"{done}/{total}")
            if total > 0:
                st.progress(done / total)

        st.markdown("---")
        st.markdown("### 🔑 Chave da API Gemini")
        api_key_input = st.text_input(
            "GEMINI_API_KEY",
            value=st.session_state.get("api_key", ""),
            type="password",
            help="Carregada automaticamente do arquivo .env se existir.",
        )
        st.session_state["api_key"] = api_key_input.strip()

        st.markdown("---")
        st.markdown("### 🛠️ Ambiente Local")
        st.write(f"- `pdflatex`: {'✅ Disponível' if is_pdflatex_available() else '❌ Ausente'}")
        st.write(f"- `pdftoppm`: {'✅ Disponível' if shutil.which('pdftoppm') else '❌ Ausente'}")
        st.write(f"- API Key: {'✅ Configurada' if st.session_state['api_key'] else '⚠️ Não informada'}")

    return get_active_project()


# ---------------------------------------------------------------------------
# Aba 1: Novo Projeto & Upload de PDFs
# ---------------------------------------------------------------------------
def tab_upload_and_project() -> None:
    st.subheader("Criar Novo Projeto ou Adicionar PDFs")

    mode_label = st.radio(
        "Modo de Entrada",
        [
            "Documento Único (1 PDF completo)",
            "Compêndio / Apostila (Múltiplos PDFs como Capítulos I, II, III...)",
        ],
        horizontal=True,
    )
    mode = "single" if mode_label.startswith("Documento") else "multi"

    col_name, col_model, col_dpi = st.columns([2, 1, 1])
    with col_name:
        proj_name = st.text_input("Nome do Projeto", value="Notas de Aula - Novo Curso")
    with col_model:
        model = st.selectbox("Modelo Gemini", AVAILABLE_MODELS, index=0)
    with col_dpi:
        dpi = st.slider("Resolução (DPI)", min_value=120, max_value=300, value=200, step=20)

    uploaded_files = st.file_uploader(
        "Selecione o(s) arquivo(s) PDF",
        type=["pdf"],
        accept_multiple_files=(mode == "multi"),
    )

    if uploaded_files:
        files_list = uploaded_files if isinstance(uploaded_files, list) else [uploaded_files]
        st.markdown("#### Ordem e Título dos Capítulos / Documentos")
        chapter_defs: List[Dict] = []
        for idx, up in enumerate(files_list, start=1):
            c1, c2 = st.columns([1, 3])
            with c1:
                order_val = st.number_input(
                    f"Ordem ({up.name})",
                    min_value=1,
                    max_value=100,
                    value=idx,
                    key=f"ord_{idx}_{up.name}",
                )
            with c2:
                default_title = Path(up.name).stem
                ch_title = st.text_input(
                    f"Título do Capítulo {idx}",
                    value=default_title,
                    key=f"title_{idx}_{up.name}",
                )
            chapter_defs.append({
                "file": up,
                "order": int(order_val),
                "title": ch_title.strip() or default_title,
                "slug": sanitize_slug(f"{int(order_val):02d}_{Path(up.name).stem}"),
            })

        if st.button("📥 Criar Projeto e Renderizar Páginas", type="primary"):
            if not shutil.which("pdftoppm"):
                st.error("O utilitário 'pdftoppm' não está disponível no sistema.")
                return

            pid = sanitize_slug(proj_name)
            # Evita sobrescrever silenciosamente se já existir
            if (BASE_DIR / "projects" / pid / "metadata.json").exists():
                pid = f"{pid}_{int(time.time()) % 10000}"

            preset = "cap12_report" if mode == "multi" else "cap12_report"
            cfg = ProjectConfig(
                project_id=pid,
                mode=mode,
                preset=preset,
                title=proj_name.strip() or "Documento LaTeX",
                model=model,
                dpi=dpi,
            )
            pdir = cfg.project_dir()
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "raw_pdfs").mkdir(exist_ok=True)
            (pdir / "page_images").mkdir(exist_ok=True)
            (pdir / "page_tex").mkdir(exist_ok=True)

            chapter_defs.sort(key=lambda x: x["order"])
            saved_chapters = []
            progress = st.progress(0.0, text="Salvando e renderizando PDFs...")

            for idx, item in enumerate(chapter_defs):
                up = item["file"]
                slug = item["slug"]
                safe_pdf_name = Path(up.name).name
                raw_pdf_path = (pdir / "raw_pdfs" / safe_pdf_name).resolve()
                if not raw_pdf_path.is_relative_to((pdir / "raw_pdfs").resolve()):
                    raise ValueError(f"Nome de arquivo inválido: {up.name}")
                raw_pdf_path.write_bytes(up.getvalue())

                total_pages = get_pdf_page_count(raw_pdf_path)
                img_dir = pdir / "page_images" / slug
                render_all_pages(raw_pdf_path, img_dir, dpi=dpi)
                (pdir / "page_tex" / slug).mkdir(parents=True, exist_ok=True)

                saved_chapters.append({
                    "filename": safe_pdf_name,
                    "slug": slug,
                    "title": item["title"],
                    "order": item["order"],
                    "total_pages": total_pages,
                })
                progress.progress((idx + 1) / len(chapter_defs), text=f"Renderizado: {up.name} ({total_pages} págs.)")

            cfg.chapters = saved_chapters
            cfg.save()
            st.session_state["active_project_id"] = cfg.project_id
            st.session_state["rev_chapter_idx"] = 0
            st.session_state["rev_page_num"] = 1
            st.success(f"Projeto **{cfg.title}** criado com sucesso ({sum(c['total_pages'] for c in saved_chapters)} páginas renderizadas)!")
            st.rerun()


# ---------------------------------------------------------------------------
# Aba 2: Metadados, Design Visual & Preâmbulo Avançado
# ---------------------------------------------------------------------------
def tab_design_and_metadata(cfg: ProjectConfig | None) -> None:
    if not cfg:
        st.info("Crie ou selecione um projeto para configurar metadados e design.")
        return

    st.subheader("🎨 Identidade Visual, Capa e Preâmbulo LaTeX")

    with st.form("design_form"):
        c1, c2 = st.columns(2)
        with c1:
            preset_choice = st.selectbox(
                "Template / Classe LaTeX",
                ["cap12_report", "article"],
                index=0 if cfg.preset == "cap12_report" else 1,
                format_func=lambda x: (
                    "Livro / Apostila (Padrão Cap. 12: Capa + Capítulos Romanos)"
                    if x == "cap12_report"
                    else "Artigo Acadêmico Compacto (Seções Romanas)"
                ),
            )
            title = st.text_input("Título Principal", value=cfg.title)
            subtitle = st.text_input("Subtítulo", value=cfg.subtitle)
            course_code = st.text_input("Identificador no Cabeçalho Direito", value=cfg.course_code)
            semester = st.text_input("Semestre / Período (Rodapé Esquerdo)", value=cfg.semester)

        with c2:
            institution = st.text_input("Instituição", value=cfg.institution)
            department = st.text_input("Departamento / Centro", value=cfg.department)
            program = st.text_input("Programa / Curso", value=cfg.program)
            professor = st.text_input("Docente / Autor Original", value=cfg.professor)
            transcriber = st.text_input("Responsável pela Transcrição", value=cfg.transcriber)
            contact_email = st.text_input("E-mail de Contato / Erratas", value=cfg.contact_email)

        st.markdown("---")
        col_c1, col_c2, col_opt1, col_opt2 = st.columns(4)
        with col_c1:
            primary_color = st.color_picker("Cor Principal de Destaque", value=cfg.primary_color_hex)
        with col_c2:
            auto_dark = darken_hex(primary_color)
            dark_color = st.color_picker("Cor Secundária (Títulos/Links)", value=cfg.dark_color_hex or auto_dark)
        with col_opt1:
            include_ai = st.checkbox("Incluir Aviso de IA + E-mail", value=cfg.include_ai_disclaimer)
        with col_opt2:
            auto_eq = st.checkbox("Enumerar Equações (I.1, I.2...)", value=cfg.auto_number_equations)

        st.markdown("---")
        with st.expander("🛠️ Editor Avançado de Preâmbulo LaTeX (Opcional)", expanded=bool(cfg.custom_preamble)):
            st.caption(
                "Deixe em branco para usar o template selecionado automaticamente com os placeholders "
                "(__PRIMARY_R__, __TITLE__, etc.), ou cole/edite o preâmbulo completo abaixo."
            )
            default_preview = cfg.custom_preamble if cfg.custom_preamble else get_default_template_text(preset_choice)
            use_custom = st.checkbox("Ativar preâmbulo customizado editado abaixo", value=bool(cfg.custom_preamble))
            custom_text = st.text_area("Código do Preâmbulo (.tex)", value=default_preview, height=340)

        submitted = st.form_submit_button("💾 Salvar Configurações de Design", type="primary")
        if submitted:
            cfg.preset = preset_choice
            cfg.title = title
            cfg.subtitle = subtitle
            cfg.course_code = course_code
            cfg.semester = semester
            cfg.institution = institution
            cfg.department = department
            cfg.program = program
            cfg.professor = professor
            cfg.transcriber = transcriber
            cfg.contact_email = contact_email
            cfg.primary_color_hex = primary_color
            cfg.dark_color_hex = dark_color
            cfg.include_ai_disclaimer = include_ai
            cfg.auto_number_equations = auto_eq
            cfg.custom_preamble = custom_text if use_custom else ""
            cfg.save()
            st.success("Configurações visuais salvas!")


# ---------------------------------------------------------------------------
# Aba 3: Processamento Automático em Lote
# ---------------------------------------------------------------------------
def tab_batch_processing(cfg: ProjectConfig | None) -> None:
    if not cfg:
        st.info("Crie ou selecione um projeto primeiro.")
        return

    st.subheader("⚡ Transcrição em Lote com IA Multimodal")
    pdir = cfg.project_dir()

    rows = []
    for ch in sorted(cfg.chapters, key=lambda c: c["order"]):
        slug = ch["slug"]
        tp = int(ch.get("total_pages", 0))
        tex_dir = pdir / "page_tex" / slug
        done = sum(1 for p in range(1, tp + 1) if (tex_dir / f"page_{p:03d}.tex").exists())
        rows.append({
            "Ordem": ch["order"],
            "Capítulo / Arquivo": ch["title"],
            "PDF": ch["filename"],
            "Páginas Transcritas": f"{done} / {tp}",
            "Status": "✅ Concluído" if done == tp and tp > 0 else "⏳ Pendente",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        model_run = st.selectbox("Modelo para esta execução", AVAILABLE_MODELS, index=AVAILABLE_MODELS.index(cfg.model) if cfg.model in AVAILABLE_MODELS else 0)
    with c2:
        chapter_filter = st.selectbox(
            "Escopo",
            ["Todos os Capítulos"] + [ch["title"] for ch in cfg.chapters],
        )
    with c3:
        force_rerun = st.checkbox("Forçar retranscrição do cache", value=False)

    extra_prompt = st.text_input(
        "Instruções adicionais opcionais para a IA (ex: 'Idioma inglês, preserve matrizes em bmatrix')",
        value="",
    )

    if st.button("🚀 Iniciar Transcrição Automática e Compilar PDF", type="primary"):
        api_key = st.session_state.get("api_key", "").strip()
        if not api_key:
            st.error("Informe a chave da API Gemini na barra lateral antes de iniciar.")
            return

        cfg.model = model_run
        cfg.save()

        targets = [
            ch for ch in sorted(cfg.chapters, key=lambda c: c["order"])
            if chapter_filter == "Todos os Capítulos" or ch["title"] == chapter_filter
        ]
        total_tasks = sum(int(ch.get("total_pages", 0)) for ch in targets)
        if total_tasks == 0:
            st.warning("Nenhuma página encontrada para processar.")
            return

        progress_bar = st.progress(0.0)
        status_box = st.empty()
        log_box = st.empty()
        logs: List[str] = []
        completed = 0

        for ch in targets:
            slug = ch["slug"]
            tp = int(ch["total_pages"])
            img_dir = pdir / "page_images" / slug
            tex_dir = pdir / "page_tex" / slug
            tex_dir.mkdir(parents=True, exist_ok=True)
            raw_pdf = pdir / "raw_pdfs" / ch["filename"]

            for pnum in range(1, tp + 1):
                completed += 1
                tex_file = tex_dir / f"page_{pnum:03d}.tex"
                png_file = img_dir / f"page_{pnum:03d}.png"

                if tex_file.exists() and not force_rerun:
                    logs.append(f"⏭️ [{ch['title']}] Pág. {pnum}/{tp} já está em cache.")
                    progress_bar.progress(completed / total_tasks)
                    log_box.code("\n".join(logs[-12:]))
                    continue

                if not png_file.exists() and raw_pdf.exists():
                    render_page_to_png(raw_pdf, pnum, img_dir, dpi=cfg.dpi)

                status_box.info(f"Transcrevendo **{ch['title']}** — Página **{pnum}/{tp}** com `{model_run}`...")
                try:
                    latex_code = transcribe_page_image(
                        api_key=api_key,
                        image_path=png_file,
                        page_num=pnum,
                        chapter_slug=slug,
                        model=model_run,
                        extra_instruction=extra_prompt,
                    )
                    tex_file.write_text(latex_code, encoding="utf-8")
                    logs.append(f"✅ [{ch['title']}] Pág. {pnum}/{tp} transcrita com sucesso.")
                except Exception as exc:
                    logs.append(f"❌ [{ch['title']}] Pág. {pnum}/{tp} falhou: {exc}")

                progress_bar.progress(completed / total_tasks)
                log_box.code("\n".join(logs[-12:]))

        status_box.info("Montando `master.tex` e compilando PDF final com `pdflatex`...")
        master_path = assemble_master_tex(cfg)
        ok, pdf_path, comp_log = compile_tex_to_pdf(master_path, passes=2)
        if ok:
            status_box.success(f"🎉 Processamento concluído e PDF compilado: `{pdf_path.name}`!")
        else:
            status_box.warning("⚠️ Transcrição salva, mas o `pdflatex` apontou erros de compilação. Verifique na aba Compilação ou Revisão.")
            with st.expander("Detalhes do Log LaTeX"):
                st.code(comp_log)


# ---------------------------------------------------------------------------
# Aba 4: Revisão Interativa Lado a Lado
# ---------------------------------------------------------------------------
def tab_side_by_side_review(cfg: ProjectConfig | None) -> None:
    if not cfg or not cfg.chapters:
        st.info("Crie um projeto com páginas renderizadas para utilizar o revisor.")
        return

    st.subheader("🔍 Revisão Lado a Lado: Página Original vs. LaTeX / TikZ")
    pdir = cfg.project_dir()
    chapters = sorted(cfg.chapters, key=lambda c: c["order"])

    c_sel, c_prev, c_pnum, c_next = st.columns([3, 1, 2, 1])
    with c_sel:
        ch_titles = [f"{ch['order']}. {ch['title']}" for ch in chapters]
        ch_idx = st.selectbox(
            "Capítulo / PDF",
            range(len(chapters)),
            index=min(st.session_state["rev_chapter_idx"], len(chapters) - 1),
            format_func=lambda i: ch_titles[i],
        )
        if ch_idx != st.session_state["rev_chapter_idx"]:
            st.session_state["rev_chapter_idx"] = ch_idx
            st.session_state["rev_page_num"] = 1
            st.session_state["preview_imgs"] = []

    ch = chapters[st.session_state["rev_chapter_idx"]]
    total_pages = max(1, int(ch.get("total_pages", 1)))
    slug = ch["slug"]

    with c_prev:
        st.write("")
        st.write("")
        if st.button("⬅️ Anterior", use_container_width=True) and st.session_state["rev_page_num"] > 1:
            st.session_state["rev_page_num"] -= 1
            st.session_state["preview_imgs"] = []
            st.rerun()

    with c_pnum:
        sel_page = st.number_input(
            f"Página (1 a {total_pages})",
            min_value=1,
            max_value=total_pages,
            value=min(st.session_state["rev_page_num"], total_pages),
        )
        if sel_page != st.session_state["rev_page_num"]:
            st.session_state["rev_page_num"] = int(sel_page)
            st.session_state["preview_imgs"] = []

    with c_next:
        st.write("")
        st.write("")
        if st.button("Próxima ➡️", use_container_width=True) and st.session_state["rev_page_num"] < total_pages:
            st.session_state["rev_page_num"] += 1
            st.session_state["preview_imgs"] = []
            st.rerun()

    pnum = st.session_state["rev_page_num"]
    img_path = pdir / "page_images" / slug / f"page_{pnum:03d}.png"
    tex_path = pdir / "page_tex" / slug / f"page_{pnum:03d}.tex"

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown(f"**Imagem Original — Página {pnum}/{total_pages}**")
        if img_path.exists():
            st.image(str(img_path), use_container_width=True)
        else:
            st.warning("Imagem da página não encontrada.")

    with col_right:
        st.markdown(f"**Código LaTeX Editável (`page_{pnum:03d}.tex`)**")
        current_tex = tex_path.read_text(encoding="utf-8") if tex_path.exists() else ""
        edited_tex = st.text_area(
            "Editor LaTeX",
            value=current_tex,
            height=480,
            label_visibility="collapsed",
            key=f"editor_{cfg.project_id}_{slug}_{pnum}",
        )

        b1, b2 = st.columns(2)
        with b1:
            if st.button("💾 Salvar Alterações", use_container_width=True, type="primary"):
                tex_path.parent.mkdir(parents=True, exist_ok=True)
                tex_path.write_text(edited_tex, encoding="utf-8")
                st.success("Página salva em cache!")
        with b2:
            if st.button("👁️ Compilar Prévia desta Página", use_container_width=True):
                tex_path.parent.mkdir(parents=True, exist_ok=True)
                tex_path.write_text(edited_tex, encoding="utf-8")
                with st.spinner("Compilando prévia LaTeX + TikZ..."):
                    ok, imgs, log_msg = compile_single_page_preview(cfg, slug, pnum, edited_tex)
                    if ok and imgs:
                        st.session_state["preview_imgs"] = [str(p) for p in imgs]
                        st.success("Prévia renderizada abaixo!")
                    else:
                        st.session_state["preview_imgs"] = []
                        st.error("Erro ao compilar esta página:")
                        st.code(log_msg)

        with st.expander("🤖 Regerar Esta Página com IA (Ex: Ajustar TikZ ou Equações)"):
            regen_hint = st.text_input(
                "Instrução de melhoria",
                placeholder="Ex: Reproduza o gráfico de potencial como figura TikZ com eixos azuis",
                key=f"hint_{slug}_{pnum}",
            )
            if st.button("🔄 Regerar Agora", key=f"regen_btn_{slug}_{pnum}"):
                api_key = st.session_state.get("api_key", "").strip()
                if not api_key:
                    st.error("Informe a chave da API Gemini na barra lateral.")
                elif not img_path.exists():
                    st.error("Imagem original ausente.")
                else:
                    with st.spinner(f"Reprocessando página {pnum} com {cfg.model}..."):
                        new_code = transcribe_page_image(
                            api_key=api_key,
                            image_path=img_path,
                            page_num=pnum,
                            chapter_slug=slug,
                            model=cfg.model,
                            extra_instruction=regen_hint,
                        )
                        tex_path.write_text(new_code, encoding="utf-8")
                        st.success("Página regerada com sucesso!")
                        st.rerun()

        if st.session_state.get("preview_imgs"):
            st.markdown("---")
            st.markdown("**Resultado Renderizado (LaTeX + TikZ):**")
            for p_img in st.session_state["preview_imgs"]:
                if Path(p_img).exists():
                    st.image(p_img, use_container_width=True)


# ---------------------------------------------------------------------------
# Aba 5: Compilação Final, Visualizador de PDF e Exportação
# ---------------------------------------------------------------------------
def tab_compile_and_export(cfg: ProjectConfig | None) -> None:
    if not cfg:
        st.info("Crie ou selecione um projeto primeiro.")
        return

    st.subheader("🚀 Compilação Final e Exportação")
    pdir = cfg.project_dir()
    master_tex = pdir / "master.tex"
    master_pdf = pdir / "master.pdf"

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("🔨 Montar master.tex e Compilar PDF (2 passagens)", type="primary", use_container_width=True):
            with st.spinner("Montando preâmbulo, equações numeradas e compilando com pdflatex..."):
                m_path = assemble_master_tex(cfg)
                ok, pdf_out, log_out = compile_tex_to_pdf(m_path, passes=2)
                if ok:
                    st.success("PDF compilado com sucesso!")
                else:
                    st.error("Falha na compilação LaTeX:")
                    st.code(log_out)

    with c2:
        dl1, dl2 = st.columns(2)
        with dl1:
            if master_pdf.exists():
                st.download_button(
                    "📥 Baixar PDF Compilado",
                    data=master_pdf.read_bytes(),
                    file_name=f"{cfg.project_id}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        with dl2:
            if master_tex.exists() or any((pdir / "page_tex").rglob("*.tex")):
                if not master_tex.exists():
                    assemble_master_tex(cfg)
                zip_path = create_source_zip(cfg)
                st.download_button(
                    "📦 Baixar Código-Fonte (.ZIP)",
                    data=zip_path.read_bytes(),
                    file_name=zip_path.name,
                    mime="application/zip",
                    use_container_width=True,
                )

    st.markdown("---")
    if master_pdf.exists():
        st.markdown("### 📄 Pré-visualização do PDF Final")
        try:
            st.pdf(str(master_pdf), height=760)
        except Exception:
            st.info("Visualizador nativo indisponível; exibindo páginas renderizadas via pdftoppm:")
            prev_all = pdir / "_pdf_preview"
            prev_all.mkdir(exist_ok=True)
            render_all_pages(master_pdf, prev_all, dpi=120)
            for p_img in sorted(prev_all.glob("page_*.png"))[:10]:
                st.image(str(p_img), use_container_width=True)
    else:
        st.info("Clique no botão acima para gerar e visualizar o PDF consolidado.")


# ---------------------------------------------------------------------------
# Execução Principal
# ---------------------------------------------------------------------------
def main() -> None:
    init_session_state()

    st.markdown(
        """
        <div class="studio-banner">
            <h1>📘 PDF2LaTeX Studio</h1>
            <p>Conversor Inteligente de Manuscritos e PDFs para LaTeX Acadêmico — Padrão Tipográfico Capítulo 12 (Libertine, Equações Numeradas & TikZ)</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cfg = render_sidebar()

    tabs = st.tabs([
        "📂 Novo Projeto & Upload",
        "🎨 Metadados & Design",
        "⚡ Processamento em Lote",
        "🔍 Revisão Lado a Lado",
        "🚀 Compilação & Download",
    ])

    with tabs[0]:
        tab_upload_and_project()
    with tabs[1]:
        tab_design_and_metadata(cfg)
    with tabs[2]:
        tab_batch_processing(cfg)
    with tabs[3]:
        tab_side_by_side_review(cfg)
    with tabs[4]:
        tab_compile_and_export(cfg)


if __name__ == "__main__":
    main()
