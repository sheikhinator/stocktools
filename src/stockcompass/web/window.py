"""The desktop window: the Stock Compass screens (web/index.html) inside Qt WebEngine, fully offline.

JavaScript talks to Python through a QWebChannel object called `bridge`. Real file dialogs, folder
picking, Excel saving and drag-and-drop of files from Explorer are done here, on the Qt side.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import threading

from PySide6.QtCore import QEvent, QObject, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow

from stockcompass.db import Database
from stockcompass.paths import exports_dir, resource

from .api import Api, Host, dumps

FILE_FILTER = "Reports (*.xlsx *.xlsm *.xls *.xlsb *.csv *.txt *.tsv *.htm *.html *.ods);;All files (*)"


class MainThread(QObject):
    """Runs a function on the Qt main thread for a worker thread (the agent writes reports in the background)."""
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run, Qt.QueuedConnection)

    @Slot(object)
    def _run(self, job):
        fn, done = job
        try:
            fn(done)
        except Exception as e:  # never leave the worker waiting
            done(None, e)


class QtHost(Host):
    def __init__(self, window: QMainWindow):
        self.w = window
        self.main = MainThread()
        self._pdf_pages = []

    def pick_files(self, kind: str = "reports") -> list[str]:
        filt = "AI models (*.gguf);;All files (*)" if kind == "gguf" else FILE_FILTER
        files, _ = QFileDialog.getOpenFileNames(self.w, "Choose files", str(Path.home()), filt)
        return files

    def _on_main(self, fn, timeout: float = 90):
        box, ev = {}, threading.Event()

        def done(result=None, err=None):
            box["r"], box["e"] = result, err
            ev.set()

        if threading.current_thread() is threading.main_thread():
            fn(done)
        else:
            self.main.call.emit((fn, done))
        ev.wait(timeout)
        return box.get("r")

    def html_to_pdf(self, html_path: str, pdf_path: str) -> bool:
        """Print the report's HTML to an A4 PDF with Chromium (same look as the screen)."""
        def work(done):
            from PySide6.QtGui import QPageLayout, QPageSize
            from PySide6.QtCore import QMarginsF
            page = QWebEnginePage()
            self._pdf_pages.append(page)

            def finished(path, ok):
                self._pdf_pages.remove(page)
                page.deleteLater()
                done(bool(ok))

            def loaded(ok):
                if not ok:
                    finished(pdf_path, False)
                    return
                layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter)
                page.printToPdf(pdf_path, layout)

            page.pdfPrintingFinished.connect(finished)
            page.loadFinished.connect(loaded)
            page.load(QUrl.fromLocalFile(html_path))

        return bool(self._on_main(work, 120))

    def svg_to_png(self, svg: str) -> bytes | None:
        """Charts in Word files: draw the SVG into a picture."""
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            from PySide6.QtGui import QColor, QImage, QPainter
            from PySide6.QtSvg import QSvgRenderer
            r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            size = r.defaultSize()
            img = QImage(size.width() * 2, size.height() * 2, QImage.Format_ARGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            r.render(p)
            p.end()
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            return bytes(buf.data())
        except Exception:
            return None

    def pick_folder(self) -> str | None:
        return QFileDialog.getExistingDirectory(self.w, "Add a folder of reports", str(Path.home())) or None

    def save_path(self, name: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(self.w, "Export to Excel", str(exports_dir() / name), "Excel (*.xlsx)")
        return path or None

    def open_path(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))


class Bridge(QObject):
    def __init__(self, api: Api):
        super().__init__()
        self.api = api

    @Slot(str, str, result=str)
    def call(self, method: str, params: str) -> str:
        try:
            p = json.loads(params or "{}")
        except ValueError:
            p = {}
        return dumps(self.api.dispatch(method, p))


class Page(QWebEnginePage):
    """Collects JavaScript errors (the self-test fails on any) and keeps links out of the app window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.errors: list[str] = []

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel and "favicon" not in message:
            self.errors.append(f"{message} ({Path(source).name}:{line})")

    def grant_media(self, origin, feature):
        """Voice typing: allow the microphone for the app's own pages only."""
        if origin.scheme() in ("file", "qrc") or origin.host() in ("127.0.0.1", "localhost"):
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionPolicy.PermissionGrantedByUser)
        else:
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
            return False
        return True


class WebWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle("Stock Compass")
        self.resize(1440, 920)
        self.view = QWebEngineView(self)
        self.page = Page(self.view)
        self.view.setPage(self.page)
        try:        # Qt 6.8+: one permission object; older: feature + origin
            self.page.permissionRequested.connect(lambda perm: perm.grant() if perm.origin().scheme() in ("file", "qrc") else perm.deny())
        except AttributeError:
            self.page.featurePermissionRequested.connect(self.page.grant_media)
        s = self.page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.api = Api(db, QtHost(self))
        self.bridge = Bridge(self.api)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.view)
        self.setAcceptDrops(True)
        self.view.setAcceptDrops(True)
        self.view.installEventFilter(self)
        self.view.loadFinished.connect(self._hook_drops)
        self.view.load(QUrl.fromLocalFile(str(resource("web", "index.html"))))

    # Files dragged from Explorer: WebEngine only gives the page file names, so catch the drop here and hand the
    # real paths to the import screen.
    def _hook_drops(self, ok):
        fp = self.view.focusProxy()
        if fp is not None:
            fp.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove) and ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            return True
        if t == QEvent.Type.Drop and ev.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.page.runJavaScript(f"window.SC_drop({json.dumps(paths)})")
                ev.acceptProposedAction()
                return True
        return super().eventFilter(obj, ev)



def webengine_available() -> bool:
    if os.environ.get("STOCKCOMPASS_CLASSIC") == "1":
        return False
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
        return resource("web", "index.html").exists()
    except Exception:
        return False
