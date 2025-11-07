import os
import re
import json
import uuid
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import time

from rbidp.clients.tesseract_async_client import ask_tesseract
from rbidp.processors.filter_ocr_response import filter_ocr_response
from rbidp.processors.agent_doc_type_checker import check_single_doc_type
from rbidp.processors.agent_extractor import extract_doc_data
from rbidp.processors.filter_gpt_generic_response import filter_gpt_generic_response
from rbidp.processors.merge_outputs import merge_extractor_and_doc_type
from rbidp.processors.validator import validate_run
from rbidp.core.errors import make_error
from rbidp.core.config import (
    OCR_PAGES,
    GPT_DOC_TYPE_RAW,
    GPT_DOC_TYPE_FILTERED,
    GPT_EXTRACTOR_RAW,
    GPT_EXTRACTOR_FILTERED,
    MERGED_FILENAME,
    VALIDATION_FILENAME,
    METADATA_FILENAME,
    MAX_PDF_PAGES,
    UTC_OFFSET_HOURS,
)
from rbidp.core.validity import compute_valid_until, format_date
from rbidp.processors.stamp_check import stamp_present_for_source


logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-\.\s]", "_", (name or "").strip())
    name = re.sub(r"\s+", "_", name)
    return name or "file"


def _count_pdf_pages(path: str) -> Optional[int]:
    try:
        import pypdf as _pypdf  # type: ignore
        try:
            reader = _pypdf.PdfReader(path)
            return len(reader.pages)
        except Exception as e:
            logger.debug("pypdf reader failed: %s", e, exc_info=True)
    except Exception:
        pass
    try:
        import PyPDF2 as _pypdf2  # type: ignore
        try:
            reader = _pypdf2.PdfReader(path)
            return len(reader.pages)
        except Exception:
            pass
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            data = f.read()
        import re as _re
        return len(_re.findall(br"/Type\s*/Page\b", data)) or None
    except Exception:
        return None


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _write_manifest(
    meta_dir: Path,
    *,
    run_id: str,
    user_input: Dict[str, Any],
    file_info: Dict[str, Any],
    artifacts: Dict[str, Any],
    status: str,
    error: Optional[str],
    created_at: str,
) -> None:
    final_result_path = artifacts.get("final_result_path") or str(meta_dir / "final_result.json")
    side_by_side_path = str(meta_dir / "side_by_side.json") if (meta_dir / "side_by_side.json").exists() else None
    merged_path = artifacts.get("gpt_merged_path")
    # Timing (authoritative from artifacts only)
    duration_seconds = None
    if isinstance(artifacts, dict) and isinstance(artifacts.get("duration_seconds"), (int, float)):
        try:
            duration_seconds = float(artifacts.get("duration_seconds"))
        except Exception:
            duration_seconds = None
    stamp_seconds = artifacts.get("stamp_seconds") if isinstance(artifacts, dict) else None
    ocr_seconds = artifacts.get("ocr_seconds") if isinstance(artifacts, dict) else None
    gpt_seconds = artifacts.get("gpt_seconds") if isinstance(artifacts, dict) else None

    manifest = {
        "run_id": run_id,
        "created_at": created_at,
        "timing": {
            "duration_seconds": duration_seconds,
            "stamp_seconds": stamp_seconds,
            "ocr_seconds": ocr_seconds,
            "gpt_seconds": gpt_seconds,
        },
        "user_input": user_input,
        "file": file_info,
        "artifacts": {
            "final_result_path": final_result_path,
            "side_by_side_path": side_by_side_path,
            "merged_path": merged_path,
        },
        "status": status,
        "error": error,
    }
    _write_json(meta_dir / "manifest.json", manifest)


def _now_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:5]
    return f"{ts}_{short_id}"


def _mk_run_dirs(runs_root: Path, run_id: str) -> Dict[str, Path]:
    date_str = datetime.now().strftime("%Y-%m-%d")
    base_dir = runs_root / date_str / run_id
    input_dir = base_dir / "input" / "original"
    ocr_dir = base_dir / "ocr"
    gpt_dir = base_dir / "gpt"
    meta_dir = base_dir / "meta"
    for d in (input_dir, ocr_dir, gpt_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)
    return {
        "base": base_dir,
        "input": input_dir,
        "ocr": ocr_dir,
        "gpt": gpt_dir,
        "meta": meta_dir,
    }


def _build_final(
    run_id: str,
    errors: List[Dict[str, Any]],
    verdict: bool,
    checks: Optional[Dict[str, Any]],
    artifacts: Dict[str, str],
    final_path: Path,
) -> Dict[str, Any]:
    # Persist a minimal final_result.json (no checks/artifacts) with only error codes
    file_errors = []
    for e in errors:
        if isinstance(e, dict) and "code" in e:
            file_errors.append({"code": e.get("code")})
        else:
            # fallback if non-dict error
            file_errors.append({"code": str(e)})
    file_result = {
        "run_id": run_id,
        "verdict": bool(verdict),
        "errors": file_errors,
    }
    # Try to include stamp_present if written to metadata.json earlier
    try:
        meta_dir = final_path.parent
        meta_path = meta_dir / METADATA_FILENAME
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as mf:
                mo = json.load(mf)
            if isinstance(mo, dict) and "stamp_present" in mo:
                file_result["stamp_present"] = bool(mo.get("stamp_present"))
    except Exception:
        pass
    _write_json(final_path, file_result)
    # Return a minimal in-memory result as well, with a pointer to the file
    return {
        "run_id": run_id,
        "verdict": bool(verdict),
        "errors": errors,
        "final_result_path": str(final_path),
    }


def run_pipeline(
    fio: Optional[str],
    reason: Optional[str],
    doc_type: str,
    source_file_path: str,
    original_filename: str,
    content_type: Optional[str],
    runs_root: Path,
) -> Dict[str, Any]:
    run_id = _now_id()
    t0 = time.perf_counter()
    t_stamp = 0.0
    t_ocr = 0.0
    t_gpt = 0.0
    request_created_at = datetime.now(timezone(timedelta(hours=UTC_OFFSET_HOURS))).strftime("%d.%m.%Y")
    dirs = _mk_run_dirs(runs_root, run_id)
    base_dir, input_dir, ocr_dir, gpt_dir, meta_dir = (
        dirs["base"], dirs["input"], dirs["ocr"], dirs["gpt"], dirs["meta"]
    )

    errors: List[Dict[str, Any]] = []
    artifacts: Dict[str, str] = {}

    base_name = _safe_filename(original_filename or os.path.basename(source_file_path))
    saved_path = input_dir / base_name
    try:
        shutil.copyfile(source_file_path, saved_path)
    except Exception as e:
        errors.append(make_error("FILE_SAVE_FAILED", details=str(e)))
        final_path = meta_dir / "final_result.json"
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": None,
            },
            artifacts=artifacts,
            status="error",
            error="FILE_SAVE_FAILED",
            created_at=request_created_at,
        )
        return result

    size_bytes = None
    try:
        size_bytes = saved_path.stat().st_size
    except Exception:
        pass

    metadata = {"fio": fio or None, "reason": reason, "doc_type": doc_type}
    _write_json(meta_dir / METADATA_FILENAME, metadata)

    if saved_path.suffix.lower() == ".pdf":
        pages = _count_pdf_pages(str(saved_path))
        if pages is not None and pages > MAX_PDF_PAGES:
            errors.append(make_error("PDF_TOO_MANY_PAGES"))
            final_path = meta_dir / "final_result.json"
            artifacts["duration_seconds"] = time.perf_counter() - t0
            artifacts["stamp_seconds"] = t_stamp
            artifacts["ocr_seconds"] = t_ocr
            artifacts["gpt_seconds"] = t_gpt
            result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
            artifacts["final_result_path"] = str(final_path)
            _write_manifest(
                meta_dir,
                run_id=run_id,
                user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
                file_info={
                    "original_filename": original_filename,
                    "saved_path": str(saved_path),
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
                artifacts=artifacts,
                status="error",
                error="PDF_TOO_MANY_PAGES",
                created_at=request_created_at,
            )
            return result

    # OCR
    _t_ocr_start = time.perf_counter()
    textract_result = ask_tesseract(str(saved_path), output_dir=str(ocr_dir), save_json=False)
    if not textract_result.get("success"):
        errors.append(make_error("OCR_FAILED", details=str(textract_result.get("error"))) )
        final_path = meta_dir / "final_result.json"
        t_ocr += (time.perf_counter() - _t_ocr_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="error",
            error="OCR_FAILED",
            created_at=request_created_at,
        )
        return result

    # Filter OCR pages
    try:
        filtered_pages_path = filter_ocr_response(textract_result.get("raw_obj", {}), str(ocr_dir), filename=OCR_PAGES)
        artifacts["ocr_pages_filtered_path"] = str(filtered_pages_path)
        with open(filtered_pages_path, "r", encoding="utf-8") as f:
            pages_obj = json.load(f)
        if not isinstance(pages_obj, dict) or not isinstance(pages_obj.get("pages"), list):
            raise ValueError("Invalid pages object")
        if len(pages_obj["pages"]) == 0:
            errors.append(make_error("OCR_EMPTY_PAGES"))
            final_path = meta_dir / "final_result.json"
            t_ocr += (time.perf_counter() - _t_ocr_start)
            artifacts["duration_seconds"] = time.perf_counter() - t0
            artifacts["stamp_seconds"] = t_stamp
            artifacts["ocr_seconds"] = t_ocr
            artifacts["gpt_seconds"] = t_gpt
            result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
            artifacts["final_result_path"] = str(final_path)
            _write_manifest(
                meta_dir,
                run_id=run_id,
                user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
                file_info={
                    "original_filename": original_filename,
                    "saved_path": str(saved_path),
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
                artifacts=artifacts,
                status="error",
                error="OCR_EMPTY_PAGES",
                created_at=request_created_at,
            )
            return result
    except Exception as e:
        errors.append(make_error("OCR_FILTER_FAILED", details=str(e)))
        final_path = meta_dir / "final_result.json"
        t_ocr += (time.perf_counter() - _t_ocr_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="error",
            error="OCR_FILTER_FAILED",
            created_at=request_created_at,
        )
        return result

    # Successfully finished OCR stage; record OCR duration
    t_ocr += (time.perf_counter() - _t_ocr_start)

    # Doc type checker (GPT)
    _t_gpt_start = time.perf_counter()
    try:
        dtc_raw_str = check_single_doc_type(pages_obj)
        dtc_raw_path = gpt_dir / GPT_DOC_TYPE_RAW
        with open(dtc_raw_path, "w", encoding="utf-8") as f:
            f.write(dtc_raw_str or "")
        dtc_filtered_path = filter_gpt_generic_response(str(dtc_raw_path), str(gpt_dir), filename=GPT_DOC_TYPE_FILTERED)
        artifacts["gpt_doc_type_check_filtered_path"] = str(dtc_filtered_path)
        with open(dtc_filtered_path, "r", encoding="utf-8") as f:
            dtc_obj = json.load(f)
        is_single = dtc_obj.get("single_doc_type") if isinstance(dtc_obj, dict) else None
        if not isinstance(is_single, bool):
            errors.append(make_error("DTC_PARSE_ERROR"))
            final_path = meta_dir / "final_result.json"
            # ensure timing is recorded for early return
            t_gpt += (time.perf_counter() - _t_gpt_start)
            artifacts["duration_seconds"] = time.perf_counter() - t0
            artifacts["stamp_seconds"] = t_stamp
            artifacts["ocr_seconds"] = t_ocr
            artifacts["gpt_seconds"] = t_gpt
            result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
            artifacts["final_result_path"] = str(final_path)
            _write_manifest(
                meta_dir,
                run_id=run_id,
                user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
                file_info={
                    "original_filename": original_filename,
                    "saved_path": str(saved_path),
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
                artifacts=artifacts,
                status="error",
                error="DTC_PARSE_ERROR",
                created_at=request_created_at,
            )
            return result
        if is_single is False:
            errors.append(make_error("MULTIPLE_DOCUMENTS"))
            final_path = meta_dir / "final_result.json"
            # ensure timing is recorded for early return
            t_gpt += (time.perf_counter() - _t_gpt_start)
            artifacts["duration_seconds"] = time.perf_counter() - t0
            artifacts["stamp_seconds"] = t_stamp
            artifacts["ocr_seconds"] = t_ocr
            artifacts["gpt_seconds"] = t_gpt
            result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
            artifacts["final_result_path"] = str(final_path)
            _write_manifest(
                meta_dir,
                run_id=run_id,
                user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
                file_info={
                    "original_filename": original_filename,
                    "saved_path": str(saved_path),
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
                artifacts=artifacts,
                status="error",
                error="MULTIPLE_DOCUMENTS",
                created_at=request_created_at,
            )
            return result
    except Exception as e:
        errors.append(make_error("DTC_FAILED", details=str(e)))
        final_path = meta_dir / "final_result.json"
        t_gpt += (time.perf_counter() - _t_gpt_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="error",
            error="DTC_FAILED",
            created_at=request_created_at,
        )
        return result

    # Extraction (GPT)
    try:
        gpt_raw = extract_doc_data(pages_obj)
        gpt_raw_path = gpt_dir / GPT_EXTRACTOR_RAW
        with open(gpt_raw_path, "w", encoding="utf-8") as f:
            f.write(gpt_raw or "")
        filtered_path = filter_gpt_generic_response(str(gpt_raw_path), str(gpt_dir), filename=GPT_EXTRACTOR_FILTERED)
        try:
            os.remove(gpt_raw_path)
        except Exception as e:
            logger.debug("Failed to remove gpt_raw_path: %s", e, exc_info=True)
        artifacts["gpt_extractor_filtered_path"] = str(filtered_path)
        with open(filtered_path, "r", encoding="utf-8") as f:
            filtered_obj = json.load(f)
        # schema check
        if not isinstance(filtered_obj, dict):
            raise ValueError("Extractor filtered object is not a dict")
        for k in ("fio", "doc_type", "doc_date"):
            if k not in filtered_obj:
                raise ValueError("Missing key: " + k)
            v = filtered_obj[k]
            if v is not None and not isinstance(v, str):
                raise ValueError(f"Key {k} has invalid type")
        # optional field valid_until
        if "valid_until" in filtered_obj:
            vu = filtered_obj.get("valid_until")
            if vu is not None and not isinstance(vu, str):
                raise ValueError("Key valid_until has invalid type")

        # Stamp presence (non-fatal) deferred until after successful single-doc and extraction
        stamp_flag = None
        try:
            suffix = saved_path.suffix.lower()
            if suffix in {".jpg", ".jpeg", ".png", ".pdf"}:
                t_s = time.perf_counter()
                # save detector visualization into the run's input/original folder
                stamp_flag = stamp_present_for_source(str(saved_path), vis_dest_dir=str(input_dir))
                t_stamp += (time.perf_counter() - t_s)
        except Exception:
            stamp_flag = None
        # Persist detector response into a dedicated file to separate inputs vs outputs
        if stamp_flag is not None:
            scr_path = meta_dir / "stamp_check_response.json"
            _write_json(scr_path, {"stamp_present": bool(stamp_flag)})
            artifacts["stamp_check_response_path"] = str(scr_path)

        # Close out GPT timing for doc-type + extraction segment so it excludes stamp time
        t_gpt += (time.perf_counter() - _t_gpt_start)
        _t_gpt_start = time.perf_counter()
    except ValueError as ve:
        errors.append(make_error("EXTRACT_SCHEMA_INVALID", details=str(ve)))
        final_path = meta_dir / "final_result.json"
        # ensure timing is recorded for early return
        t_gpt += (time.perf_counter() - _t_gpt_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="error",
            error="EXTRACT_SCHEMA_INVALID",
            created_at=request_created_at,
        )
        return result
    except Exception as e:
        errors.append(make_error("EXTRACT_FAILED", details=str(e)))
        final_path = meta_dir / "final_result.json"
        # ensure timing is recorded for early return
        t_gpt += (time.perf_counter() - _t_gpt_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="error",
            error="EXTRACT_FAILED",
            created_at=request_created_at,
        )
        return result

    # Merge
    try:
        merged_path = merge_extractor_and_doc_type(
            extractor_filtered_path=artifacts.get("gpt_extractor_filtered_path", ""),
            doc_type_filtered_path=artifacts.get("gpt_doc_type_check_filtered_path", ""),
            output_dir=str(gpt_dir),
            filename=MERGED_FILENAME,
            stamp_check_response_path=artifacts.get("stamp_check_response_path", ""),
        )
        artifacts["gpt_merged_path"] = str(merged_path)
        # Build side-by-side comparison file in meta
        try:
            # Load meta and merged raw values
            with open(meta_dir / METADATA_FILENAME, "r", encoding="utf-8") as mf:
                meta_obj = json.load(mf)
            with open(merged_path, "r", encoding="utf-8") as mg:
                merged_obj = json.load(mg)

            fio_meta_raw = meta_obj.get("fio") if isinstance(meta_obj, dict) else None
            fio_extracted_raw = merged_obj.get("fio") if isinstance(merged_obj, dict) else None

            doc_type_meta_raw = meta_obj.get("doc_type") if isinstance(meta_obj, dict) else None
            doc_type_extracted_raw = merged_obj.get("doc_type") if isinstance(merged_obj, dict) else None

            doc_date_extracted = merged_obj.get("doc_date") if isinstance(merged_obj, dict) else None
            valid_until_extracted_raw = merged_obj.get("valid_until") if isinstance(merged_obj, dict) else None
            # compute policy-based valid_until and format
            vu_dt, _, _, _ = compute_valid_until(
                doc_type_extracted_raw, doc_date_extracted, valid_until_extracted_raw
            )
            valid_until_str = format_date(vu_dt)

            single_doc_type_raw = merged_obj.get("single_doc_type") if isinstance(merged_obj, dict) else None

            side_by_side = {
                "request_created_at": request_created_at,
                "fio": {
                    "meta": fio_meta_raw,
                    "extracted": fio_extracted_raw,
                },
                "doc_type": {
                    "meta": doc_type_meta_raw,
                    "extracted": doc_type_extracted_raw,
                },
                "doc_date": {
                    "extracted": doc_date_extracted,
                    "valid_until": valid_until_str,
                },
                "single_doc_type": {
                    "extracted": single_doc_type_raw,
                },
            }
            # append stamp_present from dedicated response file if available
            try:
                scr_path = meta_dir / "stamp_check_response.json"
                sp_val = None
                if scr_path.exists():
                    with open(scr_path, "r", encoding="utf-8") as sf:
                        scr = json.load(sf)
                    if isinstance(scr, dict) and "stamp_present" in scr:
                        sp_val = bool(scr.get("stamp_present"))
                side_by_side["stamp_present"] = {"extracted": (sp_val if sp_val is not None else None)}
            except Exception:
                pass
            _write_json(meta_dir / "side_by_side.json", side_by_side)
        except Exception:
            pass
    except Exception as e:
        errors.append(make_error("MERGE_FAILED", details=str(e)))
        final_path = meta_dir / "final_result.json"
        t_gpt += (time.perf_counter() - _t_gpt_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="error",
            error="MERGE_FAILED",
            created_at=request_created_at,
        )
        return result

    # Validation
    try:
        validation = validate_run(
            meta_path=str(meta_dir / METADATA_FILENAME),
            merged_path=str(artifacts.get("gpt_merged_path", "")),
            output_dir=str(gpt_dir),
            filename=VALIDATION_FILENAME,
            write_file=False,
        )
        # validation file is suppressed; no artifacts path
        if not validation.get("success"):
            errors.append(make_error("VALIDATION_FAILED", details=str(validation.get("error"))))
            final_path = meta_dir / "final_result.json"
            # ensure timing is recorded for early return
            t_gpt += (time.perf_counter() - _t_gpt_start)
            artifacts["duration_seconds"] = time.perf_counter() - t0
            artifacts["stamp_seconds"] = t_stamp
            artifacts["ocr_seconds"] = t_ocr
            artifacts["gpt_seconds"] = t_gpt
            result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
            _write_manifest(
                meta_dir,
                run_id=run_id,
                user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
                file_info={
                    "original_filename": original_filename,
                    "saved_path": str(saved_path),
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                },
                artifacts=artifacts,
                status="error",
                error="VALIDATION_FAILED",
                created_at=request_created_at,
            )
            return result

        val_result = validation.get("result", {})
        checks = val_result.get("checks") if isinstance(val_result, dict) else None
        verdict = bool(val_result.get("verdict")) if isinstance(val_result, dict) else False
        check_errors: List[Dict[str, Any]] = []
        if isinstance(checks, dict):
            fm = checks.get("fio_match")
            if fm is False:
                check_errors.append(make_error("FIO_MISMATCH"))
            elif fm is None:
                check_errors.append(make_error("FIO_MISSING"))

            dtm = checks.get("doc_type_match")
            if dtm is False:
                check_errors.append(make_error("DOC_TYPE_MISMATCH"))
            elif dtm is None:
                check_errors.append(make_error("DOC_TYPE_MISSING"))

            dv = checks.get("doc_date_valid")
            if dv is False:
                check_errors.append(make_error("DOC_DATE_TOO_OLD"))
            elif dv is None:
                check_errors.append(make_error("DOC_DATE_MISSING"))
            if checks.get("single_doc_type_valid") is False:
                check_errors.append(make_error("SINGLE_DOC_TYPE_INVALID"))
            # stamp_present mirrors single_doc_type flow
            sp = checks.get("stamp_present")
            if sp is False:
                check_errors.append(make_error("STAMP_NOT_PRESENT"))
            elif sp is None:
                check_errors.append(make_error("STAMP_CHECK_MISSING"))
        errors.extend(check_errors)

        final_path = meta_dir / "final_result.json"
        t_gpt += (time.perf_counter() - _t_gpt_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=verdict, checks=checks, artifacts=artifacts, final_path=final_path)
        artifacts["final_result_path"] = str(final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts=artifacts,
            status="success",
            error=None,
            created_at=request_created_at,
        )
        return result
    except Exception as e:
        errors.append(make_error("VALIDATION_FAILED", details=str(e)))
        final_path = meta_dir / "final_result.json"
        t_gpt += (time.perf_counter() - _t_gpt_start)
        artifacts["duration_seconds"] = time.perf_counter() - t0
        artifacts["stamp_seconds"] = t_stamp
        artifacts["ocr_seconds"] = t_ocr
        artifacts["gpt_seconds"] = t_gpt
        result = _build_final(run_id, errors, verdict=False, checks=None, artifacts=artifacts, final_path=final_path)
        _write_manifest(
            meta_dir,
            run_id=run_id,
            user_input={"fio": fio or None, "reason": reason, "doc_type": doc_type},
            file_info={
                "original_filename": original_filename,
                "saved_path": str(saved_path),
                "content_type": content_type,
                "size_bytes": size_bytes,
            },
            artifacts={
                "final_result_path": str(final_path),
                "gpt_merged_path": artifacts.get("gpt_merged_path", ""),
            },
            status="error",
            error="VALIDATION_FAILED",
            created_at=request_created_at,
        )
        return result