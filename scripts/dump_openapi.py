"""Render the FastAPI OpenAPI schema to the frontend type snapshot (FT0-T1).

The frontend generates its TypeScript types from ``frontend/openapi.json``
(D2 in ``odd/tasks/f4-frontend.md``), so the snapshot must be reproducible in
CI without a server and without depending on ``ENVIRONMENT=production``
disabling ``/api/openapi.json``.

Usage::

    python scripts/dump_openapi.py            # write the snapshot
    python scripts/dump_openapi.py --check    # exit 1 if the snapshot is stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT = REPO_ROOT / "frontend" / "openapi.json"


def render_openapi() -> str:
    """Return the current application schema as deterministic JSON text."""
    from app.main import create_app

    schema = create_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="snapshot path (default: frontend/openapi.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; fail if the snapshot differs from the app schema",
    )
    args = parser.parse_args(argv)

    rendered = render_openapi()

    if args.check:
        current = (
            args.output.read_text(encoding="utf-8") if args.output.exists() else None
        )
        if current != rendered:
            print(
                f"{args.output} is stale; run `python scripts/dump_openapi.py`",
                file=sys.stderr,
            )
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
