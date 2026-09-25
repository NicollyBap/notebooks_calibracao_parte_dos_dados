# Tumor Fit Tool

Local application for importing tumour volume trajectories, validating subjects, comparing growth laws and simulating treatment protocols.

## Run

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000.

Implemented features:
- CSV and XLSX with separator detection and automatic column mapping;
- per-subject validation (at least 4 points, increasing times, positive volumes);
- seven growth laws and seven treatment terms;
- asynchronous multistart calibration with L-BFGS-B, T0 modes, BIC, AICc, delta BIC, weights and diagnostics;
- last-point validation, MAE, RMSE, WAPE, sMAPE, PCC, CCC and ICC;
- separate calibration of treatment terms on frozen growth;
- scenario simulation and TGI calculation;
- offline FastAPI interface with six progressively unlocked tabs;
- local queue, progress route `/api/jobs/{id}` and persistent sessions in `sessions/<id>/`;
- ZIP export with CSV, JSON, text report and PNG charts;
- long and wide table formats.

Run tests with `py -m pytest -q`.
