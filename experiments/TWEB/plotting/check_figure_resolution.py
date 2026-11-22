"""Check native PNG detail and stamp 1000-dpi metadata without resampling.

Export vector sources at >=7000 px wide first. A conservative 7-inch maximum
printed width bounds effective resolution; a narrower LaTeX figure has more dpi.
Only PNG density metadata is changed. Decoded pixel values must remain identical.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image

MIN_DPI = 1000
MAX_WIDTH_INCHES = 7
# PNG stores integer pixels per metre. Round upward so encoded dpi never falls
# just below the required minimum (a nominal 1000 dpi otherwise becomes 999.998).
STAMP_DPI = math.ceil(MIN_DPI / 0.0254) * 0.0254


def check_figure(path, *, check_only=False):
    path = Path(path)
    with Image.open(path) as original:
        if original.format != "PNG":
            raise ValueError(f"{path}: manuscript figures must be PNG")
        width, height = original.size
        if width < MIN_DPI * MAX_WIDTH_INCHES:
            raise ValueError(f"{path}: {width}px is below 7000px; re-export the source")
        pixels_before = hashlib.sha256(original.tobytes()).hexdigest()
        density = original.info.get("dpi", (0, 0))
        density_ok = len(density) == 2 and all(
            math.isfinite(value) and value >= MIN_DPI for value in density
        )
        if not density_ok:
            if check_only:
                raise ValueError(f"{path}: missing or insufficient 1000-dpi metadata")
            with original.copy() as image:
                image.save(path, dpi=(STAMP_DPI, STAMP_DPI))
    with Image.open(path) as verified:
        if verified.size != (width, height) or (
            hashlib.sha256(verified.tobytes()).hexdigest() != pixels_before
        ):
            raise ValueError(f"{path}: decoded pixels changed unexpectedly")
        density = verified.info.get("dpi", (0, 0))
        if not all(math.isfinite(value) and value >= MIN_DPI for value in density):
            raise ValueError(f"{path}: insufficient density metadata after verification")
    return {
        "file": str(path), "width_px": width, "height_px": height,
        "metadata_dpi": density,
        "effective_dpi_at_7_inches": width / MAX_WIDTH_INCHES,
        "max_print_width_inches_at_1000_dpi": width / MIN_DPI,
        "resampled": False, "pixel_sha256": pixels_before,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.files:
        print(json.dumps(check_figure(path, check_only=args.check)))


if __name__ == "__main__":
    main()
