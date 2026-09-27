"""Explicitly promote an inspected candidate to the active model directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.ml.anomaly import load_model, save_model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--active", type=Path, default=Path("models/active"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        candidate = load_model(args.candidate)
    except (OSError, ValueError) as error:
        raise SystemExit(f"candidate rejected: {error}") from None
    if args.active.exists() and not args.replace:
        raise SystemExit("active model exists; pass --replace after reviewing the candidate")
    if args.active.exists() and args.replace:
        backup = args.active.with_name(f"{args.active.name}.backup")
        if backup.exists():
            raise SystemExit(f"rollback backup already exists: {backup}; archive it before replacing")
        args.active.rename(backup)
    save_model(candidate, args.active)
    print(
        f"promoted candidate {candidate.model_version} ({candidate.algorithm}) "
        f"to {args.active}; review metrics and retain rollback artifacts"
    )


if __name__ == "__main__":
    main()