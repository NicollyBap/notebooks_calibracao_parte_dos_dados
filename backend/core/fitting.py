"""Small, deterministic fitting helpers for the first working version."""
from __future__ import annotations

from dataclasses import dataclass
import os
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

    # Per-subject cache of the residuals. L-BFGS-B estimates gradients by nudging one
    # variable at a time, and nudging a subject's T0 only changes that subject's curve:
    # the other curves are looked up instead of being re-integrated. The same inputs give
    # the same floats, so results are bit-for-bit identical to the uncached computation.
    n_shared = len(parameter_bounds)
    caches: list[dict] = [{} for _ in datasets]
    failed = object()

    def subject_errors(index: int, shared_key: tuple, params: dict, t0: float):
        key = (shared_key, float(t0))
        cached = caches[index].get(key)
        if cached is None:
            try:
                cached = simulate(datasets[index].time, t0, model, params) - datasets[index].volume
            except Exception:
                cached = failed
            if len(caches[index]) >= 20000:
                caches[index].clear()
            caches[index][key] = cached
        return cached

    def objective(values):
        params, t0_values = unpack(values)
        if any(t0 <= 0 for t0 in t0_values):
            return 1e18
        shared_key = tuple(values[:n_shared].tolist())
        errors = []
        for index, t0 in enumerate(t0_values):
            cached = subject_errors(index, shared_key, params, t0)
            if cached is failed:
                return 1e18
            errors.append(cached)
        try:
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


def calibrate_global(datasets: list[Dataset], models: list[str] | None = None, starts: int = 3, seed: int = 42, t0_strategy: str = "free", count_t0_in_ic: bool = True, on_progress: Callable[[str, int, int], None] | None = None, maxiter: int = 250, selection_metric: str = "bic", workers: int = 1) -> dict:
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
        raise ValueError("The selection criterion must be bic or aicc")
    results = None
    if workers > 1 and len(selected) > 1:
        def on_tick(done: int, total: int) -> None:
            if on_progress is not None:
                on_progress(f"fitted {done}/{total} laws on {min(workers, total)} CPU cores", done * n_starts, n_steps)
        tasks = [(datasets, model, starts, seed + index, t0_strategy, count_t0_in_ic, maxiter) for index, model in enumerate(selected)]
        results = run_parallel(_fit_one, tasks, workers, on_tick)
    if results is None:
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


# --------------------------------------------------------------------------------------
# Parallel execution (one process per law). Each law is fitted with its own seed
# (seed + index), exactly as in the sequential loop, so the numbers are identical;
# only the wall-clock time changes.
# --------------------------------------------------------------------------------------
def default_workers() -> int:
    """Processes to use: all cores but one (at most 8). Override with TUMOR_FIT_WORKERS."""
    value = os.environ.get("TUMOR_FIT_WORKERS", "")
    if value.isdigit() and int(value) >= 1:
        return int(value)
    return max(1, min((os.cpu_count() or 1) - 1, 8))


def _fit_one(task: tuple) -> dict:
    datasets, model, starts, seed, t0_strategy, count_t0_in_ic, maxiter = task
    return fit_global_model(datasets, model, starts, seed, t0_strategy, count_t0_in_ic, maxiter=maxiter)


def _validate_one(task: tuple) -> dict:
    datasets, model, starts, seed, t0_strategy = task
    return evaluate_last_point_validation(datasets, model, starts, seed, t0_strategy)


def run_parallel(function: Callable, tasks: list, workers: int, on_tick: Callable[[int, int], None] | None = None) -> list | None:
    """Run `function(task)` for every task in separate processes and return results in task order.

    `on_tick(done, total)` is called about every half second and after each completion; it may
    raise (for example to cancel), in which case the worker processes are stopped.
    Returns None when processes cannot be used on this machine, so the caller can fall back to
    the sequential path. Errors raised by `function` itself are propagated unchanged.
    """
    import multiprocessing
    import pickle
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
    from concurrent.futures.process import BrokenProcessPool

    n_workers = min(workers, len(tasks))
    if n_workers < 2:
        return None
    try:
        executor = ProcessPoolExecutor(max_workers=n_workers, mp_context=multiprocessing.get_context("spawn"))
        futures = {executor.submit(function, task): index for index, task in enumerate(tasks)}
    except (OSError, ValueError, NotImplementedError, RuntimeError):
        return None
    results: list = [None] * len(tasks)
    pending = set(futures)
    done_count = 0
    try:
        if on_tick is not None:
            on_tick(0, len(tasks))
        while pending:
            finished, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in finished:
                results[futures[future]] = future.result()
                done_count += 1
            if on_tick is not None:
                on_tick(done_count, len(tasks))
    except (BrokenProcessPool, OSError, pickle.PicklingError):
        _stop_executor(executor)
        return None
    except BaseException:
        _stop_executor(executor)
        raise
    executor.shutdown()
    return results


def _stop_executor(executor) -> None:
    # Grab the worker processes first: shutdown() clears the executor's own list of them.
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        try:
            process.terminate()
        except Exception:
            pass


def evaluate_last_point_validations(datasets: list[Dataset], models: list[str], starts: int = 2, seed: int = 42, t0_strategy: str = "free", workers: int = 1, on_tick: Callable[[int, int], None] | None = None) -> list[dict]:
    """`evaluate_last_point_validation` for several laws, in parallel when `workers` > 1."""
    tasks = [(datasets, model, starts, seed, t0_strategy) for model in models]
    parallel = run_parallel(_validate_one, tasks, workers, on_tick) if workers > 1 and len(tasks) > 1 else None
    if parallel is not None:
        return parallel
    results = []
    for index, task in enumerate(tasks):
        if on_tick is not None:
            on_tick(index, len(tasks))
        results.append(_validate_one(task))
    return results
