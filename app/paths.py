"""资料目录。源码运行放在项目 data/，打包后的桌面应用放在用户资料目录。"""
import os
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    override = os.environ.get("FAMILYLEDGER_DATA")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        from platformdirs import user_data_dir
        return Path(user_data_dir("FamilyLedger", appauthor=False)) / "data"
    return project_root() / "data"


def secrets_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return None
    path = project_root() / "secrets.local.json"
    return path if path.is_file() else None
