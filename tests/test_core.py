import numpy as np

from backend.core.fitting import Dataset, calibrate
from backend.core.models import simulate


def test_exponential_simulation_is_positive():
    values = simulate([0, 1, 2], 1.0, "exponential", {"r": 0.2})
    assert np.all(values > 0)
    assert values[-1] > values[0]


def test_calibration_returns_ranked_models():
    time = np.linspace(0, 10, 11)
    volume = 0.7 * np.exp(0.08 * time)
    datasets = [Dataset("m1", "control", time, volume), Dataset("m2", "control", time, volume * 1.1)]
    result = calibrate(datasets, ["exponential", "logistic"], starts=1)
    assert result["winner"] == "exponential"
    assert result["ranking"][0]["delta_bic"] == 0
