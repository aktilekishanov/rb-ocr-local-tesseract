import json
import os
from typing import Dict, Any
from rbidp.core.config import MERGED_FILENAME


def merge_extractor_and_doc_type(
    extractor_filtered_path: str,
    doc_type_filtered_path: str,
    output_dir: str,
    filename: str = MERGED_FILENAME,
    stamp_check_response_path: str = "",
) -> str:
    """
    Merge two JSON objects from given file paths and save to output_dir/filename.
    - extractor_filtered_path: file with extractor result (dict)
    - doc_type_filtered_path: file with doc-type check result (dict)
    Returns full path to merged file.
    """
    with open(extractor_filtered_path, "r", encoding="utf-8") as ef:
        extractor_obj: Dict[str, Any] = json.load(ef)
    with open(doc_type_filtered_path, "r", encoding="utf-8") as df:
        doc_type_obj: Dict[str, Any] = json.load(df)

    merged: Dict[str, Any] = {}
    if isinstance(extractor_obj, dict):
        merged.update(extractor_obj)
    if isinstance(doc_type_obj, dict):
        merged.update(doc_type_obj)

    # Optionally merge stamp_check_response (e.g., {"stamp_present": true|false})
    if stamp_check_response_path:
        try:
            with open(stamp_check_response_path, "r", encoding="utf-8") as sf:
                stamp_obj: Dict[str, Any] = json.load(sf)
            if isinstance(stamp_obj, dict):
                merged.update(stamp_obj)
        except Exception:
            pass

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as mf:
        json.dump(merged, mf, ensure_ascii=False, indent=2)
    return out_path
