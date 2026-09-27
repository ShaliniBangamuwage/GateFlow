import pandas as pd

from app.ml.synthetic_forecast import generate_synthetic_forecast_series
from scripts import train_forecast


def test_forecast_script_measures_same_chronological_series(tmp_path, monkeypatch) -> None:
    series = generate_synthetic_forecast_series(seed=73, days=7)
    dataset = tmp_path / "series.csv"
    series.to_csv(dataset, index=False)
    output_dir = tmp_path / "artifacts"
    monkeypatch.setattr(
        "sys.argv",
        [
            "train_forecast",
            "--dataset",
            str(dataset),
            "--version",
            "forecast-script-test",
            "--output-dir",
            str(output_dir),
        ],
    )

    train_forecast.main()

    assert (output_dir / "forecast-script-test" / "forecast.joblib").is_file()
    report = pd.read_json(output_dir / "forecast-script-test-evaluation.json", typ="series")
    assert report["training_metadata"]["chronological_split"] is True
    assert report["metrics"]["5m"]["sample_count"] == report["metrics"]["15m"]["sample_count"]
