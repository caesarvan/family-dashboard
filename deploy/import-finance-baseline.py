"""Import a private stdin payload without exposing its values in command output."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finance_baseline import main


if __name__ == '__main__':
    raise SystemExit(main())
