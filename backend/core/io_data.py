"""Input normalisation for CSV, XLSX, long and wide tables."""
from __future__ import annotations
import io
import os
import re
from pathlib import Path
import numpy as np
import pandas as pd
from .fitting import Dataset


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        frame = pd.read_excel(io.BytesIO(content))
    else:
        sample = content[:4096].decode("utf-8-sig")
        separator = ";" if sample.count(";") > sample.count(",") else ("\t" if sample.count("\t") > sample.count(",") else ",")
        frame = pd.read_csv(io.BytesIO(content), sep=separator, comment="#")
    # "x, y" must give the columns "x" and "y", not "x" and " y".
    frame.columns = [str(column).strip().lstrip("\ufeff") for column in frame.columns]
    return frame


def harmonise_headers(frames: list[pd.DataFrame], names: list[str]) -> tuple[list[pd.DataFrame], list[str]]:
    """Make column names comparable across several uploaded files.

    Spelling differences that only involve case or surrounding spaces ("x" vs
    "X", " y" vs "y") are unified to the first spelling seen. Without this,
    pandas treats them as different columns when the files are concatenated and
    the subject whose file used the other spelling ends up with no data at all.
    Returns the renamed frames and a list of human-readable warnings for files
    whose columns still differ from the first file after unification.
    """
    spelling: dict[str, str] = {}
    result: list[pd.DataFrame] = []
    warnings: list[str] = []
    for frame, name in zip(frames, names):
        mapping = {}
        for column in frame.columns:
            key = str(column).strip().lower()
            mapping[column] = spelling.setdefault(key, str(column).strip())
        renamed = frame.rename(columns=mapping)
        result.append(renamed if not renamed.columns.duplicated().any() else frame)
    reference = list(result[0].columns) if result else []
    for frame, name in zip(result[1:], names[1:]):
        if set(frame.columns) != set(reference):
            warnings.append(f"{name}: columns {list(frame.columns)} differ from the first file {reference}; its rows may be ignored.")
    return result, warnings


def _number_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.astype(str).str.replace("\u00a0", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def _source_label(value: object) -> str:
    return Path(str(value)).stem or "file"


_CONTROL_WORDS = re.compile(r"(ctrl|control|ctl|vehicle|placebo)", re.IGNORECASE)
_REPLICATE_SUFFIX = re.compile(r"[\s_\-]*\d+$")


def infer_groups_from_files(sources: list[object], default_group: str) -> dict[object, str]:
    """Guess one group per file from its name when each file is one subject.

    Only active when at least one file name looks like a control (CTRL,
    control, vehicle...). Control files go to `default_group`; the others get
    their name without the trailing replicate number (..._CART_3 -> ..._CART),
    so a folder mixing controls and treated animals is not calibrated as one
    big control group. If no name looks like a control, everything stays in
    `default_group` as before.
    """
    labels = {source: _source_label(source) for source in sources}
    if not any(_CONTROL_WORDS.search(label) for label in labels.values()):
        return {source: default_group for source in sources}
    # Drop the prefix shared by every file name (e.g. "data_study_fig3D_") so group names stay short.
    prefix = os.path.commonprefix(list(labels.values()))
    prefix = prefix[: prefix.rfind("_") + 1] if "_" in prefix else ""

    def group_of(label: str) -> str:
        if _CONTROL_WORDS.search(label):
            return default_group
        name = _REPLICATE_SUFFIX.sub("", label[len(prefix):])
        return name or _REPLICATE_SUFFIX.sub("", label) or label

    return {source: group_of(label) for source, label in labels.items()}


def normalise_table_report(frame: pd.DataFrame, mapping: dict[str, str | None], default_group="control", filename="upload") -> tuple[list[Dataset], list[dict[str, object]]]:
    time_column, volume_column = mapping.get("time"), mapping.get("volume")
    if not time_column:
        raise ValueError("the time column is required")
    subject_column, group_column = mapping.get("subject"), mapping.get("group")
    if volume_column is None and subject_column is not None:
        raise ValueError("un format long doit fournir une colonne volume")
    source_column = "__source_file" if "__source_file" in frame.columns else None
    if subject_column is None:
        work = frame.copy()
        candidates = [column for column in frame.columns if column not in {time_column, volume_column, source_column}]
        if volume_column is not None and source_column:
            rows = []
            file_groups = infer_groups_from_files(list(frame[source_column].unique()), default_group)
            for source, source_rows in frame.groupby(source_column, sort=False):
                rows.append(pd.DataFrame({"__time": _number_series(source_rows[time_column]), "__volume": _number_series(source_rows[volume_column]), "__subject": _source_label(source), "__group": file_groups[source]}))
            work = pd.concat(rows, ignore_index=True)
        elif candidates:
            rows = []
            for column in candidates:
                subject = str(column)
                if source_column:
                    source = frame[source_column].map(_source_label)
                    subject = source + ":" + subject
                rows.append(pd.DataFrame({"__time": _number_series(frame[time_column]), "__volume": _number_series(frame[column]), "__subject": subject, "__group": default_group}))
            work = pd.concat(rows, ignore_index=True)
        else:
            work["__time"] = _number_series(work[time_column]); work["__volume"] = _number_series(work[volume_column]); work["__subject"] = _source_label(filename) if source_column else filename; work["__group"] = default_group
    else:
        work = frame.copy(); work["__time"] = _number_series(work[time_column]); work["__volume"] = _number_series(work[volume_column]); work["__subject"] = work[subject_column].astype(str); work["__group"] = work[group_column].astype(str) if group_column else default_group
        if source_column:
            work["__subject"] = work[source_column].map(_source_label) + ":" + work["__subject"]
    datasets = []
    validation = []
    for subject, subject_rows in work.groupby("__subject", sort=False):
        valid_rows = subject_rows.dropna(subset=["__time", "__volume"]).sort_values("__time")
        reasons = []
        if len(valid_rows) < 4:
            reasons.append(f"only {len(valid_rows)} valid points, minimum is 4")
        if subject_rows["__time"].isna().any() or subject_rows["__volume"].isna().any():
            reasons.append("time or volume is not numeric")
        if valid_rows["__time"].duplicated().any():
            reasons.append("duplicate times")
        if (valid_rows["__volume"] <= 0).any():
            reasons.append("volume is not positive")
        item = {"id": str(subject), "group": str(subject_rows["__group"].iloc[0]), "n_points": int(len(valid_rows)), "ok": not reasons,
                # Raw points so the Data tab can draw them even for a subject that fails validation.
                "t": [round(value, 6) for value in valid_rows["__time"].tolist()],
                "v": [round(value, 6) for value in valid_rows["__volume"].tolist()]}
        if reasons:
            item["why"] = reasons
        validation.append(item)
        if reasons:
            continue
        datasets.append(Dataset(str(subject), str(valid_rows["__group"].iloc[0]), valid_rows["__time"].to_numpy(float), valid_rows["__volume"].to_numpy(float)))
    if not datasets: raise ValueError("No valid subject")
    return datasets, validation


def normalise_table(frame: pd.DataFrame, mapping: dict[str, str | None], default_group="control", filename="upload") -> list[Dataset]:
    datasets, _ = normalise_table_report(frame, mapping, default_group, filename)
    return datasets
