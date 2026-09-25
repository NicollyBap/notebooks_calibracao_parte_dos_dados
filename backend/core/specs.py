"""Parameter specifications and T0 strategies."""
from __future__ import annotations
from dataclasses import dataclass

from .models import TREATMENT_LAWS

@dataclass(frozen=True)
class TreatmentSpec:
    names: tuple[str, ...]
    x0: tuple[float, ...]
    bounds: tuple[tuple[float, float], ...]

TREATMENT_SPECS = {
    "none": TreatmentSpec((), (), ()),
    "ED": TreatmentSpec(("a", "b"), (0.2, 0.1), ((1e-6, 10.0), (1e-6, 10.0))),
    "CD": TreatmentSpec(("a", "b"), (0.1, 0.1), ((1e-6, 10.0), (1e-6, 10.0))),
    "AccelED": TreatmentSpec(("a", "b"), (0.2, 0.05), ((1e-6, 10.0), (1e-6, 10.0))),
    "MM": TreatmentSpec(("a", "b"), (0.2, 0.1), ((1e-6, 10.0), (1e-6, 10.0))),
    "LS": TreatmentSpec(("a", "b"), (0.2, 0.1), ((1e-6, 10.0), (1e-6, 10.0))),
    "dePR": TreatmentSpec(("delta", "s", "lambda"), (0.5, 1.0, 1.0), ((1e-6, 10.0), (1e-6, 100.0), (0.1, 4.0))),
}

def get_treatment_spec(model: str) -> TreatmentSpec:
    if model not in TREATMENT_SPECS:
        raise ValueError(f"Unknown treatment model: {model}")
    return TREATMENT_SPECS[model]

def get_t0_bounds(datasets, strategy: str = "free", low_fraction: float = 0.10, high_fraction: float = 4.0):
    guesses, bounds = [], []
    for dataset in datasets:
        first = float(dataset.volume[0])
        if strategy == "fixed_first_obs":
            guesses.append(first); bounds.append((first, first))
        elif strategy == "narrow_first_obs":
            guesses.append(first); bounds.append((0.9 * first, 1.1 * first))
        else:
            guesses.append(first); bounds.append((max(1e-6, low_fraction * first), max(first * 1.01, high_fraction * first)))
    return guesses, bounds

def is_near_bound(value: float, bound: tuple[float, float], rel_tol: float = 1e-3) -> bool:
    scale = max(abs(bound[1] - bound[0]), 1e-12)
    return abs(value - bound[0]) <= rel_tol * scale or abs(value - bound[1]) <= rel_tol * scale
