import json

import pandas as pd
import pytest

from app.ml.anomaly import load_model, save_model, train_detector
from app.ml.evaluation import evaluate_detector
from app.ml.schema import MODEL_FEATURES
from app.ml.synthetic import generate_synthetic_dataset
from scripts.train_anomaly import train_and_compare


def test_model_uses_fixed_numeric_schema_and_returns_uncalibrated_scores() -> None:
    dataset = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=19, samples_per_scenario=20)
    )
    normal_train = dataset.loc[
        (dataset["scenario"] == "NORMAL") & (dataset["split"] == "train")
    ]
    model = train_detector(
        normal_train,
        model_version="test-iforest-v1",
    )
    anomaly = dataset.loc[dataset["scenario"] == "TRAFFIC_SPIKE"].iloc[0].to_dict()
    anomaly.update({"tenant_id": "must-not-be-used", "client_id": "id-not-a-feature"})

    result = model.predict_score([anomaly])[0]

    assert result["model_version"] == "test-iforest-v1"
    assert isinstance(result["is_anomaly"], bool)
    assert isinstance(result["score"], float)
    assert set(result["signals"]) == set(MODEL_FEATURES)
    assert "probability" not in result
    assert model.training_metadata["feature_names"] == list(MODEL_FEATURES)
    assert "scaler" in model.pipeline.named_steps


def test_artifact_round_trip_and_checksum_validation(tmp_path) -> None:
    dataset = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=23, samples_per_scenario=12)
    )
    training = dataset.loc[
        (dataset["scenario"] == "NORMAL") & (dataset["split"] == "train")
    ]
    model = train_detector(training, model_version="roundtrip-v1")
    directory = save_model(model, tmp_path / "candidate")
    restored = load_model(directory)
    row = dataset.loc[dataset["split"] == "test"].iloc[0].to_dict()

    assert restored.model_version == model.model_version
    assert restored.algorithm == "isolation_forest"
    assert restored.predict_score([row]) == model.predict_score([row])
    metadata = json.loads((directory / "metadata.json").read_text())
    assert metadata["feature_schema_version"]
    assert metadata["training_dataset"]["sample_count"] == len(training)

    with (directory / "model.joblib").open("ab") as artifact:
        artifact.write(b"tampered")
    with pytest.raises(ValueError, match="invalid or incompatible"):
        load_model(directory)


def test_evaluation_reports_confusion_matrix_and_metrics() -> None:
    dataset = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=29, samples_per_scenario=20)
    )
    training = dataset.loc[
        (dataset["scenario"] == "NORMAL") & (dataset["split"] == "train")
    ]
    evaluation = dataset.loc[dataset["split"] == "test"]
    model = train_detector(training, model_version="evaluation-v1")

    report = evaluate_detector(model, evaluation)

    assert sum(report["confusion_matrix"][0]) + sum(report["confusion_matrix"][1]) == len(evaluation)
    assert report["tp"] + report["tn"] + report["fp"] + report["fn"] == len(evaluation)
    assert 0 <= report["precision"] <= 1
    assert 0 <= report["recall"] <= 1
    assert 0 <= report["f1"] <= 1
    assert report["inference_time_ms"] >= 0
    assert "not probability" in report["score_semantics"]


def test_comparison_uses_same_heldout_set_and_only_suggests_candidate(tmp_path) -> None:
    dataset = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=31, samples_per_scenario=12)
    )

    report = train_and_compare(
        dataset,
        model_version="comparison-v1",
        output_directory=tmp_path / "candidates",
    )

    assert set(report["models"]) == {"isolation_forest", "local_outlier_factor"}
    assert report["models"]["isolation_forest"]["sample_count"] == report["models"]["local_outlier_factor"]["sample_count"]
    assert report["recommended_candidate"] in report["models"]
    assert report["promotion"] == "not performed; inspect evidence before explicit deployment"
    assert (tmp_path / "candidates" / "comparison.json").is_file()