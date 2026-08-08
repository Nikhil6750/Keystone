"""CLI entry point: regenerate `backend/contracts/schemas/*.schema.json`.

Run from `backend/`:

    python scripts/export_contracts.py
"""

from pathlib import Path

from app.contracts.schema_export import export_all_schemas

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "contracts" / "schemas"


def main() -> None:
    written = export_all_schemas(_OUTPUT_DIR)
    for path in written:
        print(path.relative_to(_OUTPUT_DIR.parent.parent))


if __name__ == "__main__":
    main()
