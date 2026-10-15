import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp

from backend.core.fitting import Dataset, calibrate, calibrate_global, default_workers, run_parallel
from backend.core.io_data import harmonise_headers, infer_groups_from_files, normalise_table_report, read_table
from backend.core.models import TREATMENT_LAWS, simulate, treatment_effect
from backend.core.specs import get_treatment_spec


def test_exponential_simulation_is_positive():
    values = simulate([0, 1, 2], 1.0, "exponential", {"r": 0.2})
    assert np.all(values > 0)
    assert values[-1] > values[0]


def test_treatment_simulation_matches_reference_across_dose_boundary():
    times = np.linspace(0, 40, 300)
    growth_params = {"r": 2.49815, "f": 14.2442}
    treatment_params = {"a": 0.2, "b": 1.5}
    dose_times = [12.0]
    doses = [1.0]

    def treatment_rate(time, volume):
        if time < dose_times[0]:
            return 0.0
        return treatment_params["a"] * doses[0] * np.exp(-treatment_params["b"] * (time - dose_times[0]))

    def rhs(time, state):
        volume = max(float(state[0]), 1e-9)
        growth = growth_params["r"] * volume / (volume + growth_params["f"])
        return [growth - treatment_rate(time, volume) * volume]

    reference = solve_ivp(
        rhs,
        (times[0], times[-1]),
        [0.8],
        t_eval=times,
        method="LSODA",
        rtol=1e-6,
        atol=1e-8,
    ).y[0]
    actual = simulate(times, 0.8, "linear", growth_params, "ED", treatment_params, zip(dose_times, doses))

    assert np.max(np.abs(actual - reference)) < 1e-3


def test_appendix_treatment_equations_match_the_notebook():
    doses = [(10.0, 1.0)]
    assert treatment_effect(20, 10, doses, {"dmax": 0.4, "tau": 10, "n": 2}, "T_hill") == 0.2
    assert np.isclose(treatment_effect(20, 10, doses, {"dmax": 0.4, "lam": np.log(2) / 10}, "T_expon"), 0.2)
    assert np.isclose(treatment_effect(20, 10, doses, {"k": 0.1, "tau": 10}, "T_pulso"), 1 / np.e)
    assert treatment_effect(20, 10, doses, {"a": 0.1}, "T_rampa") == 1.0
    assert treatment_effect(20, 10, doses, {"dmax": 40, "tau": 10, "n": 2, "h": 10}, "T_hill_sat") == 1.0
    assert all(treatment_effect(10, 10, doses, {"dmax": 1, "tau": 10, "n": 2, "lam": 0.1, "k": 0.1, "a": 0.1, "h": 10}, model) == 0 for model in TREATMENT_LAWS[-5:])


def test_appendix_treatment_specs_use_the_selected_growth_rate():
    hill = get_treatment_spec("T_hill", {"r": 0.2})
    assert hill.names == ("dmax", "tau", "n")
    assert hill.bounds[0] == (0.2, 2.0)
    assert get_treatment_spec("T_expon", {"r": 0.2}).bounds[0] == (0.2, 10.0)
    assert get_treatment_spec("T_pulso").names == ("k", "tau")
    assert get_treatment_spec("T_rampa").names == ("a",)
    assert get_treatment_spec("T_hill_sat").names == ("dmax", "tau", "n", "h")


def test_calibration_returns_ranked_models():
    time = np.linspace(0, 10, 11)
    volume = 0.7 * np.exp(0.08 * time)
    datasets = [Dataset("m1", "control", time, volume), Dataset("m2", "control", time, volume * 1.1)]
    result = calibrate(datasets, ["exponential", "logistic"], starts=1)
    assert result["winner"] == "exponential"
    assert result["ranking"][0]["delta_bic"] == 0


def _series(header_x: str = "x") -> pd.DataFrame:
    return pd.DataFrame({header_x: [0, 3, 6, 9, 12, 15], "y": [0.5, 0.7, 1.0, 1.4, 2.0, 2.8]})


def test_read_table_strips_spaces_in_headers():
    frame = read_table("a.csv", b"x, y\n1, 2\n2, 3\n")
    assert list(frame.columns) == ["x", "y"]


def test_headers_that_differ_only_by_case_are_unified():
    frames, warnings = harmonise_headers([_series("x"), _series("X")], ["a.csv", "b.csv"])
    assert [list(frame.columns) for frame in frames] == [["x", "y"], ["x", "y"]]
    assert warnings == []


def test_every_uploaded_file_becomes_a_subject_even_if_one_header_uses_capital_x():
    # Regression: CTRL_5 had "X, y" while the other files had "x, y"; its time column
    # was silently lost and the subject was dropped with "0 valid points".
    frames, _ = harmonise_headers([_series("x") if index != 5 else _series("X") for index in range(1, 7)], [f"CTRL_{index}.csv" for index in range(1, 7)])
    merged = pd.concat([frame.assign(__source_file=f"fig_NOG_CTRL_{index}.csv") for index, frame in enumerate(frames, start=1)], ignore_index=True)
    datasets, validation = normalise_table_report(merged, {"time": "x", "volume": "y", "subject": None, "group": None})
    assert len(datasets) == 6
    assert all(item["ok"] for item in validation)


def test_columns_that_still_differ_produce_a_warning():
    other = pd.DataFrame({"time": [0, 1], "volume": [1.0, 2.0]})
    _, warnings = harmonise_headers([_series("x"), other], ["a.csv", "b.csv"])
    assert len(warnings) == 1 and "b.csv" in warnings[0]


def test_groups_are_inferred_from_file_names_when_controls_are_present():
    names = ["fig_NOG_CTRL_1.csv", "fig_NOG_CTRL_2.csv", "fig_hIL2_NOG_CART_1.csv", "fig_hIL2_NOG_CART_2.csv"]
    groups = infer_groups_from_files(names, "control")
    assert groups["fig_NOG_CTRL_1.csv"] == groups["fig_NOG_CTRL_2.csv"] == "control"
    assert groups["fig_hIL2_NOG_CART_1.csv"] == groups["fig_hIL2_NOG_CART_2.csv"] == "hIL2_NOG_CART"


def test_no_group_inference_when_no_file_looks_like_a_control():
    groups = infer_groups_from_files(["mouse_1.csv", "mouse_2.csv"], "control")
    assert set(groups.values()) == {"control"}


def _synthetic_subjects() -> list[Dataset]:
    rng = np.random.default_rng(7)
    times = np.arange(0, 30, 3.0)
    subjects = []
    for index, start in enumerate((0.5, 0.8, 1.2), start=1):
        volume = 50 / (1 + (50 / start - 1) * np.exp(-0.25 * times)) * (1 + 0.03 * rng.standard_normal(len(times)))
        subjects.append(Dataset(f"s{index}", "control", times, volume))
    return subjects


# BIC values produced by the ORIGINAL (unoptimised, sequential) code on the data above.
# If an optimisation changes these numbers, it changed the science: investigate before updating.
# The order matters: each law gets the seed `seed + its position in the list`.
REFERENCE_BIC = {"logistic": 77.221369, "exponential": 208.232263, "gompertz": 86.203536}


def test_calibration_matches_reference_values_from_the_original_code():
    result = calibrate_global(_synthetic_subjects(), list(REFERENCE_BIC), starts=2, seed=42)
    assert result["winner"] == "logistic"
    for row in result["ranking"]:
        assert abs(row["metrics"]["bic"] - REFERENCE_BIC[row["model"]]) < 1e-5


def test_parallel_calibration_gives_exactly_the_sequential_numbers():
    models = ["logistic", "exponential"]
    sequential = calibrate_global(_synthetic_subjects(), models, starts=1, seed=42, workers=1)
    parallel = calibrate_global(_synthetic_subjects(), models, starts=1, seed=42, workers=2)
    assert [r["model"] for r in parallel["ranking"]] == [r["model"] for r in sequential["ranking"]]
    for a, b in zip(sequential["ranking"], parallel["ranking"]):
        assert a["params"] == b["params"] and a["T0"] == b["T0"] and a["metrics"] == b["metrics"]


def test_parallel_run_can_be_cancelled_and_reports_progress():
    ticks = []

    def on_progress(stage, step, n_steps):
        ticks.append(step)
        if len(ticks) >= 2:
            raise RuntimeError("cancelled")

    try:
        calibrate_global(_synthetic_subjects(), ["logistic", "gompertz", "exponential"], starts=3, workers=3, on_progress=on_progress)
    except RuntimeError as error:
        assert str(error) == "cancelled"
    else:
        raise AssertionError("the cancellation was not propagated")


def test_falls_back_to_sequential_when_processes_are_unavailable(monkeypatch):
    import multiprocessing

    def broken(*args, **kwargs):
        raise OSError("processes are not available")

    monkeypatch.setattr(multiprocessing, "get_context", broken)
    assert run_parallel(len, [[1], [2]], workers=2) is None
    result = calibrate_global(_synthetic_subjects(), ["logistic", "exponential"], starts=1, workers=4)
    assert result["winner"] == "logistic"


def test_worker_count_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("TUMOR_FIT_WORKERS", "3")
    assert default_workers() == 3
    monkeypatch.setenv("TUMOR_FIT_WORKERS", "not a number")
    assert 1 <= default_workers() <= 8
