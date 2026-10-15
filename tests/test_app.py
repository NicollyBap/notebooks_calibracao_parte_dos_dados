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
    treatment_csv = (
        b"day,volume,mouse,group\n"
        b"0,0.8,drug_01,treated\n"
        b"2,0.95,drug_01,treated\n"
        b"4,1.1,drug_01,treated\n"
        b"6,1.25,drug_01,treated\n"
        b"8,1.3,drug_01,treated\n"
        b"10,1.15,drug_01,treated\n"
    )
    treatment_upload = client.post(
        "/api/treatment-data/upload",
        data={"session_id": session_id},
        files={"file": ("treatment.csv", treatment_csv, "text/csv")},
    )
    assert treatment_upload.status_code == 200
    assert treatment_upload.json()["session_id"] == session_id
    treatment_mapping = client.post(
        "/api/treatment-data/mapping",
        json={
            "session_id": session_id,
            "mapping": {"time": "day", "volume": "volume", "subject": "mouse", "group": "group"},
            "default_group": "treated",
        },
    )
    assert treatment_mapping.status_code == 200
    assert treatment_mapping.json()["groups"] == ["treated"]
    treatment = client.post("/api/treatment", json={"session_id": session_id, "treated_group": "treated", "doses": [[7, 1], [14, 1]], "starts": 1})
    assert treatment.status_code == 202
    treatment_status = client.get(f"/api/jobs/{treatment.json()['job_id']}").json()
    while treatment_status["status"] in {"queued", "running"}:
        time.sleep(0.05)
        treatment_status = client.get(f"/api/jobs/{treatment.json()['job_id']}").json()
    assert treatment_status["status"] == "done"
    assert treatment_status["step"] == treatment_status["n_steps"] == 12
    assert len(treatment_status["result"]["ranking"]) == 12
    assert all(row["curves"][0]["subject"] == "drug_01" for row in treatment_status["result"]["ranking"])

    restored = client.get(f"/api/sessions/{session_id}")
    assert restored.status_code == 200
    assert restored.json()["treatment_upload"]["filename"] == "treatment.csv"
    assert restored.json()["treatment_groups"] == ["treated"]

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


def test_reloaded_session_rebuilds_validation_and_exclusions():
    client = TestClient(app)
    content = b"day,mouse,group,volume\n0,m1,control,0.8\n1,m1,control,0.9\n2,m1,control,1.0\n3,m1,control,1.1\n0,m2,control,0.8\n1,m2,control,0.9\n2,m2,control,1.0\n3,m2,control,1.1\n"
    upload = client.post("/api/datasets/upload", files={"file": ("reload.csv", content, "text/csv")})
    session_id = upload.json()["source_id"]
    mapped = client.post("/api/datasets/mapping", json={"source_id": session_id, "mapping": {"time": "day", "volume": "volume", "subject": "mouse", "group": "group"}, "control_group": "control", "exclude_subjects": ["m2"]})
    assert mapped.status_code == 200

    from backend.main import _load_sessions

    _load_sessions()
    restored = client.get(f"/api/sessions/{session_id}")
    assert restored.status_code == 200
    body = restored.json()
    assert [subject["id"] for subject in body["validation"] if not subject.get("excluded")] == ["m1"]
    assert [subject["id"] for subject in body["validation"] if subject.get("excluded")] == ["m2"]


def test_wide_input_is_normalised():
    client = TestClient(app)
    content = b"day,mouse_a,mouse_b\n0,0.8,0.7\n1,0.9,0.8\n2,1.0,0.9\n3,1.1,1.0\n"
    upload = client.post("/api/datasets/upload", files={"file": ("wide.csv", content, "text/csv")})
    sid = upload.json()["source_id"]
    mapped = client.post("/api/datasets/mapping", json={"source_id": sid, "mapping": {"time": "day", "volume": None, "subject": None, "group": None}, "control_group": "control"})
    assert mapped.status_code == 200
    assert len(mapped.json()["subjects"]) == 2


def test_multiple_xy_files_are_loaded_as_separate_subjects():
    client = TestClient(app)
    files = [
        ("file", ("data_figB_curve_1.csv", b"x,y\n0,1\n1,2\n2,4\n3,8\n", "text/csv")),
        ("file", ("data_figB_curve_2.csv", b"x,y\n0,2\n1,3\n2,5\n3,9\n", "text/csv")),
    ]
    upload = client.post("/api/datasets/upload", files=files)
    assert upload.status_code == 200
    body = upload.json()
    assert body["filenames"] == ["data_figB_curve_1.csv", "data_figB_curve_2.csv"]
    assert body["mapping_guess"]["time"] == "x"
    assert body["mapping_guess"]["volume"] == "y"

    mapped = client.post("/api/datasets/mapping", json={"source_id": body["source_id"], "mapping": {"time": "x", "volume": "y", "subject": None, "group": None}, "control_group": "control"})
    assert mapped.status_code == 200
    assert mapped.json()["ready"] is True
    assert [subject["id"] for subject in mapped.json()["subjects"]] == ["data_figB_curve_1", "data_figB_curve_2"]


def test_multiple_upload_rejects_an_invalid_supported_file():
    client = TestClient(app)
    files = [
        ("file", ("valid.csv", b"x,y\n0,1\n1,2\n2,3\n3,4\n", "text/csv")),
        ("file", ("broken.csv", b"x,y\n\xff\xfe", "text/csv")),
    ]
    upload = client.post("/api/datasets/upload", files=files)
    assert upload.status_code == 400
    assert "broken.csv" in upload.json()["detail"]


def test_upload_directory_loads_all_matching_files(tmp_path):
    client = TestClient(app)
    for index in range(20):
        (tmp_path / f"curve_{index}.csv").write_text(f"x,y\n0,{index}\n1,{index + 1}\n2,{index + 2}\n3,{index + 3}\n", encoding="utf-8")

    response = client.post("/api/datasets/upload-folder", json={"directory": str(tmp_path)})
    assert response.status_code == 200
    body = response.json()
    assert len(body["filenames"]) == 20
    assert body["mapping_guess"]["time"] == "x"
    assert body["mapping_guess"]["volume"] == "y"


def _tumour_csv(header: str) -> bytes:
    rows = "\n".join(f"{day}, {0.5 * 2 ** (day / 10):.4f}" for day in range(0, 30, 3))
    return f"{header}\n{rows}\n".encode()


def test_multi_file_upload_with_one_header_in_capital_letters():
    # Regression: fig3D_NOG_CTRL_5.csv has "X, y" while the others have "x, y".
    client = TestClient(app)
    files = [("file", (f"fig_NOG_CTRL_{index}.csv", _tumour_csv("X, y" if index == 5 else "x, y"), "text/csv")) for index in range(1, 7)]
    upload = client.post("/api/datasets/upload", files=files)
    assert upload.status_code == 200
    body = upload.json()
    assert len(body["filenames"]) == 6 and body["warnings"] == []
    assert body["mapping_guess"]["time"] == "x" and body["mapping_guess"]["volume"] == "y"
    mapped = client.post("/api/datasets/mapping", json={"source_id": body["source_id"], "mapping": {"time": "x", "volume": "y", "subject": None, "group": None}, "control_group": "control"})
    assert mapped.status_code == 200
    subjects = mapped.json()["subjects"]
    assert mapped.json()["ready"] is True and len(subjects) == 6 and all(subject["ok"] for subject in subjects)


def test_unreadable_file_is_reported_without_blocking_the_others():
    client = TestClient(app)
    files = [("file", ("fig_CTRL_1.csv", _tumour_csv("x, y"), "text/csv")), ("file", ("fig_CTRL_2.csv", b"\x00\x01garbage\xff", "text/csv"))]
    upload = client.post("/api/datasets/upload", files=files)
    assert upload.status_code == 200
    assert upload.json()["filenames"] == ["fig_CTRL_1.csv"]
    assert any("fig_CTRL_2.csv" in warning for warning in upload.json()["warnings"])


def test_column_guess_does_not_mistake_day_for_volume():
    from backend.main import _guess_column

    assert _guess_column(["day", "volume", "mouse", "group"], ("volume", "tumor", "tumour", "mm3", "v", "y")) == "volume"
    assert _guess_column(["Time (days)", "Tumor volume (mm3)"], ("volume", "tumor", "tumour", "mm3", "v", "y")) == "Tumor volume (mm3)"
    assert _guess_column(["x", "y"], ("volume", "tumor", "tumour", "mm3", "v", "y"), exclude=("x",)) == "y"
