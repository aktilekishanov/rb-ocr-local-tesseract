import json
import os
from typing import Dict, Any
import re
from rapidfuzz import fuzz  
from rbidp.core.config import VALIDATION_FILENAME
from rbidp.core.dates import now_utc_plus
from rbidp.core.validity import compute_valid_until, is_within_validity, format_date

VALIDATION_MESSAGES = {
    "checks": {
        "fio_match": {
            True: "Относится к заявителю",
            False: "Не относится к заявителю",
        },
        "doc_type_match": {
            True: "Верный формат документа",
            False: "Неверный формат документа",
        },
        "doc_date_valid": {
            True: "Актуальная дата документа",
            False: "Устаревшая дата документа",
        },
        "single_doc_type_valid": {
            True: "Файл содержит один тип документа",
            False: "Файл содержит несколько типов документов",
        },
        "stamp_present": {
            True: "Печать обнаружена",
            False: "Печать не обнаружена",
        },
    },
    "verdict": {
        True: "Отсрочка активирована: прикрепленный документ успешно прошел проверку",
        False: "К сожалению, Вам отказано в отсрочке: прикрепленный документ не прошел проверку",
    },
}


def _norm_text(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    # collapse whitespace and lowercase
    s = re.sub(r"\s+", " ", s.strip())
    return s.casefold()


def _now_utc_plus_5():
    return now_utc_plus(5)

def kz_to_ru(s: str) -> str:
    table = str.maketrans({
        "қ": "к",
        "ұ": "у",
        "ү": "у", 
        "ң": "н",
        "ғ": "г",
        "ө": "о",
        "Қ": "К",
        "Ұ": "У",
        "Ү": "У",
        "Ң": "Н",
        "Ғ": "Г",
        "Ө": "О",
    })
    return s.translate(table)

def latin_to_cyrillic(s: str) -> str:
    table = str.maketrans({
        "a": "а",
        "e": "е",
        "o": "о",
        "p": "р",
        "c": "с",
        "y": "у",
        "x": "х",
        "k": "к",
        "h": "н",
        "b": "в",
        "m": "м",
        "t": "т",
        "i": "и",
        "A": "А",
        "E": "Е",
        "O": "О",
        "P": "Р",
        "C": "С",
        "Y": "У",
        "X": "Х",
        "K": "К",
        "H": "Н",
        "B": "В",
        "M": "М",
        "T": "Т",
        "I": "И",
    })
    return s.translate(table)

def validate_run(meta_path: str, merged_path: str, output_dir: str, filename: str = VALIDATION_FILENAME, write_file: bool = True) -> Dict[str, Any]:
    try:
        with open(meta_path, "r", encoding="utf-8") as mf:
            meta = json.load(mf)
        with open(merged_path, "r", encoding="utf-8") as gf:
            merged = json.load(gf)
    except Exception as e:
        return {"success": False, "error": f"IO error: {e}", "validation_path": "", "result": None}


    fio_meta_raw = meta.get("fio") if isinstance(meta, dict) else None
    doc_type_meta_raw = meta.get("doc_type") if isinstance(meta, dict) else None

    fio_meta = _norm_text(fio_meta_raw)
    doc_type_meta = _norm_text(doc_type_meta_raw)

    fio_meta_ru = kz_to_ru(fio_meta)
    fio_meta_norm = latin_to_cyrillic(fio_meta_ru)

    fio_raw = merged.get("fio") if isinstance(merged, dict) else None
    fio = _norm_text(fio_raw)
    fio_ru = kz_to_ru(fio)
    fio_norm = latin_to_cyrillic(fio_ru)
    doc_class_raw = merged.get("doc_type") if isinstance(merged, dict) else None
    doc_class = _norm_text(doc_class_raw)
    doc_date_raw = merged.get("doc_date") if isinstance(merged, dict) else None
    valid_until_raw = merged.get("valid_until") if isinstance(merged, dict) else None
    single_doc_type_raw = merged.get("single_doc_type") if isinstance(merged, dict) else None
    stamp_present_raw = merged.get("stamp_present") if isinstance(merged, dict) else None

    score_before = None
    score_after = None
    try:
        if fio_meta and fio:
            score_before = fuzz.token_sort_ratio(fio_meta, fio)
        if fio_meta_norm and fio_norm:
            score_after = fuzz.token_sort_ratio(fio_meta_norm, fio_norm)
    except Exception:
        pass

    if fio_meta_norm and fio_norm:
        try:
            score = fuzz.token_sort_ratio(fio_meta_norm, fio_norm)
            fio_match = score >= 90
        except Exception:
            fio_match = fio_meta_norm == fio_norm
    else:
        fio_match = None
    if doc_type_meta and doc_class:
        doc_type_match = doc_type_meta == doc_class
    else:
        doc_type_match = None

    now = _now_utc_plus_5()
    valid_until_dt, policy_type, policy_days, policy_error = compute_valid_until(
        doc_class_raw, doc_date_raw, valid_until_raw
    )
    doc_date_valid = is_within_validity(valid_until_dt, now)

    if isinstance(single_doc_type_raw, bool):
        single_doc_type_valid = single_doc_type_raw
    else:
        single_doc_type_valid = None

    # stamp_present comes from detector; treat as tri-state
    if isinstance(stamp_present_raw, bool):
        stamp_present = stamp_present_raw
    else:
        stamp_present = None

    checks = {
        "fio_match": fio_match,
        "doc_type_match": doc_type_match,
        "doc_date_valid": doc_date_valid,
        "single_doc_type_valid": single_doc_type_valid,
        "stamp_present": stamp_present,
    }

    verdict = (
        checks.get("fio_match") is True
        and checks.get("doc_type_match") is True
        and checks.get("doc_date_valid") is True
        and checks.get("single_doc_type_valid") is True
        and checks.get("stamp_present") is True
    )

    diagnostics = {
        "inputs": {
            "fio_meta": fio_meta_raw,
            "fio": fio_raw,
            "doc_type_meta": doc_type_meta_raw,
            "doc_type": doc_class_raw,
            "doc_date": doc_date_raw,
            "valid_until": valid_until_raw,
            "single_doc_type": single_doc_type_raw,
        },
        "normalization": {
            "fio_meta_norm": fio_meta_norm,
            "fio_norm": fio_norm,
            "doc_type_meta_norm": doc_type_meta,
            "doc_type_norm": doc_class,
        },
        "scores": {
            "fio_similarity_before": score_before,
            "fio_similarity_after": score_after,
        },
        "timing": {
            "now_utc_plus_5": now.isoformat(),
            "effective_valid_until": format_date(valid_until_dt),
            "policy_type": policy_type,
            "validity_window_days": policy_days,
            "policy_error": policy_error,
        },
        "checks": checks,
        "messages": {
            key: VALIDATION_MESSAGES["checks"][key].get(val) if val is not None else None
            for key, val in checks.items()
        },
    }

    result = {
        "checks": checks,
        "verdict": verdict,
        "diagnostics": diagnostics,
    }

    if not write_file:
        return {"success": True, "error": None, "validation_path": "", "result": result}
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        return {"success": False, "error": f"Validation error: {e}", "validation_path": "", "result": None}