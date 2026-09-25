"""Metrics used for model selection and validation."""
from __future__ import annotations
import numpy as np


def loglik_gaussian(y: np.ndarray, yhat: np.ndarray) -> float:
    residuals = np.asarray(y, dtype=float) - np.asarray(yhat, dtype=float)
    n = residuals.size
    variance = max(float(np.mean(residuals ** 2)), 1e-12)
    return float(-0.5 * n * (np.log(2 * np.pi * variance) + 1.0))


def _safe_corr(y: np.ndarray, yhat: np.ndarray) -> float:
    if len(y) < 2 or np.std(y) < 1e-12 or np.std(yhat) < 1e-12:
        return 1.0 if np.allclose(y, yhat) else 0.0
    return float(np.corrcoef(y, yhat)[0, 1])


def ccc(y: np.ndarray, yhat: np.ndarray) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    variance = np.var(y) + np.var(yhat) + (np.mean(y) - np.mean(yhat)) ** 2
    return float(2 * np.cov(y, yhat, ddof=0)[0, 1] / variance) if variance > 1e-12 else 1.0


def icc_a1(y: np.ndarray, yhat: np.ndarray) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    values = np.column_stack([y, yhat])
    grand = values.mean()
    row_means = values.mean(axis=1)
    ms_rows = 2 * np.sum((row_means - grand) ** 2) / max(len(y) - 1, 1)
    ms_error = np.sum((values - row_means[:, None]) ** 2) / max(len(y), 1)
    return float((ms_rows - ms_error) / (ms_rows + ms_error + 1e-12))


def metrics_from_predictions(y: np.ndarray, yhat: np.ndarray, k_total: int) -> dict[str, float]:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    n = len(y)
    residuals = y - yhat
    sse = float(np.sum(residuals ** 2))
    mse = sse / max(n, 1)
    ll = loglik_gaussian(y, yhat)
    aic = 2 * k_total - 2 * ll
    bic = k_total * np.log(max(n, 1)) - 2 * ll
    aicc = aic + (2 * k_total * (k_total + 1) / max(n - k_total - 1, 1)) if n > k_total + 1 else float("inf")
    return {"sse": sse, "loglik": ll, "aic": float(aic), "bic": float(bic), "aicc": float(aicc), "rmse": float(np.sqrt(mse)), "mae": float(np.mean(np.abs(residuals))), "wape": float(100 * np.sum(np.abs(residuals)) / max(np.sum(np.abs(y)), 1e-12)), "smape": float(100 * np.mean(2 * np.abs(residuals) / np.maximum(np.abs(y) + np.abs(yhat), 1e-12))), "pcc": _safe_corr(y, yhat), "ccc": ccc(y, yhat), "icc": icc_a1(y, yhat)}


def last_point_error(observed: list[np.ndarray], predicted: list[np.ndarray]) -> dict[str, float]:
    y = np.asarray([values[-1] for values in observed], float)
    yhat = np.asarray([values[-1] for values in predicted], float)
    return {"mae": float(np.mean(np.abs(y - yhat))), "rmse": float(np.sqrt(np.mean((y - yhat) ** 2))), "mape": float(100 * np.mean(np.abs((y - yhat) / np.maximum(np.abs(y), 1e-12))))}
