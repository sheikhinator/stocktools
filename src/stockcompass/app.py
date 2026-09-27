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
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
        from stockcompass.web import window as _web  # noqa: F401  (WebEngine must load before QApplication)
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
        w.close()
        lines.append("classic pages: ok")
        ok &= _selftest_web(app, db, lines)
        db.close()
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("SELFTEST " + ("PASSED" if ok else "FAILED"))
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return 0 if ok else 1


def _selftest_web(app, db, lines) -> bool:
    """Load the real screens in WebEngine, visit every page and open a drill-down; any JavaScript error fails."""
    import time

    from stockcompass.web.window import WebWindow

    w = WebWindow(db)
    w.show()

    def wait(cond, secs=40):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.02)
        return False

    def js(code):
        box = []
        w.page.runJavaScript(code, 0, lambda r: box.append(r))
        wait(lambda: bool(box), 20)
        return box[0] if box else None

    ready = lambda: js("!!document.querySelector('.nav') && !document.querySelector('.topbar-load')")
    good = wait(lambda: bool(ready()), 60)
    lines.append(f"web: loaded={good}")
    for pg in ["home", "agent", "analyse", "advisor", "sales", "stock", "orders", "promos", "category", "score", "health", "import", "settings"]:
        js(f"go('{pg}')")
        wait(lambda: bool(ready()), 30)
        if pg == "agent":
            wait(lambda: bool(js("!!document.querySelector('.ag-box')")), 30)
        if pg == "advisor":
            wait(lambda: bool(js("!!document.querySelector('.oa-steps')")), 30)
        if pg == "analyse":
            wait(lambda: bool(js("!!document.querySelector('.an-ctl') && !AN.busy")), 30)
        err = js("(document.querySelector('.errbox')||{}).textContent||''")
        if err:
            lines.append(f"web page {pg}: {err[:300]}")
            good = False
    js("openDrill({m:'negative'})")
    wait(lambda: bool(js("!!document.querySelector('.drawer table') || !!document.querySelector('.drawer .emptybox')")), 30)
    errs = list(w.page.errors) + (js("window.SC_errors||[]") or [])
    lines.append(f"web: pages ok, js errors={errs}")
    w.close()
    return good and not errs


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) >= 2 and argv[1] == "--selftest":
        return selftest(argv[2] if len(argv) > 2 else "selftest.log")
    from PySide6.QtCore import Qt
    try:  # the new screens need Qt WebEngine, which must be loaded before the QApplication exists
        from stockcompass.web.window import WebWindow, webengine_available
        use_web = webengine_available()
    except Exception:
        use_web = False
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
    w = None
    if use_web:
        try:
            w = WebWindow(db)
        except Exception:
            traceback.print_exc()
            w = None
    if w is None:  # classic screens if WebEngine cannot start on this PC
        w = MainWindow(db)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
