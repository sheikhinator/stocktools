# PyInstaller spec for Stock Compass (one-folder build, no console window).
# Build from the repository root:  pyinstaller packaging/stockcompass.spec
import os
from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[SRC],
    binaries=collect_dynamic_libs("duckdb"),
    datas=[(os.path.join(SRC, "stockcompass", "assets"), os.path.join("assets"))],
    hiddenimports=["python_calamine", "duckdb", "xlsxwriter", "openpyxl",
                   "PySide6.QtCharts", "stockcompass.importer.parsers.gima", "stockcompass.importer.parsers.bo",
                   "stockcompass.importer.parsers.bc", "stockcompass.importer.parsers.dp",
                   "stockcompass.importer.parsers.orders"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "cryptography", "pyarrow", "numpy.f2py", "pandas", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf",
              "PySide6.QtDesigner", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StockCompass", icon=os.path.join(SPECPATH, "icon.ico"),
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="StockCompass")
