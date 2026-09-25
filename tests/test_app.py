import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def _session(client):
    csv = Path("data_test.csv").read_bytes()
    upload = client.post("/api/datasets/upload", files={"file": ("data_test.csv", csv, "text/csv")})
    assert upload.status_code == 200
    session_id = upload.json()["source_id"]
    mapping = client.post("/api/datasets/mapping", json={"source_id": session_id, "mapping": {"time": "day", "volume": "volume", "subject": "mouse", "group": "group"}, "control_group": "control"})
    assert mapping.json()["ready"] is True
    return session_id


def test_async_calibration_and_treatment():
    client = TestClient(app)
    session_id = _session(client)
    job = client.post("/api/calibration", json={"session_id": session_id, "models": ["exponential"], "starts": 1}).json()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    while status["status"] in {"queued", "running"}:
        time.sleep(0.05)
        status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "done"
    assert status["result"]["ranking"][0]["T0"]
    treatment = client.post("/api/treatment", json={"session_id": session_id, "doses": [[7, 1], [14, 1]], "starts": 1})
    assert treatment.status_code == 202
    treatment_status = client.get(f"/api/jobs/{treatment.json()['job_id']}").json()
    while treatment_status["status"] in {"queued", "running"}:
        time.sleep(0.05)
        treatment_status = client.get(f"/api/jobs/{treatment.json()['job_id']}").json()
    assert treatment_status["status"] == "done"
    assert treatment_status["step"] == treatment_status["n_steps"] == 7
    assert len(treatment_status["result"]["ranking"]) == 7

    simulation = client.post("/api/experiments/simulate", json={"session_id": session_id, "scenarios": [{"name": "A", "dose_times": [7], "doses": [1]}]})
    assert simulation.status_code == 202
    simulation_status = client.get(f"/api/jobs/{simulation.json()['job_id']}").json()
    while simulation_status["status"] in {"queued", "running"}:
        time.sleep(0.05)
        simulation_status = client.get(f"/api/jobs/{simulation.json()['job_id']}").json()
    assert simulation_status["status"] == "done"
    assert simulation_status["step"] == simulation_status["n_steps"] == 1
    assert simulation_status["result"]["scenarios"][0]["name"] == "A"


def test_job_reports_progress_per_law_and_start():
    client = TestClient(app)
    session_id = _session(client)
    job = client.post("/api/calibration", json={"session_id": session_id, "models": ["exponential", "logistic"], "starts": 2}).json()
    assert job["n_steps"] == 4  # 2 laws x 2 starts
    seen_steps = set()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    while status["status"] in {"queued", "running"}:
        if status.get("step"):
            seen_steps.add(status["step"])
        time.sleep(0.02)
        status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "done"
    assert status["step"] == status["n_steps"] == 4
    # The stage text names which law/start is running, not a flat placeholder.
    assert "start" in status["stage"] or status["stage"] == "done"


def test_export_zip_has_provenance_and_fit_png():
    client = TestClient(app)
    session_id = _session(client)
    job = client.post("/api/calibration", json={"session_id": session_id, "models": ["exponential"], "starts": 1}).json()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    while status["status"] in {"queued", "running"}:
        time.sleep(0.02)
        status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "done"
    export = client.get(f"/api/export/{session_id}")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as bundle:
        names = bundle.namelist()
        assert "provenance.json" in names
        assert "report.txt" in names
        assert "calibration/summary.csv" in names
        assert "calibration/parameters.csv" in names
        assert "calibration/exponential_fit.png" in names


def test_invalid_experiment_scenario_is_rejected_with_clear_error():
    client = TestClient(app)
    session_id = _session(client)
    job = client.post("/api/calibration", json={"session_id": session_id, "models": ["exponential"], "starts": 1}).json()
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    while status["status"] in {"queued", "running"}:
        time.sleep(0.02)
        status = client.get(f"/api/jobs/{job['job_id']}").json()
    response = client.post("/api/experiments/simulate", json={
        "session_id": session_id,
        "scenarios": [{"name": "A", "dose_times": [7, 14], "doses": [1]}],
    })
    assert response.status_code == 422
    assert "inconsistent" in response.json()["detail"].lower()


def test_mapping_reports_invalid_subjects_and_session_can_be_reloaded():
    client = TestClient(app)
    content = b"day,mouse,group,volume\n0,m1,control,0.8\n1,m1,control,0.9\n2,m1,control,1.0\n3,m1,control,1.1\n0,m2,control,0.8\n1,m2,control,-1\n2,m2,control,1.0\n"
    upload = client.post("/api/datasets/upload", files={"file": ("invalid.csv", content, "text/csv")})
    session_id = upload.json()["source_id"]
    mapped = client.post("/api/datasets/mapping", json={"source_id": session_id, "mapping": {"time": "day", "volume": "volume", "subject": "mouse", "group": "group"}, "control_group": "control"})
    assert mapped.status_code == 200
    subjects = {subject["id"]: subject for subject in mapped.json()["subjects"]}
    assert subjects["m1"]["ok"] is True
    assert subjects["m2"]["ok"] is False
    assert "volume is not positive" in subjects["m2"]["why"]
    restored = client.get(f"/api/sessions/{session_id}")
    assert restored.status_code == 200
    assert restored.json()["validation"] == mapped.json()["subjects"]


def test_wide_input_is_normalised():
    client = TestClient(app)
    content = b"day,mouse_a,mouse_b\n0,0.8,0.7\n1,0.9,0.8\n2,1.0,0.9\n3,1.1,1.0\n"
    upload = client.post("/api/datasets/upload", files={"file": ("wide.csv", content, "text/csv")})
    sid = upload.json()["source_id"]
    mapped = client.post("/api/datasets/mapping", json={"source_id": sid, "mapping": {"time": "day", "volume": None, "subject": None, "group": None}, "control_group": "control"})
    assert mapped.status_code == 200
    assert len(mapped.json()["subjects"]) == 2
