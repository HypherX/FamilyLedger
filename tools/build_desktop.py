"""在本机打出未签名的桌面压缩包，不上传。用法：python tools/build_desktop.py"""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"', (ROOT / "app" / "version.py").read_text(encoding="utf-8")).group(1)


def resources(output: Path) -> None:
    import pymupdf
    iconset = output / "FamilyLedger.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(ROOT / "assets/icon.svg") as doc:
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                matrix = pymupdf.Matrix(pixels / doc[0].rect.width, pixels / doc[0].rect.height)
                pix = doc[0].get_pixmap(matrix=matrix, alpha=True)
                pix.save(iconset / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png")
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(256 / doc[0].rect.width, 256 / doc[0].rect.height), alpha=True)
        image = pix.tobytes("png")
        (output / "FamilyLedger.ico").write_bytes(
            struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(image), 22) + image)
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(output / "FamilyLedger.icns")], check=True)
    licenses = output / "third_party_licenses"
    licenses.mkdir(exist_ok=True)
    license_files = []
    versions = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        versions[name] = distribution.version
        folder = licenses / name
        folder.mkdir(exist_ok=True)
        meta = folder / "METADATA.txt"
        meta.write_text(distribution.read_text("METADATA") or name, encoding="utf-8")
        license_files.append(str(meta.relative_to(output)))
    (output / "license-manifest.json").write_text(json.dumps(license_files), encoding="utf-8")
    info = {
        "version": VERSION,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "signed_for_distribution": False,
        "dependencies": versions,
    }
    (output / "build-info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    generated = ROOT / ".build-generated"
    generated.mkdir(exist_ok=True)
    resources(generated)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(dist),
                    "--workpath", str(ROOT / ".build-work"), str(ROOT / "FamilyLedger.spec")], cwd=ROOT, check=True)
    architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    os_name = "macOS" if sys.platform == "darwin" else "Windows"
    stem = f"FamilyLedger-{VERSION}-{os_name}-{architecture}"
    archive = dist / f"{stem}.zip"
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(dist / "FamilyLedger.app"), str(archive)], check=True)
    else:
        shutil.make_archive(str(dist / stem), "zip", dist, "FamilyLedger")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / f"{stem}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    shutil.copy2(generated / "build-info.json", dist / f"{stem}.json")
    print("已生成本机未签名构建：", archive)


if __name__ == "__main__":
    main()
