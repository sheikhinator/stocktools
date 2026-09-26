"""Start Stock Compass."""

from __future__ import annotations

import sys
import traceback


def selftest(log_path: str) -> int:
    """Headless end-to-end check used by the build: open a database, import a report, compute the home
    screen and draw every page. Exit code 0 = healthy. Writes a log because the .exe has no console."""
    import os
    import tempfile

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["STOCKCOMPASS_HOME"] = tempfile.mkdtemp(prefix="sc_selftest_")
    lines = []
    ok = True
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication([sys.argv[0]])
        from stockcompass.analytics.core import Scope, overview
        from stockcompass.db import Database
        from stockcompass.importer.pipeline import analyze, commit
        from stockcompass.ui import theme
        from stockcompass.ui.main_window import MainWindow

        theme.load_fonts()
        db = Database()
        lines.append("database: ok")
        text = "STR\tITEMPR\tPHQTPR\tISTSPR\tIDSCPR\n504\t123456\t-3\tNI\tTEST\n500\t123457\t-1\tAC\tTEST 2\n"
        outs = commit(analyze("selftest.txt", db, text=text), db)
        lines.append(f"import: {[(o.report_type, o.status, o.rows) for o in outs]}")
        ok &= bool(outs) and outs[0].status == "ok" and outs[0].rows == 2
        kpis, _ = overview(db, Scope())
        lines.append(f"overview: {[k.key for k in kpis]}")
        w = MainWindow(db)
        for target in ["home", "sales", "stock:neg", "stock:sleeping", "stock:move", "orders", "promos", "category",
                       "score", "import", "health", "settings"]:
            w.go(target)
            app.processEvents()
        w.toggle_lang()
        w.toggle_lang()
        lines.append("pages: ok")
        db.close()
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("SELFTEST " + ("PASSED" if ok else "FAILED"))
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) >= 2 and argv[1] == "--selftest":
        return selftest(argv[2] if len(argv) > 2 else "selftest.log")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from stockcompass.db import Database
    from stockcompass.ui import theme
    from stockcompass.ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("Stock Compass")
    app.setOrganizationName("MAF Carrefour Pakistan")
    theme.load_fonts()
    from PySide6.QtGui import QIcon
    from stockcompass.paths import resource
    app.setWindowIcon(QIcon(str(resource("assets", "icon.png"))))

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
