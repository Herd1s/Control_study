"""Draw the application's geometric icon, without external image assets."""
from pathlib import Path
import struct
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

root = Path(__file__).resolve().parents[1]
icon = QImage(256, 256, QImage.Format.Format_ARGB32)
icon.fill(Qt.GlobalColor.transparent)
painter = QPainter(icon)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor('#2D8375'))
painter.drawRoundedRect(QRectF(5, 5, 246, 246), 54, 54)
painter.setPen(QPen(QColor('#DEF2DF'), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
painter.drawLine(QPointF(48, 192), QPointF(208, 192))
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor('#EDF5E8'))
painter.drawRoundedRect(QRectF(80, 141, 97, 40), 10, 10)
painter.setPen(QPen(QColor('#EDB780'), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
painter.drawLine(QPointF(128, 141), QPointF(147, 68))
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor('#FFD6A8'))
painter.drawEllipse(QPointF(147, 65), 14, 14)
painter.end()
resource = root / 'src/control_lab/resources/icon.png'
resource.parent.mkdir(parents=True, exist_ok=True)
assert icon.save(str(resource))
png = QByteArray()
buffer = QBuffer(png)
buffer.open(QIODevice.OpenModeFlag.WriteOnly)
icon.save(buffer, 'PNG')
payload = bytes(png)
# ICO permits a PNG image as its image payload. 0 width/height means 256.
header = struct.pack('<HHH', 0, 1, 1)
entry = struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(payload), 22)
(root / 'packaging/windows/control_lab.ico').write_bytes(header + entry + payload)
