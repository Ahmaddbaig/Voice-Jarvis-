"""Jarvis CLI REPL launcher (thin wrapper)."""
import sys
from pathlib import Path

# Ensure src/ is on sys.path so `import jarvis` finds the package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from jarvis.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
