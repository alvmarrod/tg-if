"""Read service version from version.txt in the project root."""

from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_version() -> str:
    return (_PROJECT_ROOT / "version.txt").read_text().strip()
