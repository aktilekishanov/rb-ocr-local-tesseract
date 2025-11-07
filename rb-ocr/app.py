import os
import re
import json
import tempfile
from pathlib import Path
import streamlit as st

from rbidp.orchestrator import run_pipeline
from rbidp.core.errors import message_for

# --- Page setup ---
st.set_page_config(page_title="RB Loan Deferment IDP", layout="centered")

st.write("")
st.title("RB Loan Deferment IDP")
st.write("Загрузите один файл для распознавания (локальная обработка через Textract (Dev-OCR) & GPT (DMZ))")

# --- Basic paths ---
BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# --- Simple CSS tweaks ---
st.markdown(
    """
<style>
.block-container{max-width:980px;padding-top:1.25rem;}
.meta{color:#6b7280;font-size:0.92rem;margin:0.25rem 0 1rem 0;}
.meta code{background:#f3f4f6;border:1px solid #e5e7eb;padding:2px 6px;border-radius:6px;}
.card{border:1px solid #e5e7eb;border-radius:14px;background:#ffffff;box-shadow:0 2px 8px rgba(0,0,0,.04);} 
.card.pad{padding:22px;}
.result-card{border:1px solid #e5e7eb;border-radius:14px;padding:16px;background:#fafafa;}
.stButton>button{border-radius:10px;padding:.65rem 1rem;font-weight:600;}
.stDownloadButton>button{border-radius:10px;}
</style>
""",
    unsafe_allow_html=True,
)

# --- Reason -> doc types mapping (example) ---
reasons_map = {
    "Временная нетрудоспособность заемщика по причине болезни": [
        "Лист временной нетрудоспособности (больничный лист)",
        "Выписка из стационара (выписной эпикриз)",
        "Больничный лист на сопровождающего (если предусмотрено)",
        "Заключение врачебно-консультативной комиссии (ВКК)",
        "Справка об инвалидности",
        "Справка о степени утраты общей трудоспособности",
    ],
    "Уход заемщика в декретный отпуск": [
        "Лист временной нетрудоспособности (больничный лист)",
        "Приказ о выходе в декретный отпуск по уходу за ребенком",
        "Справка о выходе в декретный отпуск по уходу за ребенком",
    ],
    "Потеря дохода заемщика (увольнение, сокращение, отпуск без содержания и т.д.)": [
        "Приказ о расторжении трудового договора",
        "Справка о расторжении трудового договора",
        "Справка о регистрации в качестве безработного",
        "Приказ работодателя о предоставлении отпуска без сохранения заработной платы",
        "Справка о неполучении доходов",
        "Уведомление о регистрации в качестве лица, ищущего работу",
        "Лица, зарегистрированные в качестве безработных",
    ],
}

# --- Inputs outside form for dynamic selects ---
fio = st.text_input("ФИО", placeholder="Иванов Иван Иванович")

reason_options = ["Выберите причину"] + list(reasons_map.keys())
reason = st.selectbox(
    "Причина отсрочки",
    options=reason_options,
    index=0,
    help="Сначала выберите причину, затем подходящий тип документа",
    key="reason",
)

doc_options = ["Выберите тип документа"] + (
    reasons_map[reason] if reason in reasons_map else []
)
doc_type = st.selectbox(
    "Тип документа",
    options=doc_options,
    index=0,
    key="doc_type",
)


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-\.\s]", "_", name.strip())
    name = re.sub(r"\s+", "_", name)
    return name or "file"


def _count_pdf_pages(path: str):
    try:
        if _pypdf is not None:
            reader = _pypdf.PdfReader(path)
            return len(reader.pages)
    except Exception:
        pass
    try:
        if _pypdf2 is not None:
            reader = _pypdf2.PdfReader(path)
            return len(reader.pages)
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            data = f.read()
        return len(re.findall(br"/Type\s*/Page\b", data)) or None
    except Exception:
        return None


# --- Upload form ---
with st.form("upload_form", clear_on_submit=False):
    uploaded_file = st.file_uploader(
        "Выберите документ",
        type=["pdf", "jpg", "png", "jpeg"],
        accept_multiple_files=False,
        help="Поддержка: PDF, JPEG",
    )
    submitted = st.form_submit_button("Загрузить и распознать", type="primary")

if submitted:
    if not uploaded_file:
        st.warning("Пожалуйста, прикрепите файл")
    elif reason == "Выберите причину":
        st.warning("Пожалуйста, выберите причину отсрочки")
    elif doc_type == "Выберите тип документа":
        st.warning("Пожалуйста, выберите тип документа")
    else:
        # Save uploaded file to a temporary location (auto-cleaned) and call orchestrator once
        with tempfile.TemporaryDirectory(prefix="upload_") as tmp_dir:
            tmp_path = Path(tmp_dir) / _safe_filename(uploaded_file.name)
            with open(tmp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            with st.spinner("Обрабатываем документ..."):
                result = run_pipeline(
                    fio=fio or None,
                    reason=reason,
                    doc_type=doc_type,
                    source_file_path=str(tmp_path),
                    original_filename=uploaded_file.name,
                    content_type=getattr(uploaded_file, "type", None),
                    runs_root=RUNS_DIR,
                )

        st.subheader("Результат проверки")
        verdict = bool(result.get("verdict", False))
        errors = result.get("errors", []) or []

        if verdict:
            st.success("Вердикт: True — документ прошел проверку")
        else:
            st.error("Вердикт: False — документ не прошел проверку")

        if errors:
            st.markdown("**Ошибки**")
            for e in errors:
                code = e.get("code")
                msg = message_for(code) or e.get("message") or str(code)
                st.write(f"- {msg}")

        # Diagnostics: show final_result.json for full context
        final_result_path = result.get("final_result_path")
        if isinstance(final_result_path, str) and os.path.exists(final_result_path):
            try:
                with open(final_result_path, "r", encoding="utf-8") as ff:
                    final_obj = json.load(ff)
                with st.expander("Диагностика: final_result.json"):
                    st.json(final_obj)
            except Exception:
                pass

        # Side-by-side comparison (if available)
        if isinstance(final_result_path, str):
            sbs_path = os.path.join(os.path.dirname(final_result_path), "side_by_side.json")
            if os.path.exists(sbs_path):
                try:
                    with open(sbs_path, "r", encoding="utf-8") as sbf:
                        side_by_side = json.load(sbf)
                    with st.expander("Сравнение: side_by_side.json"):
                        # Compact table for quick review
                        rows = []
                        try:
                            rows = [
                                {"Поле": "ФИО (заявка)", "Значение": str(side_by_side.get("fio", {}).get("meta"))},
                                {"Поле": "ФИО (из документа)", "Значение": str(side_by_side.get("fio", {}).get("extracted"))},
                                {"Поле": "Тип документа (заявка)", "Значение": str(side_by_side.get("doc_type", {}).get("meta"))},
                                {"Поле": "Тип документа (из документа)", "Значение": str(side_by_side.get("doc_type", {}).get("extracted"))},
                                {"Поле": "Дата (заявки)", "Значение": str(side_by_side.get("request_created_at"))},
                                {"Поле": "Дата (из документа)", "Значение": str(side_by_side.get("doc_date", {}).get("extracted"))},
                                {"Поле": "Действителен до", "Значение": str(side_by_side.get("doc_date", {}).get("valid_until"))},
                                {"Поле": "Один тип документа", "Значение": str(side_by_side.get("single_doc_type", {}).get("extracted"))},
                                {"Поле": "Печать обнаружена", "Значение": str(side_by_side.get("stamp_present", {}).get("extracted"))},
                            ]
                        except Exception:
                            rows = []
                        if rows:
                            st.table(rows)
                except Exception:
                    pass

        # Preview visualization of stamp detector (if available)
        if isinstance(final_result_path, str):
            try:
                meta_dir = os.path.dirname(final_result_path)
                run_base = os.path.dirname(meta_dir)
                input_original_dir = os.path.join(run_base, "input", "original")
                vis_path = None
                if os.path.isdir(input_original_dir):
                    for name in os.listdir(input_original_dir):
                        lower = name.lower()
                        if lower.endswith("_with_boxes.jpg") or lower.endswith("_with_boxes.jpeg") or lower.endswith("_with_boxes.png"):
                            vis_path = os.path.join(input_original_dir, name)
                            break
                if vis_path and os.path.exists(vis_path):
                    with st.expander("Превью документа с печатью"):
                        st.image(vis_path, use_container_width=True)
            except Exception:
                pass

        # SLA & timings (displayed at the end) from manifest.timing
        if isinstance(final_result_path, str) and os.path.exists(final_result_path):
            try:
                meta_dir = os.path.dirname(final_result_path)
                manifest_path = os.path.join(meta_dir, "manifest.json")
                if os.path.exists(manifest_path):
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        manifest = json.load(mf)
                    timing = manifest.get("timing", {}) if isinstance(manifest, dict) else {}
                    if isinstance(timing, dict):
                        dur = timing.get("duration_seconds")
                        stamp_t = timing.get("stamp_seconds")
                        ocr_t = timing.get("ocr_seconds")
                        gpt_t = timing.get("gpt_seconds")
                        with st.expander("SLA и тайминги выполнения"):
                            # Show four metrics if available
                            cols = st.columns(4)
                            cols[0].metric("Всего (сек)", f"{dur:.2f}" if isinstance(dur, (int, float)) else "-")
                            cols[1].metric("Печать (сек)", f"{stamp_t:.2f}" if isinstance(stamp_t, (int, float)) else "-")
                            cols[2].metric("OCR (сек)", f"{ocr_t:.2f}" if isinstance(ocr_t, (int, float)) else "-")
                            cols[3].metric("GPT (сек)", f"{gpt_t:.2f}" if isinstance(gpt_t, (int, float)) else "-")
            except Exception:
                pass