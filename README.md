# Tumor Fit Tool

A local application for tumour-growth modelling. Import volume measurements, compare
seven growth laws, fit a treatment effect and simulate dosing protocols, all from a
browser tab, with no programming needed.

**Your data never leaves your computer.** The app runs on `127.0.0.1` and works offline
once installed.

> **New here? Read the [step-by-step tutorial](TUTORIAL.md).** It takes about 10 minutes
> and uses the example data shipped with the project.

## Quick start

You need **Python 3.10 or newer** ([download](https://www.python.org/downloads/); on
Windows tick *"Add python.exe to PATH"*). The first launch needs internet to download the libraries.

| System | How to start |
|---|---|
| Windows | Double-click **`start_app.bat`** |
| macOS / Linux | Run **`./start_app.sh`** in a terminal |

The script creates a private environment, installs the dependencies (first run only),
starts the app and opens <http://127.0.0.1:8000> in your browser. Keep the window open
while you work; close it to stop the app.

<details>
<summary>Manual start (any system)</summary>

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
</details>

## What it does

1. **Data**: CSV or XLSX, in long or wide format, one table or one file per animal
   (several files can be dropped at once). Each animal is validated and the columns are
   detected automatically. *Quick analysis* goes from files to a first ranking in one click.
2. **Calibration**: fits seven growth laws (exponential, Mendelsohn, logistic,
   Bertalanffy, Gompertz, linear, surface) on the control group, with one initial volume
   (T0) per animal. Multistart L-BFGS-B, selection by BIC or AICc.
3. **Results**: ranking with BIC, AICc, ΔBIC, Akaike weights, RMSE, leave-last-point-out
   error, per-animal fits and residuals.
4. **Treatment**: with the growth law frozen, compares seven treatment terms against
   "no treatment" on the treated group.
5. **Experiments**: simulates dosing protocols and reports tumour growth inhibition (TGI).
6. **Report**: one ZIP with tables, parameters, charts, a text report and a provenance
   file that records exactly how the result was produced.

## Data in one minute

Any of these layouts works (details and examples in the [tutorial](TUTORIAL.md#3-preparing-your-data)):

| Layout | Example |
|---|---|
| **Long**: one row per measurement | `day,volume,mouse,group` |
| **Wide**: one column per animal | `day,m1,m2,m3` |
| **One file per animal** | `CTRL_1.csv`, `CTRL_2.csv`, with columns `x, y` |

Each animal needs **at least 4 measurements**, strictly increasing times and positive volumes.

Example files are in [`examples/`](examples). The app can also load them with the
**Load example data** button.

## Project layout

```
backend/            FastAPI server and the scientific code
  core/             growth and treatment models, fitting, metrics, file reading
frontend/           the web interface (plain HTML / CSS / JavaScript, no build step)
examples/           ready-to-use sample data
tests/              automated tests
notebooks_calibracao_NBA/   original calibration notebooks and data
sessions/           created automatically: one folder per working session
```

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Good to know

- Calibration jobs run one at a time, in the background, with a progress bar and a cancel button.
- Calibration is fast: curves already computed are reused, and the seven laws are fitted in
  parallel on all CPU cores but one. Results are identical with or without parallelism.
  Set `TUMOR_FIT_WORKERS=<n>` to choose the number of processes (`1` turns it off).
- Results are reproducible: the same data, settings and seed give the same numbers.
- Sessions are saved in `sessions/` and restored when you reopen the app. Delete a
  session folder to remove it.
- The app has no login. Keep it on `127.0.0.1` (the default) and do not expose it on a network.
