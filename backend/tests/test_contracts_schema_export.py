"""Tests that every contract model exports valid, stable JSON Schema."""

import json
from pathlib import Path

from app.contracts.schema_export import CONTRACT_MODELS, export_all_schemas


def test_every_contract_model_generates_a_schema() -> None:
    for name, model in CONTRACT_MODELS.items():
        schema = model.model_json_schema()
        assert isinstance(schema, dict), f"{name} did not produce a schema dict"
        assert schema.get("title") or schema.get("$defs") is not None


def test_export_all_schemas_writes_one_file_per_model(tmp_path: Path) -> None:
    written = export_all_schemas(tmp_path)
    assert len(written) == len(CONTRACT_MODELS)
    for path in written:
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)


def test_committed_schema_files_are_up_to_date(tmp_path: Path) -> None:
    """Guards against editing a contract model without regenerating its schema file."""
    committed_dir = Path(__file__).resolve().parent.parent / "contracts" / "schemas"
    fresh = export_all_schemas(tmp_path)
    for path in fresh:
        committed_path = committed_dir / path.name
        assert committed_path.exists(), f"missing committed schema: {path.name}"
        assert committed_path.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), (
            f"{path.name} is stale; run scripts/export_contracts.py"
        )
