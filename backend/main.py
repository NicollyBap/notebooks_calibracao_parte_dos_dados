from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core.fitting import Dataset, calibrate_global, evaluate_last_point_validation
from .core.io_data import normalise_table, normalise_table_report, read_table
from .core.models import GROWTH_LAWS, TREATMENT_LAWS, simulate
from .core.treatment_fitting import compare_treatments
from .jobs import JobCancelled, cancel as cancel_job, get as get_job, is_cancelled, result as get_job_result, submit as submit_job, update as update_job

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SESSIONS: dict[str, dict[str, Any]] = {}
SESSIONS_DIR = ROOT / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Tumor Fit Tool", version="0.1.0")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


class MappingRequest(BaseModel):
    source_id: str
    mapping: dict[str, str | None]
    control_group: str
    treated_groups: list[str] = Field(default_factory=list)
    exclude_subjects: list[str] = Field(default_factory=list)
    time_unit: str = "days"
    volume_unit: str = "mm3"


class CalibrationRequest(BaseModel):
    session_id: str
    models: list[str] = Field(default_factory=lambda: list(GROWTH_LAWS))
    starts: int = Field(default=3, ge=1, le=20)
    seed: int = 42
    t0_strategy: str = "free"
    count_t0_in_ic: bool = True
    validation_top_k: int = Field(default=3, ge=0, le=7)
    maxiter: int = Field(default=250, ge=50, le=2000)
    selection_metric: str = "bic"


class SelectModelRequest(BaseModel):
    session_id: str
    model: str


class TreatmentRequest(BaseModel):
    session_id: str
    doses: list[tuple[float, float]] = Field(default_factory=list)
    treated_group: str | None = None
    starts: int = Field(default=3, ge=1, le=20)
    seed: int = 42


class Scenario(BaseModel):
    name: str
    dose_times: list[float] = Field(default_factory=list)
    doses: list[float] = Field(default_factory=list)


class SimulationRequest(BaseModel):
    session_id: str
    treatment_model: str = "ED"
    treatment_params: dict[str, float] = Field(default_factory=lambda: {"a": 0.2, "b": 0.1})
    initial_volume: float = Field(default=0.8, gt=0)
    horizon_days: float = Field(default=60, gt=0)
    n_points: int = Field(default=240, ge=20, le=2000)
    scenarios: list[Scenario] = Field(default_factory=list)


def _guess_column(columns: list[str], words: tuple[str, ...]) -> str | None:
    lowered = {column: column.lower().replace(" ", "_") for column in columns}
    for column, value in lowered.items():
        if any(word in value for word in words):
            return column
    return None


def _read_upload(filename: str, content: bytes) -> pd.DataFrame:
    try:
        if filename.lower().endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(content))
        sample = content[:4096].decode("utf-8-sig", errors="replace")
        separator = ";" if sample.count(";") > sample.count(",") else ("\t" if sample.count("\t") > sample.count(",") else ",")
        return pd.read_csv(io.BytesIO(content), sep=separator)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read file: {exc}") from exc


def _save_session(session_id: str, session: dict[str, Any]) -> None:
    directory = SESSIONS_DIR / session_id
    directory.mkdir(exist_ok=True)
    serialisable = {key: value for key, value in session.items() if key not in {"frame", "datasets"}}
    (directory / "session.json").write_text(json.dumps(serialisable, default=str, indent=2), encoding="utf-8")


def _load_sessions() -> None:
    for directory in SESSIONS_DIR.iterdir():
        metadata = directory / "session.json"
        uploaded = directory / "uploaded.csv"
        if not directory.is_dir() or not metadata.exists() or not uploaded.exists():
            continue
        try:
            session = json.loads(metadata.read_text(encoding="utf-8"))
            session["frame"] = pd.read_csv(uploaded)
            mapping = session.get("mapping")
            if mapping:
                session["frame"] = _convert_units(session["frame"], mapping, session.get("time_unit", "days"), session.get("volume_unit", "mm3"))
                session["datasets"] = normalise_table(session["frame"], mapping, session.get("control_group", "control"), session.get("filename", "upload"))
            SESSIONS[directory.name] = session
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue


def _preview(frame: pd.DataFrame) -> dict[str, Any]:
    columns = [str(column) for column in frame.columns if not str(column).startswith("__")]
    visible = frame[columns] if columns else frame
    return {"columns": columns, "rows": visible.head(8).replace({np.nan: None}).to_dict(orient="records"), "mapping_guess": {"time": _guess_column(columns, ("day", "time", "dia", "t", "x")), "volume": _guess_column(columns, ("volume", "tumor", "tumour", "mm3", "v", "y")), "subject": _guess_column(columns, ("mouse", "subject", "animal", "id")), "group": _guess_column(columns, ("group", "arm", "treatment"))}}


def _normalise(frame: pd.DataFrame, mapping: dict[str, str | None], control_group: str, treated_groups: list[str], exclude: list[str]) -> list[Dataset]:
    time_column = mapping.get("time")
    volume_column = mapping.get("volume")
    subject_column = mapping.get("subject")
    group_column = mapping.get("group")
    if not time_column or not volume_column:
        raise HTTPException(status_code=422, detail="Les colonnes time et volume sont obligatoires")
    work = frame.copy()
    work["__time"] = pd.to_numeric(work[time_column].astype(str).str.replace(",", "."), errors="coerce")
    work["__volume"] = pd.to_numeric(work[volume_column].astype(str).str.replace(",", "."), errors="coerce")
    work["__subject"] = work[subject_column].astype(str) if subject_column else "subject_1"
    work["__group"] = work[group_column].astype(str) if group_column else control_group
    datasets: list[Dataset] = []
    for subject, rows in work.dropna(subset=["__time", "__volume"]).groupby("__subject", sort=False):
        subject = str(subject)
        if subject in exclude:
            continue
        rows = rows.sort_values("__time")
        if len(rows) < 4 or rows["__time"].duplicated().any() or (rows["__volume"] <= 0).any():
            continue
        datasets.append(Dataset(subject, str(rows["__group"].iloc[0]), rows["__time"].to_numpy(float), rows["__volume"].to_numpy(float)))
    if not datasets:
        raise HTTPException(status_code=422, detail="No valid subject: at least 4 positive points are required per subject")
    return datasets


def _convert_units(frame: pd.DataFrame, mapping: dict[str, str | None], time_unit: str, volume_unit: str) -> pd.DataFrame:
    if time_unit not in {"days", "hours"} or volume_unit not in {"mm3", "cm3"}:
        raise HTTPException(status_code=422, detail="Supported units: days/hours and mm3/cm3")
    converted = frame.copy()
    if time_unit == "hours":
        column = mapping.get("time")
        if column:
            converted[column] = pd.to_numeric(converted[column].astype(str).str.replace(",", "."), errors="coerce") / 24.0
    if volume_unit == "cm3":
        columns = [mapping.get("volume")] if mapping.get("volume") else [column for column in converted.columns if column != mapping.get("time") and not str(column).startswith("__")]
        for column in columns:
            if column:
                converted[column] = pd.to_numeric(converted[column].astype(str).str.replace(",", "."), errors="coerce") * 1000.0
    return converted


_load_sessions()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/sessions")
def list_sessions() -> list[dict[str, Any]]:
    return [{"session_id": session_id, "filename": session.get("filename", "upload"), "has_mapping": bool(session.get("datasets")), "has_calibration": bool(session.get("calibration")), "has_treatment": bool(session.get("treatment")), "has_simulation": bool(session.get("simulation"))} for session_id, session in SESSIONS.items()]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    mapping = session.get("mapping")
    return {"session_id": session_id, "filename": session.get("filename", "upload"), "preview": _preview(session["frame"]), "mapping": mapping, "control_group": session.get("control_group"), "groups": sorted({dataset.group for dataset in session.get("datasets") or []}), "validation": session.get("validation", []), "calibration": session.get("calibration"), "treatment": session.get("treatment"), "simulation": session.get("simulation")}


@app.post("/api/datasets/upload")
async def upload_dataset(file: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not file:
        raise HTTPException(status_code=400, detail="At least one file is required")
    frames = []
    filenames = []
    for upload in file:
        content = await upload.read()
        filename = upload.filename or "upload.csv"
        parsed = read_table(filename, content)
        frames.append(parsed)
        filenames.append(filename)
    if len(frames) > 1:
        for parsed, filename in zip(frames, filenames):
            parsed["__source_file"] = filename
    frame = pd.concat(frames, ignore_index=True, sort=False)
    source_id = uuid.uuid4().hex[:10]
    session = {"frame": frame, "datasets": None, "calibration": None, "filename": filenames[0], "filenames": filenames}
    SESSIONS[source_id] = session
    (SESSIONS_DIR / source_id).mkdir(exist_ok=True)
    frame.to_csv(SESSIONS_DIR / source_id / "uploaded.csv", index=False)
    _save_session(source_id, session)
    return {"source_id": source_id, "filename": filenames[0], "filenames": filenames, **_preview(frame)}


@app.post("/api/datasets/mapping")
def apply_mapping(request: MappingRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.source_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        frame = _convert_units(session["frame"], request.mapping, request.time_unit, request.volume_unit)
        datasets, validation = normalise_table_report(frame, request.mapping, request.control_group, session.get("filename", "upload"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    excluded = set(request.exclude_subjects)
    datasets = [dataset for dataset in datasets if dataset.subject not in excluded]
    for item in validation:
        if item["id"] in excluded:
            item["excluded"] = True
    session["datasets"] = datasets
    session["control_group"] = request.control_group
    session["treated_groups"] = request.treated_groups
    session["mapping"] = request.mapping
    session["time_unit"] = request.time_unit
    session["volume_unit"] = request.volume_unit
    session["validation"] = validation
    _save_session(request.source_id, session)
    return {"session_id": request.source_id, "subjects": validation, "ready": len(datasets) > 0, "groups": sorted({dataset.group for dataset in datasets}), "control_group": request.control_group, "excluded_subjects": sorted(excluded)}


def _calibrate_session(job_id: str, session_id: str, request: CalibrationRequest) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session or not session.get("datasets"):
        raise ValueError("Validate the data first")
    control = [dataset for dataset in session["datasets"] if dataset.group == session.get("control_group", dataset.group)]

    def on_progress(stage: str, step: int, n_steps: int) -> None:
        if is_cancelled(job_id):
            raise JobCancelled()
        update_job(job_id, stage=stage, step=step, n_steps=n_steps)

    result = calibrate_global(control or session["datasets"], request.models, request.starts, request.seed, request.t0_strategy, request.count_t0_in_ic, on_progress=on_progress, maxiter=request.maxiter, selection_metric=request.selection_metric)
    if request.validation_top_k:
        update_job(job_id, stage="last-point validation")
        for ranked in result["ranking"][:request.validation_top_k]:
            ranked["validation"] = evaluate_last_point_validation(control or session["datasets"], ranked["model"], max(1, min(request.starts, 3)), request.seed, request.t0_strategy)
    session["calibration"] = result
    session["calibration_config"] = request.model_dump()
    _save_session(session_id, session)
    return {"session_id": session_id, **result}


@app.post("/api/calibration", status_code=202)
def run_calibration(request: CalibrationRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("datasets"):
        raise HTTPException(status_code=409, detail="Validate the data first")
    job_id = submit_job(_calibrate_session, request.session_id, request)
    n_models = len(request.models) or len(GROWTH_LAWS)
    return {"job_id": job_id, "n_steps": n_models * max(1, request.starts), "status": "queued"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    status = get_job(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    if status.get("status") == "done":
        status["result"] = get_job_result(job_id)
    return status


@app.post("/api/jobs/{job_id}/cancel")
def cancel_status(job_id: str) -> dict[str, Any]:
    if not cancel_job(job_id):
        raise HTTPException(status_code=409, detail="Job already finished or not found")
    return {"job_id": job_id, "status": "cancellation_requested"}


@app.get("/api/calibration/{job_id}")
def calibration_result(job_id: str) -> dict[str, Any]:
    status = get_job(job_id)
    if not status or status.get("status") != "done":
        raise HTTPException(status_code=409, detail="Calibration is not complete")
    return get_job_result(job_id)


@app.post("/api/calibration/select")
def select_calibration_model(request: SelectModelRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("calibration"):
        raise HTTPException(status_code=404, detail="Calibration not found")
    ranking = session["calibration"]["ranking"]
    selected = next((row for row in ranking if row["model"] == request.model), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Model not found in ranking")
    session["calibration"]["ranking"] = [selected, *[row for row in ranking if row["model"] != request.model]]
    session["calibration"]["winner"] = request.model
    session["calibration"]["selected_model"] = request.model
    _save_session(request.session_id, session)
    return {"session_id": request.session_id, "winner": request.model, "selected_model": request.model}


def _fit_treatment_session(job_id: str, request: TreatmentRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("calibration"):
        raise ValueError("Calibrate growth first")
    winner = session["calibration"]["ranking"][0]
    treated = [dataset for dataset in session["datasets"] if dataset.group == request.treated_group] if request.treated_group else [dataset for dataset in session["datasets"] if dataset.group != session.get("control_group")]
    result = compare_treatments(treated or session["datasets"], winner["model"], winner["params"], request.doses, request.starts, request.seed, on_progress=lambda stage, step, n_steps: update_job(job_id, stage=stage, step=step, n_steps=n_steps))
    session["treatment"] = result
    session["treatment_config"] = request.model_dump()
    _save_session(request.session_id, session)
    return {"session_id": request.session_id, **result}


@app.post("/api/treatment", status_code=202)
def run_treatment(request: TreatmentRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("calibration"):
        raise HTTPException(status_code=409, detail="Calibrate growth first")
    job_id = submit_job(_fit_treatment_session, request)
    return {"job_id": job_id, "n_steps": len(TREATMENT_LAWS) * max(1, request.starts), "status": "queued"}


def _run_simulation_session(job_id: str, request: SimulationRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("calibration"):
        raise ValueError("Calibrate a model before simulating")
    winner = session["calibration"]["ranking"][0]
    times = np.linspace(0, request.horizon_days, request.n_points)
    control = simulate(times, request.initial_volume, winner["model"], winner["params"])
    scenarios = []
    n_steps = max(1, len(request.scenarios))
    for index, scenario in enumerate(request.scenarios, 1):
        update_job(job_id, stage=f"simulation {scenario.name}", step=index, n_steps=n_steps)
        if len(scenario.dose_times) != len(scenario.doses):
            raise ValueError(f"Le scenario {scenario.name} a des doses incoherentes")
        values = simulate(times, request.initial_volume, winner["model"], winner["params"], request.treatment_model, request.treatment_params, zip(scenario.dose_times, scenario.doses))
        final = float(values[-1])
        scenarios.append({"name": scenario.name, "values": values.tolist(), "final_volume": final, "tgi_pct": float(100 * (1 - final / max(float(control[-1]), 1e-12)))})
    result = {"t": times.tolist(), "control": control.tolist(), "model": winner["model"], "scenarios": scenarios}
    session["simulation"] = result
    session["simulation_config"] = request.model_dump()
    return result


@app.post("/api/experiments/simulate", status_code=202)
def run_simulation(request: SimulationRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session or not session.get("calibration"):
        raise HTTPException(status_code=409, detail="Calibrate a model before simulating")
    job_id = submit_job(_run_simulation_session, request)
    return {"job_id": job_id, "n_steps": max(1, len(request.scenarios)), "status": "queued"}


@app.get("/api/export/{session_id}")
def export_session(session_id: str) -> StreamingResponse:
    session = SESSIONS.get(session_id)
    if not session or not session.get("calibration"):
        raise HTTPException(status_code=409, detail="No calibration to export")

    calibration = session["calibration"]
    simulation = session.get("simulation")
    treatment = session.get("treatment")
    calibration_config = session.get("calibration_config", {})
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        ranking = pd.DataFrame([
            {key: value for key, value in row.items() if key not in {"curves", "params", "diagnostics", "validation"}}
            for row in calibration["ranking"]
        ])
        bundle.writestr("calibration/ranking.csv", ranking.to_csv(index=False))
        bundle.writestr("calibration/summary.csv", pd.DataFrame([{"model": row["model"], "bic": row["metrics"]["bic"], "aicc": row["metrics"]["aicc"], "delta_bic": row["delta_bic"], "akaike_weight": row["akaike_weight"], "rmse": row["metrics"]["rmse"], "mae": row["metrics"]["mae"], "ccc": row["metrics"]["ccc"]} for row in calibration["ranking"]]).to_csv(index=False))
        bundle.writestr("calibration/parameters.csv", pd.DataFrame([{**{"model": row["model"]}, **row["params"]} for row in calibration["ranking"]]).to_csv(index=False))
        bundle.writestr("calibration/parameters.json", json.dumps({
            "winner": calibration["winner"],
            "tie_with": calibration["tie_with"],
            "parameters": calibration["ranking"][0]["params"],
        }, indent=2))

        # Provenance: what produced this result, so it can be reproduced later.
        bundle.writestr("provenance.json", json.dumps({
            "app_version": app.version,
            "session_id": session_id,
            "source_file": session.get("filename", "inconnu"),
            "control_group": session.get("control_group"),
            "treated_groups": session.get("treated_groups", []),
            "calibration_config": calibration_config,
            "treatment_config": session.get("treatment_config"),
            "simulation_config": session.get("simulation_config"),
        }, indent=2, default=str))

        report = [
            "Tumor Fit Tool - session report",
            f"Session: {session_id}",
            f"Version de l'application: {app.version}",
            f"Fichier source: {session.get('filename', 'inconnu')}",
            f"Seed: {calibration_config.get('seed', 'unknown')}",
            f"T0 strategy: {calibration.get('t0_strategy', 'free')}",
            f"Winning model: {calibration['winner']}",
            f"Tie (delta BIC < 2): {', '.join(calibration['tie_with']) or 'none'}",
            "",
            "Winning model parameters:",
            json.dumps(calibration["ranking"][0]["params"], indent=2),
        ]
        if treatment:
            bundle.writestr("treatment/summary.csv", pd.DataFrame([{"model": row["model"], "bic": row["metrics"]["bic"], "aicc": row["metrics"]["aicc"], "delta_bic": row["delta_bic"]} for row in treatment["ranking"]]).to_csv(index=False))
            bundle.writestr("treatment/parameters.csv", pd.DataFrame([{**{"model": row["model"]}, **row["params"]} for row in treatment["ranking"]]).to_csv(index=False))
            report += [
                "",
                f"Winning treatment term: {treatment['winner']}",
                "Treatment parameters:",
                json.dumps(treatment["ranking"][0]["params"], indent=2),
            ]
        bundle.writestr("report.txt", "\n".join(report))

        for row in calibration["ranking"]:
            curves = []
            for curve in row["curves"]:
                curves.extend(pd.DataFrame({
                    "subject": curve["subject"], "group": curve["group"], "time": curve["t"],
                    "observed": curve["observed"], "fitted": curve["fitted"],
                }).to_dict("records"))
            bundle.writestr(f"calibration/{row['model']}_curves.csv", pd.DataFrame(curves).to_csv(index=False))

            # One 300 dpi PNG per fitted law, one panel per mouse, matching the notebooks' plot_fits.
            n_subjects = max(len(row["curves"]), 1)
            n_cols = min(3, n_subjects)
            n_rows = -(-n_subjects // n_cols)
            figure, axes = plt.subplots(n_rows, n_cols, figsize=(4.2 * n_cols, 3.4 * n_rows), dpi=300, squeeze=False)
            for index, curve in enumerate(row["curves"]):
                axis = axes[index // n_cols][index % n_cols]
                axis.plot(curve["t"], curve["observed"], "o", color="#3d6078", markersize=3, label="Observe")
                axis.plot(curve["t"], curve["fitted"], "-", color="#c84438", linewidth=1.6, label="Ajuste")
                axis.set_title(str(curve["subject"]), fontsize=8)
                axis.tick_params(labelsize=6)
                if index == 0:
                    axis.legend(fontsize=6)
            for index in range(n_subjects, n_rows * n_cols):
                axes[index // n_cols][index % n_cols].axis("off")
            figure.suptitle(f"{row['model']} - BIC {row['metrics']['bic']:.2f}", fontsize=10)
            figure.tight_layout()
            image = io.BytesIO()
            figure.savefig(image, format="png")
            plt.close(figure)
            bundle.writestr(f"calibration/{row['model']}_fit.png", image.getvalue())

        if simulation:
            points = {"time": simulation["t"], "control": simulation["control"]}
            for scenario in simulation["scenarios"]:
                points[scenario["name"]] = scenario["values"]
            bundle.writestr("experiments/scenarios.csv", pd.DataFrame(points).to_csv(index=False))
            bundle.writestr("experiments/summary.json", json.dumps([
                {key: value for key, value in scenario.items() if key != "values"}
                for scenario in simulation["scenarios"]
            ], indent=2))

            figure, axis = plt.subplots(figsize=(10, 5.5), dpi=150)
            axis.plot(simulation["t"], simulation["control"], "--", color="#7d817d", label="Simulated control")
            colors = ["#c84438", "#3d6078", "#56664d", "#9a6a34"]
            for index, scenario in enumerate(simulation["scenarios"]):
                axis.plot(simulation["t"], scenario["values"], color=colors[index % len(colors)], label=scenario["name"])
            axis.set_xlabel("Temps (jours)")
            axis.set_ylabel("Volume tumoral")
            axis.set_title(f"Projections - model {simulation['model']}")
            axis.grid(alpha=0.2)
            axis.legend()
            figure.tight_layout()
            image = io.BytesIO()
            figure.savefig(image, format="png")
            plt.close(figure)
            bundle.writestr("experiments/scenarios.png", image.getvalue())

    archive.seek(0)
    return StreamingResponse(archive, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="tumor_fit_{session_id}.zip"'})
