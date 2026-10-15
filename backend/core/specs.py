"""Parameter specifications and T0 strategies."""
from __future__ import annotations
from dataclasses import dataclass
import math

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

def get_treatment_spec(model: str, growth_params: dict[str, float] | None = None) -> TreatmentSpec:
    if model not in TREATMENT_SPECS:
        reference_rate = float((growth_params or {}).get("r", 0.0))
        if not reference_rate > 0.0:
            reference_rate = 0.1
        appendix_specs = {
            "T_hill": TreatmentSpec(
                ("dmax", "tau", "n"),
                (reference_rate, 25.0, 2.0),
                ((reference_rate, 10.0 * reference_rate), (5.0, 80.0), (1.0, 8.0)),
            ),
            "T_expon": TreatmentSpec(
                ("dmax", "lam"),
                (3.0 * reference_rate, 0.05),
                ((reference_rate, 50.0 * reference_rate), (0.005, 0.5)),
            ),
            "T_pulso": TreatmentSpec(
                ("k", "tau"),
                (min(max(3.0 * math.e * reference_rate / 20.0, 0.001), 0.5), 20.0),
                ((0.001, 0.5), (5.0, 60.0)),
            ),
            "T_rampa": TreatmentSpec(
                ("a",),
                (min(max(reference_rate / 30.0, 1e-4), 0.05),),
                ((1e-4, 0.05),),
            ),
            "T_hill_sat": TreatmentSpec(
                ("dmax", "tau", "n", "h"),
                (20.0, 25.0, 2.0, 20.0),
                ((1.0, 500.0), (5.0, 80.0), (1.0, 8.0), (1.0, 200.0)),
            ),
        }
        if model not in appendix_specs:
            raise ValueError(f"Unknown treatment model: {model}")
        return appendix_specs[model]
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
