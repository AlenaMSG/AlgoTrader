from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class ConfigDialog(QDialog):
    def __init__(self, parent=None, prefill: tuple[str, str] = ("", "")):
        super().__init__(parent)
        self.setWindowTitle("Configuración — Alpaca API Keys")
        self.setFixedSize(480, 300)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._build_ui(prefill)

    def _build_ui(self, prefill: tuple[str, str]) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(28, 24, 28, 24)

        # Title
        title = QLabel("Credenciales de Alpaca Paper Trading")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # Hint
        hint = QLabel(
            "Obtén tus claves en <b>alpaca.markets → Paper Trading → API Keys</b>.<br>"
            "Se guardarán en <code>.env</code> en la raíz del proyecto."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: #8888aa; font-size: 11px;")
        layout.addWidget(hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a3a;")
        layout.addWidget(sep)

        # API KEY
        layout.addWidget(QLabel("API Key:"))
        self._api_key_input = QLineEdit(prefill[0])
        self._api_key_input.setPlaceholderText("PKXXXXXXXXXXXXXXXXXXXXXXXX")
        self._api_key_input.setMinimumHeight(34)
        layout.addWidget(self._api_key_input)

        # SECRET KEY
        layout.addWidget(QLabel("Secret Key:"))
        self._secret_input = QLineEdit(prefill[1])
        self._secret_input.setPlaceholderText("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret_input.setMinimumHeight(34)
        layout.addWidget(self._secret_input)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setFixedWidth(100)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Guardar")
        save_btn.setFixedWidth(100)
        save_btn.setDefault(True)
        save_btn.setStyleSheet(
            "QPushButton { background: #0077cc; color: white; border-radius: 4px; }"
            "QPushButton:hover { background: #0099ff; }"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _on_save(self) -> None:
        api_key = self._api_key_input.text().strip()
        secret  = self._secret_input.text().strip()
        if not api_key or not secret:
            self._api_key_input.setStyleSheet("border: 1px solid red;" if not api_key else "")
            self._secret_input.setStyleSheet("border: 1px solid red;" if not secret else "")
            return
        self.accept()

    def get_credentials(self) -> tuple[str, str]:
        return self._api_key_input.text().strip(), self._secret_input.text().strip()
