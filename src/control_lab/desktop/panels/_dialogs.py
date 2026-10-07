"""Keep experiment dialogs reachable on small logical-pixel displays."""
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget


def scrolling_body(dialog, parent=None, preferred=(880, 650)):
    available = dialog.screen().availableGeometry()
    width, height = available.width()-24, available.height()-48
    if parent is not None:
        window = parent.window()
        width, height = min(width, window.width()-16), min(height, window.height()-24)
    dialog.resize(min(preferred[0], max(240, width)), min(preferred[1], max(240, height)))
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(4, 4, 4, 4)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    layout = QVBoxLayout(content)
    scroll.setWidget(content)
    outer.addWidget(scroll)
    dialog.content_scroll = scroll
    return layout
