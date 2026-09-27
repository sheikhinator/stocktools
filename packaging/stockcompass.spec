# PyInstaller spec for Stock Compass (one-folder build, no console window).
# Build from the repository root:  pyinstaller packaging/stockcompass.spec
import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

a = Analysis(
    [os.path.join(SPECPATH, "launch.py")],
    pathex=[SRC],
    binaries=collect_dynamic_libs("duckdb"),
    datas=[(os.path.join(SRC, "stockcompass", "assets"), "assets"),
           (os.path.join(SRC, "stockcompass", "web"), "web")] + collect_data_files("docx"),
    hiddenimports=["python_calamine", "duckdb", "xlsxwriter", "openpyxl",
                   "PySide6.QtCharts", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebChannel",
                   "stockcompass.web.api", "stockcompass.web.window", "PySide6.QtSvg", "docx",
                   "stockcompass.agent.service", "stockcompass.agent.providers", "stockcompass.agent.tools",
                   "stockcompass.agent.local", "stockcompass.agent.report", "stockcompass.agent.memory", "stockcompass.agent.secrets", "stockcompass.importer.parsers.gima", "stockcompass.importer.parsers.bo",
                   "stockcompass.importer.parsers.bc", "stockcompass.importer.parsers.dp",
                   "stockcompass.importer.parsers.orders",
                   # modules DuckDB loads lazily at runtime (missing ones only fail on the user's PC)
                   "uuid", "decimal", "fractions", "ipaddress", "zoneinfo", "json", "datetime", "csv", "tempfile"]
                  + collect_submodules("duckdb"),
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "cryptography", "pyarrow", "numpy.f2py", "pandas",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "PySide6.QtDesigner", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StockCompass", icon=os.path.join(SPECPATH, "icon.ico"),
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="StockCompass")
