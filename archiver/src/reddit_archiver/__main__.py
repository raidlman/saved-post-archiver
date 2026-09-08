import argparse
import sys

from .archive import run


def main() -> int:
    parser = argparse.ArgumentParser(prog="reddit-archiver")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List/resolve/decide only - no files written, no unsave() calls. Overrides DRY_RUN=false in config.env.",
    )
    args = parser.parse_args()
    return run(force_dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
