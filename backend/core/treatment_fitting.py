"""Treatment calibration with the growth law held fixed."""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize
from .models import TREATMENT_LAWS, simulate
from .specs import get_treatment_spec
from .metrics import metrics_from_predictions


def fit_treatment(datasets, growth_model, growth_params, treatment_model, doses, starts=3, seed=42, on_progress=None, progress_state=None, n_steps=1):
    if treatment_model not in TREATMENT_LAWS:
        raise ValueError(f"Unknown treatment model: {treatment_model}")
    spec = get_treatment_spec(treatment_model)
    if not spec.names:
        predicted = [simulate(d.time, d.volume[0], growth_model, growth_params) for d in datasets]
        y = np.concatenate([d.volume for d in datasets]); yhat = np.concatenate(predicted)
        return {"model": treatment_model, "params": {}, "metrics": metrics_from_predictions(y, yhat, 0), "curves": _curves(datasets, predicted)}
    lower = np.array([bound[0] for bound in spec.bounds]); upper = np.array([bound[1] for bound in spec.bounds]); rng = np.random.default_rng(seed)
    dose_list = list(doses)
    def params(values): return dict(zip(spec.names, map(float, values)))
    def objective(values):
        try:
            return float(np.mean([np.mean((simulate(d.time, d.volume[0], growth_model, growth_params, treatment_model, params(values), dose_list) - d.volume) ** 2) for d in datasets]))
        except (RuntimeError, ValueError, FloatingPointError):
            return 1e18
    best = None
    for index in range(max(1, starts)):
        if on_progress is not None:
            progress_state["step"] += 1
            on_progress(f"fitting {treatment_model} (start {index + 1}/{max(1, starts)})", progress_state["step"], n_steps)
        initial = np.asarray(spec.x0) if index == 0 else lower + (upper - lower) * rng.random(len(spec.bounds))
        result = minimize(objective, initial, method="L-BFGS-B", bounds=spec.bounds, options={"maxiter": 250})
        if best is None or result.fun < best.fun: best = result
    estimated = params(best.x)
    predicted = [simulate(d.time, d.volume[0], growth_model, growth_params, treatment_model, estimated, dose_list) for d in datasets]
    y = np.concatenate([d.volume for d in datasets]); yhat = np.concatenate(predicted)
    return {"model": treatment_model, "params": estimated, "metrics": metrics_from_predictions(y, yhat, len(spec.names)), "curves": _curves(datasets, predicted), "converged": bool(best.success)}


def _curves(datasets, predictions):
    return [{"subject": d.subject, "group": d.group, "t": d.time.tolist(), "observed": d.volume.tolist(), "fitted": p.tolist()} for d, p in zip(datasets, predictions)]


def compare_treatments(datasets, growth_model, growth_params, doses, starts=3, seed=42, on_progress=None):
    progress_state = {"step": 0}
    n_steps = len(TREATMENT_LAWS) * max(1, starts)
    results = [fit_treatment(datasets, growth_model, growth_params, model, doses, starts, seed + index, on_progress, progress_state, n_steps) for index, model in enumerate(TREATMENT_LAWS)]
    results.sort(key=lambda result: result["metrics"]["bic"])
    winner = results[0]["metrics"]["bic"]
    for result in results:
        result["delta_bic"] = float(result["metrics"]["bic"] - winner)
        result["tie"] = result["delta_bic"] < 2
    return {"winner": results[0]["model"], "ranking": results}
