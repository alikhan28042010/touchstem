"""Synthetic webcam video for end-to-end tests of the living sheet.

Renders the A4 mat (markers + tactile plate) as a tilted phone camera would see it and
moves a green fingertip sticker over chosen hotspots on a timeline. Output: .y4m that
Chromium can use as a fake camera (--use-file-for-fake-video-capture).

Usage: python -I tools/fake_camera.py <example.json> <out.y4m> <timeline.json>
timeline.json: [[seconds, hotspot_id_or_null], ...]  e.g. [[1.0, null], [1.2, "e3"], [0.5, null]]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from touchstem.model import Circuit  # noqa: E402
from touchstem.render import build_diagram, polygons  # noqa: E402
from touchstem.touch import MAT_H, MAT_W, _marker_cells, marker_layout, plate_offset  # noqa: E402

PX = 3.0            # mat raster: pixels per mm
W, H, FPS = 640, 480, 15
CAM = [(70, 50), (585, 72), (612, 448), (36, 424)]   # where the mat corners land in the camera image


def render_mat(layout) -> Image.Image:
    img = Image.new("RGB", (int(MAT_W * PX), int(MAT_H * PX)), "white")
    d = ImageDraw.Draw(img)
    for mid, cx, cy, side in marker_layout():
        cell = side / 6
        x0, y0 = cx - side / 2, cy - side / 2
        d.rectangle([x0 * PX, y0 * PX, (x0 + side) * PX, (y0 + side) * PX], fill="black")
        for r, row in enumerate(_marker_cells(mid)):
            for c, bit in enumerate(row):
                if bit == "1":
                    d.rectangle([(x0 + (c + 1) * cell) * PX, (y0 + (r + 1) * cell) * PX,
                                 (x0 + (c + 2) * cell) * PX - 1, (y0 + (r + 2) * cell) * PX - 1], fill="white")
    ox, oy = plate_offset(layout)
    d.rectangle([ox * PX, oy * PX, (ox + layout.width) * PX, (oy + layout.height) * PX], fill=(238, 239, 234))
    for p in polygons(layout.raised):
        d.polygon([((x + ox) * PX, (y + oy) * PX) for x, y in p.exterior.coords], fill=(120, 124, 118))
    for x, y in layout.dots:
        d.ellipse([(x + ox - 0.8) * PX, (y + oy - 0.8) * PX, (x + ox + 0.8) * PX, (y + oy + 0.8) * PX], fill=(120, 124, 118))
    return img


def homography(src, dst):
    """Direct linear transform: 3x3 H with dst ~ H @ src."""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.array(A, float))
    h = vt[-1]
    return (h / h[-1]).reshape(3, 3)


def to_y4m_frame(img: Image.Image) -> bytes:
    ycc = img.convert("YCbCr")
    y, cb, cr = [np.asarray(ch, np.uint8) for ch in ycc.split()]
    cb = np.asarray(Image.fromarray(cb).resize((W // 2, H // 2), Image.BILINEAR))
    cr = np.asarray(Image.fromarray(cr).resize((W // 2, H // 2), Image.BILINEAR))
    return b"FRAME\n" + y.tobytes() + cb.tobytes() + cr.tobytes()


def main():
    example, out, timeline = sys.argv[1], sys.argv[2], json.loads(Path(sys.argv[3]).read_text())
    c = Circuit.from_dict(json.loads(Path(example).read_text(encoding="utf-8")))
    layout = build_diagram(c)
    mat = render_mat(layout)
    mat_px = [(0, 0), (MAT_W * PX, 0), (MAT_W * PX, MAT_H * PX), (0, MAT_H * PX)]
    Hmi = homography(mat_px, CAM)                       # mat pixels -> camera pixels
    Him = np.linalg.inv(Hmi)                            # camera -> mat (PIL needs output->input)
    coeffs = (Him / Him[2, 2]).flatten()[:8]
    base = mat.transform((W, H), Image.PERSPECTIVE, tuple(coeffs), Image.BILINEAR, fillcolor=(60, 52, 44))
    ox, oy = plate_offset(layout)
    spots = {h["id"]: (h["x"] + ox, h["y"] + oy) for h in layout.hotspots}
    with open(out, "wb") as f:
        f.write(f"YUV4MPEG2 W{W} H{H} F{FPS}:1 Ip A1:1 C420jpeg\n".encode())
        for secs, hid in timeline:
            for _ in range(int(round(secs * FPS))):
                frame = base.copy()
                if hid:
                    mx, my = spots[hid]
                    p = Hmi @ np.array([mx * PX, my * PX, 1.0])
                    u, v = p[0] / p[2], p[1] / p[2]
                    ImageDraw.Draw(frame).ellipse([u - 7, v - 7, u + 7, v + 7], fill=(40, 220, 70))
                f.write(to_y4m_frame(frame))
    base.save(out.replace(".y4m", ".png"))
    print(json.dumps({k: [round(a, 1), round(b, 1)] for k, (a, b) in spots.items()}))


if __name__ == "__main__":
    main()
