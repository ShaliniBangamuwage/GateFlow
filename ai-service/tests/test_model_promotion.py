import pandas as pd
import pytest

from app.ml.anomaly import save_model, train_detector
from app.ml.synthetic import generate_synthetic_dataset
from scripts.promote_model import main


def test_promotion_requires_explicit_replace_for_existing_active_model(
    tmp_path, monkeypatch
) -> None:
    rows = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=53, samples_per_scenario=8)
    )
    normal = rows.loc[(rows["scenario"] == "NORMAL") & (rows["split"] == "train")]
    candidate = train_detector(normal, model_version="candidate-v1")
    candidate_path = save_model(candidate, tmp_path / "candidate")
    active_path = tmp_path / "active"
    save_model(candidate, active_path)
    monkeypatch.setattr(
        "sys.argv",
        ["promote_model", str(candidate_path), "--active", str(active_path)],
    )

    with pytest.raises(SystemExit, match="pass --replace"):
        main()


def test_promotion_preserves_previous_active_as_backup(tmp_path, monkeypatch) -> None:
    rows = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=59, samples_per_scenario=8)
    )
    normal = rows.loc[(rows["scenario"] == "NORMAL") & (rows["split"] == "train")]
    first = train_detector(normal, model_version="first-v1")
    second = train_detector(normal, model_version="second-v1")
    first_path = save_model(first, tmp_path / "first")
    second_path = save_model(second, tmp_path / "second")
    active_path = tmp_path / "active"
    save_model(first, active_path)
    monkeypatch.setattr(
        "sys.argv",
        ["promote_model", str(second_path), "--active", str(active_path), "--replace"],
    )

    main()

    assert (tmp_path / "active.backup" / "metadata.json").is_file()
    assert (tmp_path / "active" / "metadata.json").is_file()