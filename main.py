import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont, QIcon
from PyQt6.QtCore import Qt

from src.config.config_manager import ConfigManager
from src.ui.main_window import MainWindow
from src.ui.config_dialog import ConfigDialog


def _dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    c = {
        QPalette.ColorRole.Window:          QColor(13,  13,  20),
        QPalette.ColorRole.WindowText:      QColor(200, 200, 230),
        QPalette.ColorRole.Base:            QColor(10,  10,  16),
        QPalette.ColorRole.AlternateBase:   QColor(20,  20,  30),
        QPalette.ColorRole.ToolTipBase:     QColor(10,  10,  16),
        QPalette.ColorRole.ToolTipText:     QColor(200, 200, 230),
        QPalette.ColorRole.Text:            QColor(200, 200, 230),
        QPalette.ColorRole.Button:          QColor(22,  22,  34),
        QPalette.ColorRole.ButtonText:      QColor(200, 200, 230),
        QPalette.ColorRole.BrightText:      QColor(255,  80,  80),
        QPalette.ColorRole.Link:            QColor(0,  170, 255),
        QPalette.ColorRole.Highlight:       QColor(0,  119, 204),
        QPalette.ColorRole.HighlightedText: QColor(255, 255, 255),
    }
    for role, color in c.items():
        palette.setColor(role, color)
    app.setPalette(palette)
    app.setStyleSheet("""
        QToolTip { color: #c8c8e0; background: #0d0d14; border: 1px solid #2a2a3a; }
        QMenuBar  { background: #0d0d14; }
        QMenu     { background: #12121c; border: 1px solid #2a2a3a; }
        QMenu::item:selected { background: #0077cc; }
        QScrollBar:vertical { background: #12121c; width: 8px; }
        QScrollBar::handle:vertical { background: #3a3a5a; border-radius: 4px; }
        QSpinBox, QLineEdit {
            background: #12121c; border: 1px solid #2a2a3a;
            color: #c8c8e0; border-radius: 4px; padding: 2px 6px;
        }
        QSpinBox:focus, QLineEdit:focus { border: 1px solid #0077cc; }
    """)


def main() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    _dark_palette(app)

    icon_path = Path(__file__).parent / "Readme" / "icono.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config = ConfigManager()

    if not config.has_valid_config():
        dialog = ConfigDialog()
        dialog.setWindowTitle("Configuración inicial — AlgoTrader")
        if dialog.exec():
            api_key, secret_key = dialog.get_credentials()
            config.save_config(api_key, secret_key)
        else:
            sys.exit(0)

    window = MainWindow(config)
    window.show()

    # Centrar en pantalla y forzar al frente
    screen = app.primaryScreen().availableGeometry()
    wg = window.frameGeometry()
    window.move(
        screen.x() + (screen.width()  - wg.width())  // 2,
        screen.y() + (screen.height() - wg.height()) // 2,
    )
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
