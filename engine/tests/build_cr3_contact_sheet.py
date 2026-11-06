"""Genera una hoja visual de previews CR3 para inventarios de prueba."""

from __future__ import annotations

import argparse
import io
import math
from pathlib import Path

import rawpy
from PIL import Image, ImageDraw, ImageFont, ImageOps


def _preview(path: Path) -> Image.Image:
    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                image = Image.open(io.BytesIO(thumb.data))
            else:
                image = Image.fromarray(thumb.data)
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            image = Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))
    image.load()
    return ImageOps.exif_transpose(image).convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=4)
    args = parser.parse_args()

    files = sorted(
        (path for path in args.source.iterdir() if path.is_file() and path.suffix.lower() == ".cr3"),
        key=lambda path: path.name.lower(),
    )
    if not files:
        raise FileNotFoundError(f"No se encontraron archivos CR3 en {args.source}")

    cell_width, image_height, label_height = 320, 220, 34
    columns = max(1, args.columns)
    rows = math.ceil(len(files) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * (image_height + label_height)), "#18181b")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=16)

    for index, path in enumerate(files):
        preview = ImageOps.contain(_preview(path), (cell_width - 12, image_height - 12))
        column, row = index % columns, index // columns
        left = column * cell_width + (cell_width - preview.width) // 2
        top = row * (image_height + label_height) + (image_height - preview.height) // 2
        sheet.paste(preview, (left, top))
        draw.text(
            (column * cell_width + 8, row * (image_height + label_height) + image_height + 6),
            path.name,
            fill="white",
            font=font,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
