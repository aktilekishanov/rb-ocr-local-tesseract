import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# Adjust these absolute paths for the server if needed
DETECTOR_PY = "/home/rb_admin2/main/stamp-processing/.venv/bin/python"
DETECTOR_SCRIPT = "/home/rb_admin2/main/stamp-processing/main.py"
DETECTOR_WEIGHT = "/home/rb_admin2/main/stamp-processing/weights/stamp_detector.pt"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _is_image_path(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_SUFFIXES


def _render_pdf_to_vertical_jpg(pdf_path: str) -> Optional[str]:
    """Render all pages of a PDF to a single tall JPEG (pages glued vertically).
    Returns path to temp JPG or None if rendering unavailable/fails.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None
    try:
        from PIL import Image
    except Exception:
        return None

    tmpdir = tempfile.mkdtemp(prefix="pdf2jpg_")
    out_path = os.path.join(tmpdir, "pages_glued.jpg")
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count < 1:
            return None
        mat = fitz.Matrix(200 / 72.0, 200 / 72.0)  # ~200 DPI

        pil_pages = []
        for i in range(doc.page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            # Convert pixmap to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pil_pages.append(img)

        if not pil_pages:
            return None

        widths = [im.width for im in pil_pages]
        heights = [im.height for im in pil_pages]
        max_w = max(widths)
        total_h = sum(heights)

        canvas = Image.new("RGB", (max_w, total_h), (255, 255, 255))
        y = 0
        for im in pil_pages:
            # If page width < max_w, paste centered on white background
            if im.width != max_w:
                bg = Image.new("RGB", (max_w, im.height), (255, 255, 255))
                bg.paste(im, ((max_w - im.width) // 2, 0))
                im = bg
            canvas.paste(im, (0, y))
            y += im.height

        # Save as JPEG with moderate quality
        canvas.save(out_path, format="JPEG", quality=85)
        return out_path
    except Exception:
        return None


def _run_detector(image_path: str, vis_dest_dir: Optional[str] = None, vis_basename: Optional[str] = None) -> Optional[bool]:
    """Run the external detector script and return True/False. None on error."""
    out_dir = tempfile.mkdtemp(prefix="stampdet_")
    try:
        cmd = [
            DETECTOR_PY,
            DETECTOR_SCRIPT,
            "--image",
            image_path,
            "--out-dir",
            out_dir,
            "--detector-weight",
            DETECTOR_WEIGHT,
        ]
        # Let detector output print to console for debugging visibility
        subprocess.run(cmd, check=True)
        result_path = os.path.join(out_dir, "result.json")
        if not os.path.exists(result_path):
            return None
        with open(result_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Copy visualization image to destination if requested
        if vis_dest_dir:
            try:
                # Detector saves vis using the temp image stem/suffix
                det_stem = Path(image_path).stem
                det_suffix = Path(image_path).suffix
                det_name = f"{det_stem}_with_boxes{det_suffix}"
                det_src = os.path.join(out_dir, det_name)

                # Destination filename should reflect the original file stem if provided
                dst_stem = vis_basename if vis_basename else det_stem
                dst_name = f"{dst_stem}_with_boxes{det_suffix}"
                os.makedirs(vis_dest_dir, exist_ok=True)
                vis_dst = os.path.join(vis_dest_dir, dst_name)

                copied = False
                if os.path.exists(det_src):
                    shutil.copyfile(det_src, vis_dst)
                    copied = True
                else:
                    # Fallback: find any *_with_boxes.* in out_dir and copy the first
                    for fname in os.listdir(out_dir):
                        if fname.startswith(det_stem + "_with_boxes") or fname.endswith("_with_boxes" + det_suffix):
                            try:
                                shutil.copyfile(os.path.join(out_dir, fname), vis_dst)
                                copied = True
                                break
                            except Exception:
                                pass
                # Optional debug print
                print(f"[stamp_check] vis copy {'OK' if copied else 'MISS'}: src_dir={out_dir} -> {vis_dst}")
            except Exception:
                pass
        return bool(data.get("stamp_present", False))
    except Exception:
        return None
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def stamp_present_for_source(source_path: str, vis_dest_dir: Optional[str] = None) -> Optional[bool]:
    """Compute stamp presence for an input file.
    - If image: run detector directly.
    - If PDF: try to render first page to JPG via PyMuPDF; run detector; cleanup.
    - Returns True/False or None if cannot compute.
    """
    p = Path(source_path)
    if _is_image_path(p):
        return _run_detector(str(p), vis_dest_dir=vis_dest_dir, vis_basename=p.stem)
    if p.suffix.lower() == ".pdf":
        temp_jpg = _render_pdf_to_vertical_jpg(str(p))
        if not temp_jpg:
            return None
        try:
            # For PDFs, ensure the visualization name matches original file stem
            return _run_detector(temp_jpg, vis_dest_dir=vis_dest_dir, vis_basename=p.stem)
        finally:
            # cleanup jpg parent tmpdir
            try:
                shutil.rmtree(os.path.dirname(temp_jpg), ignore_errors=True)
            except Exception:
                pass
    return None
