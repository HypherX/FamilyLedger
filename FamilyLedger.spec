# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import json
import re
import sys

root = Path(SPECPATH)
mac = sys.platform == "darwin"
version = re.search(r'VERSION\s*=\s*"([^"]+)"', (root / "app" / "version.py").read_text(encoding="utf-8")).group(1)
generated = root / ".build-generated"
datas = []
for path in (root / "static").rglob("*"):
    if path.is_file() and path.name != ".DS_Store":
        datas.append((str(path), str(path.parent.relative_to(root))))
datas.append((str(generated / "build-info.json"), "."))
if (generated / "license-manifest.json").is_file():
    for relative in json.loads((generated / "license-manifest.json").read_text(encoding="utf-8")):
        datas.append((str(generated / relative), str(Path(relative).parent)))

from PyInstaller.utils.hooks import collect_data_files, copy_metadata
datas += collect_data_files("webview")
for package in ("openai", "pymupdf", "pywebview", "platformdirs", "openpyxl"):
    datas += copy_metadata(package)

hiddenimports = [
    "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on",
    "openpyxl", "xlrd", "pymupdf",
]
for source in (root / "app").rglob("*.py"):
    parts = list(source.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    hiddenimports.append(".".join(parts))
hiddenimports += ["webview.platforms.cocoa"] if mac else ["webview.platforms.winforms", "webview.platforms.edgechromium"]

a = Analysis(
    [str(root / "desktop.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "unittest", "tkinter", "webview.platforms.qt", "webview.platforms.gtk"],
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = str(generated / ("FamilyLedger.icns" if mac else "FamilyLedger.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FamilyLedger", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FamilyLedger")
if mac:
    app = BUNDLE(
        coll, name="FamilyLedger.app", icon=icon,
        bundle_identifier="org.familyledger.desktop", version=version,
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "CFBundleShortVersionString": version,
            "CFBundleDisplayName": "家庭账本",
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSExceptionDomains": {"127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True}},
            },
        },
    )
