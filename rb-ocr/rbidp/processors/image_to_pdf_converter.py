import os
import tempfile
from typing import Optional

try:
    from PIL import Image, ImageSequence, ImageOps
except Exception:
    Image = None
    ImageSequence = None
    ImageOps = None


def convert_image_to_pdf(image_path: str, output_dir: Optional[str] = None, output_path: Optional[str] = None, overwrite: bool = False) -> str:
    if Image is None:
        raise RuntimeError("Pillow is required for image to PDF conversion")
    if not os.path.isfile(image_path):
        raise FileNotFoundError(image_path)
    # Determine output path
    if output_path:
        out_dir = os.path.dirname(output_path) or os.path.dirname(image_path)
        os.makedirs(out_dir, exist_ok=True)
        out_pdf = output_path
    else:
        out_dir = output_dir if output_dir else os.path.dirname(image_path)
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(image_path))[0]
        candidate = os.path.join(out_dir, f"{base}_converted.pdf")
        if overwrite:
            out_pdf = candidate
        else:
            if not os.path.exists(candidate):
                out_pdf = candidate
            else:
                idx = 1
                while True:
                    candidate_i = os.path.join(out_dir, f"{base}_converted({idx}).pdf")
                    if not os.path.exists(candidate_i):
                        out_pdf = candidate_i
                        break
                    idx += 1
    with Image.open(image_path) as im:
        frames = []
        try:
            for frame in ImageSequence.Iterator(im):
                f = frame.copy()
                try:
                    f = ImageOps.exif_transpose(f)
                except Exception:
                    pass
                if f.mode not in ("RGB", "L"):
                    f = f.convert("RGB")
                frames.append(f)
        except Exception:
            f = im.copy()
            try:
                f = ImageOps.exif_transpose(f)
            except Exception:
                pass
            if f.mode not in ("RGB", "L"):
                f = f.convert("RGB")
            frames = [f]
        if len(frames) == 1:
            frames[0].save(out_pdf, format="PDF", resolution=300.0)
        else:
            first, rest = frames[0], frames[1:]
            first.save(out_pdf, format="PDF", resolution=300.0, save_all=True, append_images=rest)
        for fr in frames:
            try:
                fr.close()
            except Exception:
                pass
    return out_pdf