"""Import an interview CSV and the authored answer catalog into local SQLite."""
import argparse
import json
from pathlib import Path

from backend.app.question_bank import DEFAULT_CSV, DEFAULT_DB, build_bank


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    print(json.dumps(build_bank(args.csv, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
