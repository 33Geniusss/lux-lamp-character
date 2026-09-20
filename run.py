"""Convenience launcher that works without installing the package."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from lamp_character.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
