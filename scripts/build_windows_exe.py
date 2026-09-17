"""Build standalone Windows executable for MeetTrace using PyInstaller."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def build() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    scripts_dir = root_dir / "scripts"
    icons_dir = root_dir / "extension" / "icons"
    icon_path = icons_dir / "app_icon.ico"

    # 1. Ensure icons exist
    if not icon_path.is_file():
        print("Generating icons...")
        subprocess.run([sys.executable, str(scripts_dir / "generate_icons.py")], check=True)

    entry_point = root_dir / "src" / "meettrace" / "ui" / "app.py"

    pyinstaller_args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=MeetTrace",
        "--onedir",
        "--noconsole",
        "--clean",
        "--noconfirm",
        f"--icon={icon_path}",
        # Paths
        f"--paths={root_dir / 'src'}",
        # Hidden imports
        "--hidden-import=meettrace",
        "--hidden-import=meettrace.ui.app",
        "--hidden-import=pyaudiowpatch",
        "--hidden-import=pycaw",
        "--hidden-import=comtypes",
        "--hidden-import=faster_whisper",
        "--hidden-import=ctranslate2",
        "--hidden-import=huggingface_hub",
        "--hidden-import=tokenizers",
        # Collect all binaries & data for complex packages
        "--collect-all=faster_whisper",
        "--collect-all=ctranslate2",
        "--collect-all=pyaudiowpatch",
        "--collect-all=pycaw",
        "--collect-all=comtypes",
        # Entrypoint
        str(entry_point),
    ]

    print("Running PyInstaller with arguments:")
    print(" ".join(pyinstaller_args))

    result = subprocess.run(pyinstaller_args, cwd=root_dir, check=False)
    if result.returncode != 0:
        print(f"PyInstaller failed with exit code {result.returncode}")
        return result.returncode

    # 2. Copy extension/ folder and documentation into dist/MeetTrace/
    dist_dir = root_dir / "dist" / "MeetTrace"
    if dist_dir.is_dir():
        dist_ext_dir = dist_dir / "extension"
        if dist_ext_dir.exists():
            shutil.rmtree(dist_ext_dir)
        shutil.copytree(root_dir / "extension", dist_ext_dir)
        print(f"Copied extension to {dist_ext_dir}")

        shutil.copy(root_dir / "README.md", dist_dir / "README.md")
        print("Copied README.md to dist")

    print("\n" + "=" * 60)
    print("Build complete! Executable is ready at:")
    print(f"  {dist_dir / 'MeetTrace.exe'}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(build())
