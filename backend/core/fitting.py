"""Small, deterministic fitting helpers for the first working version."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import numpy as np
from scipy.optimize import minimize

from .models import GROWTH_LAWS, simulate
from .metrics import metrics_from_predictions
from .specs import get_t0_bounds, is_near_bound

PARAMETERS = {
    "exponential": ("r",), "mendelsohn": ("r", "b"), "logistic": ("r", "K"),
    "bertalanffy": ("r", "alpha"), "gompertz": ("r", "K", "c"),
    "linear": ("r", "f"), "surface": ("r", "f"),
}
BOUNDS = {
    "exponential": ((0.0001, 2.0),), "mendelsohn": ((0.0001, 2.0), (0.1, 2.0)),
    "logistic": ((0.0001, 2.0), (0.01, 10000.0)), "bertalanffy": ((0.0001, 2.0), (0.0001, 2.0)),
    "gompertz": ((0.0001, 2.0), (0.01, 10000.0), (0.00001, 10.0)),
    "linear": ((0.0001, 100.0), (0.001, 1000.0)), "surface": ((0.0001, 20.0), (0.001, 1000.0)),
}

@dataclass
class Dataset:
    subject: str
    group: str
    time: np.ndarray
    volume: np.ndarray


def _params(model: str, values: np.ndarray) -> dict[str, float]:
    return dict(zip(PARAMETERS[model], map(float, values)))


def fit_model(datasets: list[Dataset], model: str, starts: int = 3, seed: int = 42) -> dict:
    if model not in GROWTH_LAWS:
        raise ValueError(f"Unknown growth model: {model}")
    rng = np.random.default_rng(seed)
    bounds = BOUNDS[model]
    lower = np.array([item[0] for item in bounds], dtype=float)
    upper = np.array([item[1] for item in bounds], dtype=float)
    best = None

    def objective(values: np.ndarray) -> float:
        params = _params(model, values)
        error = 0.0
        for dataset in datasets:
            try:
                prediction = simulate(dataset.time, dataset.volume[0], model, params)
                error += float(np.mean((prediction - dataset.volume) ** 2))
            except Exception:
                return 1e18
        return error / max(len(datasets), 1)

    for start_index in range(max(1, starts)):
        initial = lower + (upper - lower) * (0.5 if start_index == 0 else rng.random(len(bounds)))
        result = minimize(objective, initial, method="L-BFGS-B", bounds=bounds, options={"maxiter": 250})
        if best is None or result.fun < best.fun:
            best = result
    assert best is not None
    params = _params(model, best.x)
    curves = []
    residuals = []
    n_obs = 0
    for dataset in datasets:
        prediction = simulate(dataset.time, dataset.volume[0], model, params)
        curves.append({"subject": dataset.subject, "group": dataset.group, "t": dataset.time.tolist(), "observed": dataset.volume.tolist(), "fitted": prediction.tolist()})
        residuals.extend((dataset.volume - prediction).tolist())
        n_obs += len(dataset.time)
    sse = float(np.sum(np.square(residuals)))
    k = len(bounds)
    bic = float(n_obs * np.log(max(sse / max(n_obs, 1), 1e-12)) + k * np.log(max(n_obs, 1)))
    return {"model": model, "params": params, "sse": sse, "bic": bic, "rmse": float(np.sqrt(sse / max(n_obs, 1))), "curves": curves, "converged": bool(best.success)}


def calibrate(datasets: list[Dataset], models: list[str] | None = None, starts: int = 3, seed: int = 42) -> dict:
    selected = models or list(GROWTH_LAWS)
    results = [fit_model(datasets, model, starts=starts, seed=seed + index) for index, model in enumerate(selected)]
    results.sort(key=lambda item: item["bic"])
    winner_bic = results[0]["bic"]
    for result in results:
        result["delta_bic"] = float(result["bic"] - winner_bic)
        result["tie"] = result["delta_bic"] < 2.0
    weights = np.exp(-0.5 * np.array([r["delta_bic"] for r in results]))
    weights /= max(float(weights.sum()), 1e-12)
    for result, weight in zip(results, weights):
        result["akaike_weight"] = float(weight)
    return {"winner": results[0]["model"], "tie_with": [r["model"] for r in results[1:] if r["tie"]], "ranking": results}


def fit_global_model(datasets: list[Dataset], model: str, starts: int = 3, seed: int = 42, t0_strategy: str = "free", count_t0_in_ic: bool = True, on_start: Callable[[int, int], None] | None = None, maxiter: int = 250) -> dict:
    """Fit shared growth parameters plus one T0 per subject.

    `on_start(start_index, n_starts)` is called (1-indexed) before each
    multistart attempt, so a caller can report progress per (law, start).
    """
    if model not in GROWTH_LAWS:
        raise ValueError(f"Unknown growth model: {model}")
    rng = np.random.default_rng(seed)
    parameter_bounds = BOUNDS[model]
    guesses, t0_bounds = get_t0_bounds(datasets, t0_strategy)
    lower = np.asarray([bound[0] for bound in parameter_bounds] + [bound[0] for bound in t0_bounds], float)
    upper = np.asarray([bound[1] for bound in parameter_bounds] + [bound[1] for bound in t0_bounds], float)

    def unpack(values):
        return _params(model, values[:len(parameter_bounds)]), values[len(parameter_bounds):]

    def objective(values):
        params, t0_values = unpack(values)
        if any(t0 <= 0 for t0 in t0_values):
            return 1e18
        try:
            errors = [simulate(dataset.time, t0, model, params) - dataset.volume for dataset, t0 in zip(datasets, t0_values)]
            return float(np.mean(np.concatenate(errors) ** 2))
        except Exception:
            return 1e18

    base = np.asarray([item[0] for item in parameter_bounds] + guesses, float)
    best = None
    n_starts = max(1, starts)
    for index in range(n_starts):
        if on_start is not None:
            on_start(index + 1, n_starts)
        initial = base if index == 0 else lower + (upper - lower) * rng.random(len(lower))
        result = minimize(objective, initial, method="L-BFGS-B", bounds=list(parameter_bounds) + t0_bounds, options={"maxiter": maxiter})
        if best is None or result.fun < best.fun:
            best = result
    assert best is not None
    params, t0_values = unpack(best.x)
    predictions = [simulate(dataset.time, t0, model, params) for dataset, t0 in zip(datasets, t0_values)]
    observed = np.concatenate([dataset.volume for dataset in datasets])
    fitted = np.concatenate(predictions)
    if not np.all(np.isfinite(fitted)):
        raise RuntimeError(f"Model {model} produced non-finite values")
    k_total = len(parameter_bounds) + (len(datasets) if count_t0_in_ic else 0)
    metrics = metrics_from_predictions(observed, fitted, k_total)
    diagnostics = [f"T0_{index} at bound [{bound[0]:.4g}, {bound[1]:.4g}]" for index, (value, bound) in enumerate(zip(t0_values, t0_bounds), start=1) if is_near_bound(value, bound)]
    curves = [{"subject": dataset.subject, "group": dataset.group, "t": dataset.time.tolist(), "observed": dataset.volume.tolist(), "fitted": prediction.tolist(), "T0": float(t0)} for dataset, prediction, t0 in zip(datasets, predictions, t0_values)]
    return {"model": model, "params": params, "T0": [float(value) for value in t0_values], "metrics": metrics, "bic": metrics["bic"], "rmse": metrics["rmse"], "curves": curves, "diagnostics": diagnostics, "converged": bool(best.success)}


def calibrate_global(datasets: list[Dataset], models: list[str] | None = None, starts: int = 3, seed: int = 42, t0_strategy: str = "free", count_t0_in_ic: bool = True, on_progress: Callable[[str, int, int], None] | None = None, maxiter: int = 250, selection_metric: str = "bic") -> dict:
    """Fit every requested law and rank them.

    `on_progress(stage_text, step, n_steps)` is called before each
    (law, start) attempt across the whole run, so a job queue can show one
    combined progress bar instead of restarting it per law.
    """
    selected = models or list(GROWTH_LAWS)
    n_starts = max(1, starts)
    n_steps = len(selected) * n_starts
    progress_state = {"step": 0}

    def make_on_start(model: str):
        def on_start(start_index: int, starts_total: int) -> None:
            progress_state["step"] += 1
            if on_progress is not None:
                on_progress(f"fitting {model} (start {start_index}/{starts_total})", progress_state["step"], n_steps)
        return on_start

    if selection_metric not in {"bic", "aicc"}:
        raise ValueError("Le critere doit etre bic ou aicc")
    results = [
        fit_global_model(datasets, model, starts, seed + index, t0_strategy, count_t0_in_ic, on_start=make_on_start(model), maxiter=maxiter)
        for index, model in enumerate(selected)
    ]
    results.sort(key=lambda result: result["metrics"][selection_metric])
    best_metric = results[0]["metrics"][selection_metric]
    best_bic = results[0]["metrics"]["bic"]
    weights = np.exp(-0.5 * np.asarray([result["metrics"]["bic"] - best_bic for result in results]))
    weights /= max(float(weights.sum()), 1e-12)
    for result, weight in zip(results, weights):
        result["delta_bic"] = float(result["metrics"]["bic"] - best_bic); result["delta_selection"] = float(result["metrics"][selection_metric] - best_metric); result["tie"] = result["delta_selection"] < 2; result["akaike_weight"] = float(weight)
    return {"winner": results[0]["model"], "tie_with": [result["model"] for result in results[1:] if result["tie"]], "ranking": results, "t0_strategy": t0_strategy, "selection_metric": selection_metric}


def evaluate_last_point_validation(datasets: list[Dataset], model: str, starts: int = 2, seed: int = 42, t0_strategy: str = "free") -> dict:
    """Hide the last observation of every subject, refit, and score predictions."""
    if any(len(dataset.time) < 5 for dataset in datasets):
        return {"enabled": False, "reason": "at least 5 points per subject are required"}
    training = [Dataset(dataset.subject, dataset.group, dataset.time[:-1], dataset.volume[:-1]) for dataset in datasets]
    fitted = fit_global_model(training, model, starts, seed, t0_strategy)
    errors = []
    predictions = []
    for dataset, t0 in zip(datasets, fitted["T0"]):
        prediction = simulate(np.asarray([dataset.time[0], dataset.time[-1]]), t0, model, fitted["params"])[-1]
        predictions.append(float(prediction)); errors.append(float(dataset.volume[-1]))
    errors_array = np.asarray(errors) - np.asarray(predictions)
    return {"enabled": True, "mae": float(np.mean(np.abs(errors_array))), "rmse": float(np.sqrt(np.mean(errors_array ** 2))), "mape": float(100 * np.mean(np.abs(errors_array) / np.maximum(np.abs(errors), 1e-12))), "observed": errors, "predicted": predictions}
