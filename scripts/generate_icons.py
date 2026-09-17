"""Generate clean extension icons using PySide6."""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath


def generate_icons() -> None:
    _app = QGuiApplication.instance() or QGuiApplication([])
    icons_dir = Path("extension/icons")
    icons_dir.mkdir(parents=True, exist_ok=True)

    for size in (16, 48, 128):
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        radius = size * 0.22
        path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        painter.fillPath(path, QColor("#7C5CFC"))

        painter.setPen(QColor("#FFFFFF"))
        font = QFont("Segoe UI", int(size * 0.52), QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "M")
        painter.end()

        target = icons_dir / f"icon{size}.png"
        img.save(str(target))
        print(f"Generated {target}")


if __name__ == "__main__":
    generate_icons()
