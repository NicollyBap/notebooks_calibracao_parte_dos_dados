"""Growth and treatment models used by the local tumor fitting tool."""
from __future__ import annotations

from typing import Iterable
import numpy as np
from scipy.integrate import solve_ivp

GROWTH_LAWS = ("exponential", "mendelsohn", "logistic", "bertalanffy", "gompertz", "linear", "surface")
TREATMENT_LAWS = (
    "none", "ED", "CD", "AccelED", "MM", "LS", "dePR",
    "T_hill", "T_expon", "T_pulso", "T_rampa", "T_hill_sat",
)


def growth_term(volume: float, params: dict[str, float], model: str) -> float:
    t = max(float(volume), 1e-12)
    r = float(params.get("r", 0.0))
    if model == "exponential":
        return r * t
    if model == "mendelsohn":
        return r * t ** float(params.get("b", 0.7))
    if model == "logistic":
        return r * t * (1.0 - t / max(float(params.get("K", 1.0)), 1e-12))
    if model == "bertalanffy":
        return r * t ** (2.0 / 3.0) - float(params.get("alpha", 0.1)) * t
    if model == "gompertz":
        capacity = max(float(params.get("K", 1.0)), t + 1e-9)
        return r * t * np.log(capacity / (t + max(float(params.get("c", 0.01)), 1e-12)))
    if model == "linear":
        return r * t / (t + max(float(params.get("f", 1.0)), 1e-12))
    if model == "surface":
        return r * t / max((t + float(params.get("f", 1.0))) ** (1.0 / 3.0), 1e-12)
    raise ValueError(f"Unknown growth model: {model}")


def treatment_effect(time: float, volume: float, doses: Iterable[tuple[float, float]], params: dict[str, float], model: str) -> float:
    if model == "none":
        return 0.0
    dose_list = [(float(dose_time), max(float(dose), 0.0)) for dose_time, dose in doses]
    if model in {"T_hill", "T_expon", "T_pulso", "T_rampa", "T_hill_sat"}:
        if not dose_list:
            return 0.0
        elapsed = max(float(time) - min(dose_time for dose_time, _ in dose_list), 0.0)
        hill = 0.0
        if elapsed > 0.0:
            tau = max(float(params.get("tau", 1.0)), 1e-12)
            exponent = max(float(params.get("n", 1.0)), 1e-12)
            elapsed_power = elapsed ** exponent
            hill = elapsed_power / (tau ** exponent + elapsed_power)
        if model == "T_hill":
            return max(float(params.get("dmax", 0.0)) * hill, 0.0)
        if model == "T_expon":
            rate = max(float(params.get("lam", 0.0)), 0.0)
            return max(float(params.get("dmax", 0.0)) * -np.expm1(-rate * elapsed), 0.0)
        if model == "T_pulso":
            tau = max(float(params.get("tau", 1.0)), 1e-12)
            return max(float(params.get("k", 0.0)) * elapsed * np.exp(-elapsed / tau), 0.0)
        if model == "T_rampa":
            return max(float(params.get("a", 0.0)) * elapsed, 0.0)
        capacity = max(float(params.get("h", 1.0)), 1e-12)
        return max(float(params.get("dmax", 0.0)) * hill / (capacity + max(float(volume), 1e-12)), 0.0)
    a = float(params.get("a", 0.2))
    b = float(params.get("b", 0.1))
    total = 0.0
    cumulative = 0.0
    for dose_time, dose in dose_list:
        if time < dose_time:
            continue
        delta = max(float(time) - float(dose_time), 0.0)
        cumulative += dose
        if model == "ED":
            total += a * dose * np.exp(-b * delta)
        elif model == "CD":
            total += a * cumulative * np.exp(-b * delta)
        elif model == "AccelED":
            total += a * dose * np.exp(-b * delta * delta)
        elif model == "MM":
            total += a * dose / (1.0 + b * dose)
        elif model == "LS":
            total += a * dose / (1.0 + b * max(volume, 0.0))
        elif model == "dePR":
            delta_param = float(params.get("delta", 0.5))
            lam = float(params.get("lambda", 1.0))
            scale = max(float(params.get("s", 1.0)), 1e-12)
            total += delta_param * dose ** lam / (scale * max(volume, 1e-12) ** lam + dose ** lam)
        else:
            raise ValueError(f"Unknown treatment model: {model}")
    return max(total, 0.0)


def simulate(times: Iterable[float], initial_volume: float, growth_model: str, growth_params: dict[str, float], treatment_model: str = "none", treatment_params: dict[str, float] | None = None, doses: Iterable[tuple[float, float]] = ()) -> np.ndarray:
    grid = np.asarray(list(times), dtype=float)
    if grid.ndim != 1 or len(grid) < 2 or np.any(np.diff(grid) <= 0):
        raise ValueError("times must contain at least two strictly increasing values")
    treatment_params = treatment_params or {}
    dose_list = [(float(day), float(dose)) for day, dose in doses]

    def rhs(time: float, state: np.ndarray) -> list[float]:
        volume = max(float(state[0]), 1e-9)
        return [growth_term(volume, growth_params, growth_model) - treatment_effect(time, volume, dose_list, treatment_params, treatment_model) * volume]

    if treatment_model == "none" and growth_model == "exponential":
        exponent = np.clip(float(growth_params.get("r", 0.0)) * (grid - grid[0]), -700.0, 700.0)
        return np.nan_to_num(float(initial_volume) * np.exp(exponent), nan=1e300, posinf=1e300, neginf=0.0)
    if treatment_model == "none":
        result = solve_ivp(rhs, (float(grid[0]), float(grid[-1])), [max(float(initial_volume), 1e-9)], t_eval=grid, method="RK45", max_step=np.inf)
        if not result.success or result.y.shape[1] != len(grid):
            raise RuntimeError(result.message)
        return np.maximum(result.y[0], 0.0)

    # Treatment rates jump when a dose is administered. Integrating through a
    # jump in one RK45 call makes the result depend on the output grid and can
    # noticeably drift from the notebook reference. Restart at every dose
    # boundary so each solver call sees a continuous right-hand side.
    boundaries = sorted({day for day, _ in dose_list if grid[0] < day < grid[-1]})
    segments = [grid[0], *boundaries, grid[-1]]
    values = np.empty_like(grid)
    state = np.array([max(float(initial_volume), 1e-9)])

    for start, end in zip(segments[:-1], segments[1:]):
        mask = (grid >= start) & (grid <= end)
        segment_grid = grid[mask]
        if len(segment_grid) == 0 or segment_grid[0] != start:
            segment_grid = np.insert(segment_grid, 0, start)
        if segment_grid[-1] != end:
            segment_grid = np.append(segment_grid, end)
        result = solve_ivp(
            rhs,
            (float(start), float(end)),
            state,
            t_eval=segment_grid,
            method="RK45",
            rtol=1e-6,
            atol=1e-8,
        )
        if not result.success or result.y.shape[1] != len(segment_grid):
            raise RuntimeError(result.message)
        output_mask = (grid >= start) & (grid <= end)
        values[output_mask] = np.interp(grid[output_mask], segment_grid, result.y[0])
        state = result.y[:, -1]

    return np.maximum(values, 0.0)
