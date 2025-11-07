import argparse
from pathlib import Path
import sys
import json
 
import cv2
 
from stamp_processing import StampDetector
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Path to input image")
    parser.add_argument("--out-dir", default="out", help="Directory to save outputs")
    parser.add_argument("--detector-weight", default=None, help="Path to local detector weight (.pt)")
    args = parser.parse_args()
 
    img_path = Path(args.image)
    if not img_path.exists():
        print(f"ERROR: Image not found: {img_path}")
        sys.exit(1)
 
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
 
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"ERROR: Failed to read image: {img_path}")
        sys.exit(1)
 
    # Detection
    if args.detector_weight:
        weight_path = Path(args.detector_weight)
        if not weight_path.exists():
            print(f"ERROR: Detector weight not found: {weight_path}")
            sys.exit(1)
        detector = StampDetector(model_path=str(weight_path))
    else:
        detector = StampDetector()
    boxes = detector([img])[0]
 
    vis = img.copy()
    for (x1, y1, x2, y2) in boxes:
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
 
    vis_path = out_dir / f"{img_path.stem}_with_boxes{img_path.suffix}"
    cv2.imwrite(str(vis_path), vis)
 
    # JSON summary
    result_path = out_dir / "result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"stamp_present": bool(len(boxes) > 0)}, f)
 
    print("detections:", boxes)
    print("saved visualization:", vis_path)
    print("saved result json:", result_path)
 
 
if __name__ == "__main__":
    main()
 
 