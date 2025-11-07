from rbidp.core.config import TEXTRACT_PAGES

def filter_textract_response(obj: dict, output_dir: str, filename: str = TEXTRACT_PAGES) -> str:
    """
    Build per-page text and save to JSON file {"pages": [{"page_number", "text"}, ...]}.
    Returns the full path to the saved file.
    """
    import os, json
    os.makedirs(output_dir, exist_ok=True)

    pages = []
    # Prefer {data: {pages: [...]}} if present
    data = obj.get("data", {}) if isinstance(obj, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("pages"), list):
        for p in data["pages"]:
            if isinstance(p, dict):
                pn = p.get("page_number")
                try:
                    pn = int(pn) if pn is not None else None
                except Exception:
                    pn = None
                pages.append({
                    "page_number": pn,
                    "text": p.get("text", "") or "",
                })
        if all(isinstance(x.get("page_number"), int) for x in pages):
            pages.sort(key=lambda x: x["page_number"]) 
    # Else, derive from Textract Blocks
    elif isinstance(obj.get("Blocks"), list):
        from collections import defaultdict
        blocks = obj["Blocks"]
        pages_map = defaultdict(list)
        has_line = any(isinstance(b, dict) and b.get("BlockType") == "LINE" for b in blocks)
        if has_line:
            for b in blocks:
                if isinstance(b, dict) and b.get("BlockType") == "LINE":
                    page_no = b.get("Page")
                    txt = b.get("Text", "")
                    if txt:
                        pages_map[page_no].append(txt)
        else:
            for b in blocks:
                if isinstance(b, dict) and b.get("Text"):
                    pages_map[b.get("Page")].append(b.get("Text"))
        for pn in sorted((k for k in pages_map.keys() if isinstance(k, int))):
            pages.append({
                "page_number": pn,
                "text": "\n".join(pages_map[pn]).strip(),
            })
        if None in pages_map:
            pages.append({
                "page_number": None,
                "text": "\n".join(pages_map[None]).strip(),
            })
    else:
        # Fallback: nothing recognizable
        pages = [{"page_number": None, "text": ""}]

    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f, ensure_ascii=False, indent=2)
    return out_path