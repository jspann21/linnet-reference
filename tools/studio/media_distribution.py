"""Package the Windows Media Manager with its Python runtime and dependencies."""
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from tools.studio.targets import ROOT


def create(output):
    if os.name != "nt":
        raise ValueError("Build the Windows Media Manager on Windows.")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Media Manager output already exists")
    try:
        import PyInstaller  # noqa: F401
    except ImportError as error:
        raise RuntimeError("Install packaging support with: python -m pip install pyinstaller==6.22.3") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="media-package-", dir=ROOT / "out") as temporary:
        work = Path(temporary)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
                   "--onedir", "--name", "Linnet Media", "--paths", str(ROOT),
                   "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
                   "--specpath", str(work), "--collect-all", "lz4",
                   "--copy-metadata", "mutagen", "--copy-metadata", "Pillow",
                   "--copy-metadata", "pyserial", "--copy-metadata", "PySide6"]
        for name in ("config", "targets", "hal", "services", "ui", "assets", "themes", "sdk/assets"):
            command += ["--add-data", str(ROOT / name) + os.pathsep + name]
        command += ["--add-data", str(ROOT / "tools/studio/media_desktop.qss") + os.pathsep + "tools/studio",
                    str(ROOT / "tools/studio/media_entry.py")]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError("Media Manager packaging failed:\n" + result.stdout + result.stderr)
        # Qt on Windows imports the OS's unsuffixed ICU API. PyInstaller can
        # pick up an unrelated ICU build from PATH, whose versioned exports
        # break QtCore at startup. Let Windows supply its own ICU libraries.
        for library in (work / "dist/Linnet Media/_internal").glob("icu*.dll"):
            library.unlink()
        from tools.studio.apple_tools import distribution
        distribution(work / "dist/Linnet Media/_internal/apple-tools")
        from tools.content.aac_index import executable as aac_executable
        shutil.copy2(aac_executable(), work / 'dist/Linnet Media/_internal/aac-index.exe')
        from tools.content.mp3_index import executable as mp3_executable
        shutil.copy2(mp3_executable(), work / 'dist/Linnet Media/_internal/mp3-index.exe')
        archive = work / "media.zip"
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted((work / "dist").rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(work / "dist").as_posix())
        archive.replace(output)
    return dict(archive=str(output), executable="Linnet Media/Linnet Media.exe")
