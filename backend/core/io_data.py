"""Input normalisation for CSV, XLSX, long and wide tables."""
from __future__ import annotations
import io
from pathlib import Path
import numpy as np
import pandas as pd
from .fitting import Dataset


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content))
    sample = content[:4096].decode("utf-8-sig", errors="replace")
    separator = ";" if sample.count(";") > sample.count(",") else ("\t" if sample.count("\t") > sample.count(",") else ",")
    return pd.read_csv(io.BytesIO(content), sep=separator, comment="#")


def _number_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.astype(str).str.replace("\u00a0", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def normalise_table_report(frame: pd.DataFrame, mapping: dict[str, str | None], default_group="control", filename="upload") -> tuple[list[Dataset], list[dict[str, object]]]:
    time_column, volume_column = mapping.get("time"), mapping.get("volume")
    if not time_column:
        raise ValueError("la columns time est obligatoire")
    subject_column, group_column = mapping.get("subject"), mapping.get("group")
    if volume_column is None and subject_column is not None:
        raise ValueError("un format long doit fournir une columns volume")
    if subject_column is None:
        work = frame.copy()
        candidates = [column for column in frame.columns if column != time_column and column != volume_column]
        if candidates:
            rows = []
            for column in candidates:
                rows.append(pd.DataFrame({"__time": _number_series(frame[time_column]), "__volume": _number_series(frame[column]), "__subject": str(column), "__group": default_group}))
            work = pd.concat(rows, ignore_index=True)
        else:
            work["__time"] = _number_series(work[time_column]); work["__volume"] = _number_series(work[volume_column]); work["__subject"] = filename; work["__group"] = default_group
    else:
        work = frame.copy(); work["__time"] = _number_series(work[time_column]); work["__volume"] = _number_series(work[volume_column]); work["__subject"] = work[subject_column].astype(str); work["__group"] = work[group_column].astype(str) if group_column else default_group
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
        item = {"id": str(subject), "group": str(subject_rows["__group"].iloc[0]), "n_points": int(len(valid_rows)), "ok": not reasons}
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
