"""The desktop window: the Stock Compass screens (web/index.html) inside Qt WebEngine, fully offline.

JavaScript talks to Python through a QWebChannel object called `bridge`. Real file dialogs, folder
picking, Excel saving and drag-and-drop of files from Explorer are done here, on the Qt side.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMainWindow

from stockcompass.db import Database
from stockcompass.paths import exports_dir, resource

from .api import Api, Host, dumps

FILE_FILTER = "Reports (*.xlsx *.xlsm *.xls *.xlsb *.csv *.txt *.tsv *.htm *.html *.ods);;All files (*)"


class QtHost(Host):
    def __init__(self, window: QMainWindow):
        self.w = window

    def pick_files(self) -> list[str]:
        files, _ = QFileDialog.getOpenFileNames(self.w, "Add reports", str(Path.home()), FILE_FILTER)
        return files

    def pick_folder(self) -> str | None:
        return QFileDialog.getExistingDirectory(self.w, "Add a folder of reports", str(Path.home())) or None

    def save_path(self, name: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(self.w, "Export to Excel", str(exports_dir() / name), "Excel (*.xlsx)")
        return path or None

    def open_path(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


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
