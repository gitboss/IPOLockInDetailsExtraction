#!/usr/bin/env python3
"""Restore files from finalized/ folders with strong safety confirmation."""

from pathlib import Path
import shutil
import argparse
import sys

RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_warning() -> None:
    print("")
    print(f"{RED}{BOLD}##############################################################{RESET}")
    print(f"{RED}{BOLD}#                                                            #{RESET}")
    print(f"{RED}{BOLD}#                      !!! WARNING !!!                       #{RESET}")
    print(f"{RED}{BOLD}#                                                            #{RESET}")
    print(f"{RED}{BOLD}#   THIS WILL MOVE FILES OUT OF finalized/ FOLDERS.          #{RESET}")
    print(f"{RED}{BOLD}#   THIS ACTION CANNOT BE UNDONE AUTOMATICALLY.              #{RESET}")
    print(f"{RED}{BOLD}#                                                            #{RESET}")
    print(f"{RED}{BOLD}##############################################################{RESET}")
    print("")


def require_double_confirmation() -> bool:
    print_warning()
    first = input("Type YES to confirm you have read and understood: ").strip()
    if first != "YES":
        print("Cancelled.")
        return False
    second = input("Type YES again to proceed with irreversible restore: ").strip()
    if second != "YES":
        print("Cancelled.")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="downloads")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    finalized_dirs = [p for p in root.rglob("finalized") if p.is_dir()]

    if not finalized_dirs:
        print(f"No finalized folders found under '{root}'.")
        return 0

    if not args.dry_run and not require_double_confirmation():
        return 1

    restored = skipped = errors = 0

    for fdir in finalized_dirs:
        target_dir = fdir.parent
        for src in fdir.iterdir():
            if not src.is_file():
                continue

            dst = target_dir / src.name
            if dst.exists():
                print(f"SKIP (exists): {dst}")
                skipped += 1
                continue

            try:
                if args.dry_run:
                    print(f"WOULD RESTORE: {src} -> {dst}")
                else:
                    shutil.move(str(src), str(dst))
                    print(f"RESTORED: {dst}")
                    restored += 1
            except Exception as e:
                print(f"ERROR: {src} -> {dst} | {e}")
                errors += 1

    print("\nDone.")
    print(f"Restored: {restored}")
    print(f"Skipped : {skipped}")
    print(f"Errors  : {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
