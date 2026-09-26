"""Start Stock Compass."""

from __future__ import annotations

import sys
import traceback


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from stockcompass.db import Database
    from stockcompass.ui import theme
    from stockcompass.ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("Stock Compass")
    app.setOrganizationName("MAF Carrefour Pakistan")
    theme.load_fonts()

    def excepthook(t, v, tb):
        msg = "".join(traceback.format_exception(t, v, tb))
        try:
            QMessageBox.critical(None, "Stock Compass", "Something went wrong. Nothing was lost.\n\n" + msg[-1500:])
        except Exception:
            print(msg, file=sys.stderr)

    sys.excepthook = excepthook
    try:
        db = Database()
    except Exception as e:
        QMessageBox.critical(None, "Stock Compass", f"The database could not be opened:\n{e}\n\n"
                             "Is Stock Compass already open in another window?")
        return 1
    w = MainWindow(db)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
