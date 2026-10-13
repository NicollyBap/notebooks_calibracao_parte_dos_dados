# Tumor Fit Tool: Tutorial

This tutorial takes you from installation to a finished report. Part 2 is a 10-minute
walkthrough with the example data that ships with the project; the rest is a reference
you can come back to.

**Contents**

1. [Install and start](#1-install-and-start)
2. [10-minute walkthrough](#2-ten-minute-walkthrough)
3. [Preparing your data](#3-preparing-your-data)
4. [The six tabs in detail](#4-the-six-tabs-in-detail)
5. [Reading your results](#5-reading-your-results)
6. [What you get in the report](#6-what-you-get-in-the-report)
7. [Troubleshooting](#7-troubleshooting)
8. [Glossary](#8-glossary)

---

## 1. Install and start

**You need:** Python 3.10 or newer, and internet access for the first launch only.
Get Python at <https://www.python.org/downloads/>. On Windows, tick **"Add python.exe to PATH"**
in the installer.

| System | Start the app |
|---|---|
| **Windows** | Double-click **`start_app.bat`** |
| **macOS / Linux** | Open a terminal in the project folder and run **`./start_app.sh`** |

What happens: the script creates a private Python environment in `.venv/`, installs the
libraries (first run only, a few minutes), starts the server and opens
**http://127.0.0.1:8000** in your browser. If the page does not open by itself, type that
address in your browser.

- **Keep the black terminal window open** while you work. It is the app's engine.
- **To stop**, close that window (or press `Ctrl+C`).
- The next launches take a couple of seconds.

Everything runs on your computer. Nothing is uploaded anywhere.

---

## 2. Ten-minute walkthrough

The folder `examples/frosberg_fig3D/` contains 10 small files, one per animal:
6 controls (`..._NOG_CTRL_1` to `_6`) and 4 treated animals (`..._hIL2_NOG_CART_1` to `_4`).
Each file has two columns, `x` (time, read by the app as days) and `y` (tumour volume).

### Step 1. Load the data

Open the **Data** tab (step 01) and click **Load example data**.
(Your own files work the same way: drop them on the dashed box, or click it and select
several files at once, or use **Select folder**.)

You should now see:

- **"10 files loaded"** and a list of the file names;
- a preview table of the first rows. (The chart of all raw curves appears once the data are validated, which Quick analysis does for you.)

The app recognised the columns `x` (time) and `y` (volume) by itself, and it guessed the
groups from the file names: files containing `CTRL` become the **control** group, and the
others form their own group, `hIL2_NOG_CART`.

### Step 2. Quick analysis

Click ** Quick analysis**. The app validates the animals, fits all seven growth laws on
the control animals and jumps to the **Results** tab. With the example data this takes
a few seconds (about 4 s in our test, on a single CPU core).

> Quick analysis uses **1 start** per law: it is meant for a first look. You will redo the
> calibration with more starts in step 4.

### Step 3. Read the ranking

On the **Results** tab (step 03):

- The banner says which law **wins** and whether others are **tied** (within ΔBIC < 2,
  meaning the data cannot really tell them apart). In our test the logistic law ranked first.
- The table lists every law, best first. **Lower BIC is better.** See
  [Reading your results](#5-reading-your-results) for every column.
- Below it, one small chart per animal shows the observed points and the fitted curve, then
  a **residuals** chart (observed minus fitted; you want a random scatter around zero).
- Charts are interactive: **drag** to zoom into an area, **scroll** to zoom in or out,
  **double-click** to reset, **click a legend entry** to hide or show a series.

### Step 4. Confirm with more starts (recommended)

Optimisation can get stuck in a poor solution, so the app tries several random starting points
("starts"). Go back to **Calibration** (step 02), set **Number of starts** to **6** or more,
and press **Run calibration**. A progress bar shows which law and which start is running
(about 35 seconds at 3 starts for the example data on a single core; more starts take proportionally longer, and more CPU cores make it faster).
Compare the new ranking with the quick one: if the winner changes, trust the run with more starts.

### Step 5. Choose the growth law

On the **Results** tab, click **Use** on the law you want to keep (normally the first row).
This freezes that law for the next steps and unlocks the **Treatment** tab.

### Step 6. Fit the treatment effect

On the **Treatment** tab (step 04):

1. **Treated group**: choose `hIL2_NOG_CART`.
2. **Dose days** and **Doses**: the schedule that was actually used, as comma-separated lists
   of the same length, for example `60,67,74` and `1,1,1`.
3. Click **Compare treatments**.

> ⚠ **Important for this example.** The example files do **not** contain the dosing schedule,
> and their time axis runs from day 13 to day 191. Dose days are on the **same clock as the
> time column** of your data. Whatever you type here is an assumption: use the example to
> learn the mechanics, not to draw conclusions. With your own data, enter the real schedule.

The app fits seven treatment terms plus **`none`** (no treatment effect) and ranks them. If
`none` is not beaten, the data show no evidence of a treatment effect for that schedule.
The **Term** menu chooses which term is carried to the simulation.

### Step 7. Test protocols

On the **Experiments** tab (step 05):

1. Set **Initial volume** to a realistic starting volume for your animals.
2. Set **Horizon (days)** to cover the period you care about (the default 60 is short
   for the example, whose data run to day ~190).
3. Edit the first scenario (name, dose days, doses), or use the **Generator** (number of doses,
   first day, interval, dose) to create schedules, then **+** to add more scenarios.
4. Click **Simulate scenarios**.

You get the projected curves and, per scenario, the **TGI** (tumour growth inhibition)
at the end of the horizon: `TGI % = 100 × (1 − final volume with treatment / final volume of the simulated control)`.
A TGI of 0 % means no effect; 100 % means the tumour is gone.

### Step 8. Download the report

On the **Report** tab (step 06), click **Download ZIP**. See
[What you get in the report](#6-what-you-get-in-the-report).

**You are done.** Your session is saved automatically: if you close the browser and reopen
the app, it takes you back to where you stopped.

---

## 3. Preparing your data

### Accepted layouts

The app accepts **CSV** (comma, semicolon or tab separated; UTF-8) and **XLSX** (the first
sheet is read). Choose the layout that matches how your data are stored.

**A. Long format: one row per measurement** (best when you have several groups)

```csv
day,volume,mouse,group
0,0.80,CTRL_01,control
2,0.94,CTRL_01,control
4,1.11,CTRL_01,control
0,0.82,TREATED_01,treated
2,0.85,TREATED_01,treated
```

Map the four columns in the form (Time, Volume, Subject, Group).

**B. Wide format: one column per animal** (all animals are put in the control group)

```csv
day,m1,m2,m3
0,0.80,0.82,0.79
2,0.94,0.90,0.97
4,1.11,1.08,1.15
```

Set **Volume** to `(wide format)` and **Subject** to `(one subject only)`.
Every column other than the time column becomes one animal.

**C. One file per animal** (typical when curves were digitised from papers)

`CTRL_1.csv`:

```csv
x, y
13.1, 0.06
20.1, 7.55
26.2, 6.65
```

Drop all the files together. The **file name becomes the animal's name**. Column names may
differ in capitalisation (`x` vs `X`) or have spaces after commas: the app copes with both.
If at least one file name contains a control word (`CTRL`, `control`, `ctl`, `vehicle`,
`placebo`), the app builds groups from the names: control files form the **control** group,
and the other files are grouped by their name without the trailing number
(`hIL2_NOG_CART_3` → `hIL2_NOG_CART`). If no name looks like a control, all animals go to the
control group.

### Rules each animal must satisfy

| Rule | Why |
|---|---|
| At least **4 measurements** | Fewer points cannot constrain a growth law |
| Times **strictly increasing**, no duplicates | A volume cannot have two values at one time |
| Volumes **greater than zero** | The models work on positive volumes |
| Times and volumes are **numbers** | Text or empty cells are not usable |
| **5 or more** measurements to get the "last point" check | That check hides the last point and predicts it |

An animal that breaks a rule is **not deleted**: it stays visible in a **"Subjects to fix"**
table with the reason, and it is left out of the calibration until you fix the file or
exclude it deliberately.

### Units

- **Time unit**: `days` or `hours` (hours are converted to days).
- **Volume unit**: `mm3` or `cm3` (cm³ are converted to mm³).

Use one unit for the whole file. All results and the dose days are expressed in **days**.

### Common data mistakes

- **Decimal commas in a comma-separated file** (`0,8` in a `,` file): the columns get mixed
  up. Save the file with semicolons, or use decimal points.
- **Several sheets in an XLSX**: only the first one is read.
- **Mixing layouts in one upload** (a long table and single-animal files together): upload
  one layout at a time.
- **A zero volume** (tumour not yet measurable): remove that row or replace it with a small
  positive detection limit; zeros are rejected.

---

## 4. The six tabs in detail

The tabs unlock progressively: you can only go to a step once the previous one is done.

### 01 · Data

| Control | What it does |
|---|---|
| **Drop zone / Select folder** | Import one or many files at once |
| **Load example data** | Loads the bundled example folder (shown before anything is imported) |
| ** Quick analysis** | Validates with the detected columns, then runs all seven laws with 1 start |
| **Time / Volume / Subject / Group** | Which column holds what. Use `(wide format)` and `(one subject only)` / `(one group only)` where the layout calls for it |
| **Time unit / Volume unit** | See [Units](#units) |
| **Control group** | Name of the group used to fit growth (default `control`) |
| **Subjects to exclude** | Animals to leave out, comma-separated (for example `m3,m7`) |
| **Validate data →** | Checks every animal and moves on |

If some files could not be read, an orange **"file(s) need attention"** box lists them with the
reason. The other files are still imported.

### 02 · Calibration

Growth is fitted **on the control group only**, with **shared parameters for all animals** and
**one initial volume (T0) per animal**.

| Setting | Meaning | Default |
|---|---|---|
| **Models to compare** | The growth laws to fit (see below) | all seven |
| **T0 strategy** | How free each animal's starting volume is: *Free* (0.10× to 4× the first measurement), *Fixed at first point*, *Narrow* (±10 %) | Free |
| **Criterion** | Score used to rank the laws: **BIC** (stricter on complexity) or **AICc** | BIC |
| **Number of starts** | Random starting points tried per law. More starts means a more reliable result and a longer run | 3 |
| **Maximum iterations** | Optimiser iterations per start | 250 |
| **Seed** | Fixes the random starts so the run can be repeated exactly | 42 |

The seven growth laws (V is the volume, r a growth rate; the other letters are fitted parameters):

| Law | Parameters | Idea |
|---|---|---|
| exponential | r | Unlimited growth |
| mendelsohn | r, b | Growth proportional to V^b |
| logistic | r, K | Growth that slows towards a ceiling K |
| bertalanffy | r, alpha | Surface-driven growth minus volume loss |
| gompertz | r, K, c | Fast early growth that slows towards K |
| linear | r, f | Growth that becomes linear at large volumes |
| surface | r, f | Growth driven by the tumour surface |

**How long does it take?** Time grows with *(number of animals) × (number of laws) × (number
of starts)*. In our test (6 animals, 7 laws, one CPU core) 1 start took about 4 seconds and
3 starts about 35 seconds. A progress bar and a **Cancel job** button are shown. Jobs run one at a time.

**Speed on multi-core computers.** The seven laws are fitted **in parallel**, using all CPU
cores but one (8 at most), so a 4-core laptop finishes roughly 3 times faster than a single core.
The numbers are **exactly the same** as with a single core: only the waiting time changes.
To choose the number of processes yourself, set the environment variable
`TUMOR_FIT_WORKERS` before starting the app (for example `TUMOR_FIT_WORKERS=1` to turn
parallelism off, or `TUMOR_FIT_WORKERS=6`). On Windows: `set TUMOR_FIT_WORKERS=6` in the terminal,
then `start_app.bat`.

**Rule of thumb:** use 1 start to explore, **6 to 8 starts for a result you will report**.

### 03 · Results

See [Reading your results](#5-reading-your-results). Click **Use** to select a law and unlock
the next tab. You can come back and choose another law at any time.

### 04 · Treatment

With the growth law frozen, the app fits a **treatment term** on the treated group.

| Setting | Meaning |
|---|---|
| **Treated group** | Group the term is fitted on (the non-control groups are offered first) |
| **Term** | Term carried forward to the simulation (all seven are always compared) |
| **Dose days** | Days of administration, **on the same clock as your time column** |
| **Doses** | Dose given each day, same number of values as the days |
| **Starts** | Random starting points per term |

A treatment effect `e(t)` is subtracted from the growth rate (`dV/dt = growth − e(t) × V`).
`a` and `b` below are fitted; `d` is a dose, `Δ` the time since that dose:

| Term | Effect of each dose |
|---|---|
| **ED** | `a·d·exp(−b·Δ)`: fades exponentially after the dose |
| **CD** | `a·(cumulative dose)·exp(−b·Δ)`: fades, and grows with the dose already given |
| **AccelED** | `a·d·exp(−b·Δ²)`: stays strong, then drops faster |
| **MM** | `a·d / (1 + b·d)`: saturates with the dose, does not fade |
| **LS** | `a·d / (1 + b·V)`: weaker on larger tumours, does not fade |
| **dePR** | `δ·d^λ / (s·V^λ + d^λ)`: depends on both dose and volume (δ, s, λ fitted) |
| **none** | No effect. Always included as the reference |

**If `none` ranks first**, no treatment term explained the data better than doing nothing:
check the dose schedule before concluding there is an effect.

### 05 · Experiments

Simulates the tumour with the chosen growth law and treatment term.

| Setting | Meaning |
|---|---|
| **Initial volume (mm³)** | Starting volume of the simulated tumour |
| **Horizon (days)** | Length of the simulation |
| **Simulation points** | Smoothness of the curves |
| **Generator** | Creates a regular schedule: number of doses, first day, interval, dose |
| **Scenario rows** | A name, the dose days and the doses. **+** adds one, **−** removes one |

Result: projected curves and one **TGI %** per scenario (see step 7 of the walkthrough).
These are **model projections**, useful for comparing schedules. They are not predictions
of a real experiment.

### 06 · Report

**Download ZIP** exports everything. See the next sections.

---

## 5. Reading your results

### The ranking table

| Column | How to read it |
|---|---|
| **Rank / Law** | Laws ordered best first by the chosen criterion |
| **BIC, AICc** | Fit quality **penalised for complexity**. **Lower is better.** Only differences matter, not the absolute value |
| **ΔBIC** | BIC minus the best BIC. `0` for the winner |
| **Akaike weight** | Relative support of each law among those compared (they sum to 100 %). Computed from ΔBIC |
| **RMSE** | Typical size of the fitting error, in volume units |
| **Last point (MAE)** | Leave-one-out check on the top three laws: the last measurement of every animal is hidden, the law is refitted and asked to predict it. Smaller is better. Shown as `-` if some animals have fewer than 5 points |
| **T0 bounds** | `⚠ n` means *n* animals have a starting volume stuck at the edge of its allowed range. Hover for details. Consider another T0 strategy or check those animals |

### Is the winner really better?

A common rule of thumb for ΔBIC between two laws:

| ΔBIC | Evidence for the better law |
|---|---|
| below 2 | Not worth mentioning (**tie**, the banner says so) |
| 2 to 6 | Positive |
| 6 to 10 | Strong |
| above 10 | Very strong |

When laws are tied, prefer the **simpler** one (fewer parameters), or report both.

### Checking the fit

- **Per-animal charts**: fitted curves should follow the points.
- **Residuals chart**: points should scatter randomly around the zero line. A clear pattern,
  such as all positive at late times, shows a bias that the RMSE does not reveal.
- **Last point (MAE)**: a law that fits well but predicts the held-out point badly may be overfitting.

### Good practice

- Use **6 to 8 starts** for any result you report, and keep the seed.
- A handful of animals gives a **wide uncertainty**: treat rankings as guidance, not proof.
- The growth laws are **phenomenological**: they describe curves, they do not prove a mechanism.
- Report the law, its parameters, the criterion, the number of starts and the seed. The
  `provenance.json` file in the ZIP contains all of these.

---

## 6. What you get in the report

The ZIP is named `tumor_fit_<session id>.zip`.

| File | Content |
|---|---|
| `report.txt` | Readable summary: source file, seed, T0 strategy, winning law and parameters, treatment term |
| `provenance.json` | Everything needed to reproduce the result (settings, groups, source file, app version) |
| `calibration/summary.csv` | One row per law: BIC, AICc, ΔBIC, Akaike weight, RMSE, MAE, CCC |
| `calibration/ranking.csv` | The full ranking table |
| `calibration/parameters.csv`, `parameters.json` | Fitted parameters of every law; winner and ties |
| `calibration/<law>_curves.csv` | Observed and fitted values for every animal and time |
| `calibration/<law>_fit.png` | 300 dpi figure, one panel per animal |
| `treatment/summary.csv`, `parameters.csv` | Treatment ranking and parameters (if you ran the Treatment step) |
| `experiments/scenarios.csv`, `summary.json`, `scenarios.png` | Simulated curves, TGI per scenario and a figure (if you ran Experiments) |

**Sessions.** The app also keeps each working session in a folder `sessions/<id>/`
(your imported data and settings). To remove a session, delete its folder while the app
is stopped.

---

## 7. Troubleshooting

| Problem | What to do |
|---|---|
| Double-clicking `start_app.bat` shows *"Python ... was not found"* | Install Python 3.10+ and tick *Add python.exe to PATH*, then try again |
| Installation fails at first launch | Check your internet connection, then run the script again |
| The browser shows *"can't connect"* | Wait a few seconds and refresh. Make sure the black terminal window is still open |
| *"Address already in use"* in the terminal | The app is already running in another window. Close it, or open http://127.0.0.1:8000 |
| An animal appears in **"Subjects to fix"** | Read the reason in the table. Usual causes: fewer than 4 points, repeated times, a volume of 0 or less, non-numeric cells |
| A file is listed as *skipped* | It is not valid CSV/XLSX text (or is empty). Re-export it and upload again |
| Warning *"columns ... differ from the first file"* | The files do not share the same column names, so some rows are not recognised. Rename the headers consistently |
| **Quick analysis** is greyed out | The time and volume columns could not be detected. Use the mapping form below the drop zone |
| Treated animals were fitted as controls | Rename files so control files contain `CTRL`/`control` and the others do not, or use the long format with a Group column |
| The Treatment tab is locked | Click **Use** on a law in the Results tab first |
| The result changes between runs | Keep the same **Seed** and **Number of starts**. With 1 or 2 starts results are less stable, so use more |
| `⚠` in the T0 bounds column | Some starting volumes sit at their limit. Try *Free* T0, or check those animals for outliers |
| Everything seems frozen | A calibration is running (see the progress bar). Large numbers of starts take time. Use **Cancel job** if needed |
| Calibration is slow | Use fewer starts to explore, close other heavy programs, and check that parallelism is on (see *Speed on multi-core computers*). Computers with 1 or 2 cores run one law at a time |
| Nothing changed after updating the app | Refresh the page with `Ctrl+F5` to clear the cached interface |

Still stuck? Note the exact message, the layout of your file (first rows) and the steps you
followed, and share them with the project maintainer.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| **Calibration** | Adjusting a model's parameters so that its curve matches the data |
| **Growth law** | An equation describing how a tumour's volume changes over time |
| **T0** | The estimated starting volume of an animal (one per animal) |
| **Start (multistart)** | One optimisation attempt from a random starting point. Several starts reduce the chance of a poor solution |
| **BIC / AICc** | Scores that balance fit quality against model complexity. Lower is better |
| **ΔBIC** | Difference to the best law. Below 2 means a tie |
| **Akaike weight** | Share of support a law receives among the compared laws |
| **RMSE** | Root mean squared error between observed and fitted volumes |
| **MAE** | Mean absolute error |
| **Residual** | Observed value minus fitted value |
| **Control group** | Untreated animals, used to fit natural growth |
| **Treatment term** | The equation describing how a dose slows tumour growth |
| **TGI** | Tumour growth inhibition: how much smaller the treated tumour is than the control at the end |
| **Session** | One working project: imported data, settings and results, saved automatically |
| **Seed** | A number that fixes the random choices so a run can be repeated exactly |
