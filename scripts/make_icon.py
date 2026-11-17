"""Render the SV-Guard icon with Qt and write app/resources/svguard.{png,ico}.

The .ico holds PNG-compressed images at the sizes Windows asks for, assembled by hand
because Qt's ICO writer stores only a single size.

    python scripts/make_icon.py
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

OUT = Path(__file__).resolve().parents[1] / "app" / "resources"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256

    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0, QColor("#2b5cd6"))
    gradient.setColorAt(1, QColor("#16307a"))
    p.setBrush(gradient)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 48 * s, 48 * s)

    font = QFont("Segoe UI", 1, QFont.Weight.Black)
    font.setPixelSize(max(1, round(118 * s)))
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 18 * s, size, 150 * s), Qt.AlignmentFlag.AlignCenter, "SV")

    check = QPainterPath(QPointF(78 * s, 178 * s))
    check.lineTo(QPointF(112 * s, 210 * s))
    check.lineTo(QPointF(180 * s, 146 * s))
    pen = QPen(QColor("#4ade80"), max(2.0, 22 * s))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(check)
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = len(header) + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, blob in pngs:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    return header + entries + blobs


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (fonts need an app)
    OUT.mkdir(parents=True, exist_ok=True)
    pngs = [(size, png_bytes(render(size))) for size in SIZES]
    (OUT / "svguard.png").write_bytes(pngs[-1][1])
    (OUT / "svguard.ico").write_bytes(build_ico(pngs))
    print(f"wrote {OUT / 'svguard.png'} and {OUT / 'svguard.ico'}")


if __name__ == "__main__":
    main()
