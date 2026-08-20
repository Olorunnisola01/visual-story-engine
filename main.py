import sys
import os

# Ensure bundled assets are findable when running as a PyInstaller exe
if getattr(sys, "frozen", False):
    os.chdir(sys._MEIPASS)  # type: ignore[attr-defined]

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from ui.app import App


def main():
    # Enable high-DPI scaling (Windows 10/11)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")          # consistent look; styled via QSS

    window = App()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
