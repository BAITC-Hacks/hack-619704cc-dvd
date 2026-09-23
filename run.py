"""One-command bootstrap: python run.py (Python 3.11+)."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Установите Python 3.11 или новее.")
    environment = ROOT / ".venv-career"
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = ROOT / "requirement.txt"
    marker = environment / ".requirements-installed"
    content = requirements.read_bytes()
    if not marker.exists() or marker.read_bytes() != content:
        subprocess.run([str(interpreter), "-m", "pip", "install", "-r", str(requirements)], check=True)
        marker.write_bytes(content)
    subprocess.run([str(interpreter), "-m", "streamlit", "run", str(ROOT / "app.py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
