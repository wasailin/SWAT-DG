"""
Hydrograph diagnostic engine for expert-guided SWAT calibration.

This module analyzes the differences between observed and simulated time series
to identify specific model deficiencies and recommend parameter adjustments.
An experienced SWAT modeler reads a hydrograph and knows which parameters to
tweak based on peak magnitude, baseflow behavior, volume balance, and timing.
This module automates that expert interpretation.

Components:
    A. Baseflow separation (Eckhardt digital filter)
    B. Peak flow analysis (detection, magnitude comparison, timing lag)
    C. Volume balance analysis (total, seasonal, flow-regime)
    D. Parameter-process knowledge base (diagnostic rules)
    E. diagnose() orchestrator → DiagnosticReport

Example:
    >>> import numpy as np
    >>> report = diagnose(observed, simulated, dates)
    >>> print(report.summary())
    >>> for r in report.recommendations:
    ...     print(f"  {r.parameter}: {r.direction} ({r.reason})")
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from swat_modern.calibration.objectives import (
    nse, kge, pbias, rmse, r_squared, log_nse, rsr, evaluate_model,
)


# ---------------------------------------------------------------------------
# A. Baseflow Separation
# ---------------------------------------------------------------------------

def eckhardt_baseflow_filter(
    streamflow: np.ndarray,
    alpha: float = 0.98,
    bfi_max: float = 0.80,
) -> np.ndarray:
    """
    Eckhardt (2005) recursive digital filter for baseflow separation.

    b(t) = ((1 - BFI_max) * alpha * b(t-1) + (1 - alpha) * BFI_max * Q(t))
           / (1 - alpha * BFI_max)

    with the constraint b(t) <= Q(t).

    Args:
        streamflow: Total streamflow array (daily values recommended).
        alpha: Recession constant (0.90-0.99). Higher = slower recession.
            Typical: 0.98 for perennial streams.
        bfi_max: Maximum baseflow index.
            0.25 for ephemeral streams with porous aquifers
            0.50 for perennial streams with hard rock aquifers
            0.80 for perennial streams with porous aquifers (default)

    Returns:
        Baseflow array, same length as streamflow. Always <= streamflow.

    References:
        Eckhardt, K. (2005). How to construct recursive digital filters for
        baseflow separation. Hydrological Processes, 19(2), 507-515.
    """
    Q = np.asarray(streamflow, dtype=np.float64).copy()
    n = len(Q)
    if n == 0:
        return np.array([], dtype=np.float64)

    b = np.zeros(n, dtype=np.float64)
    b[0] = min(Q[0], Q[0] * bfi_max)

    denom = 1.0 - alpha * bfi_max
    for t in range(1, n):
        numerator = (1.0 - bfi_max) * alpha * b[t - 1] + (1.0 - alpha) * bfi_max * Q[t]
        b[t] = numerator / denom
        # Baseflow cannot exceed total flow
        b[t] = min(b[t], Q[t])
        # Baseflow cannot be negative
        b[t] = max(b[t], 0.0)

    return b


def lyne_hollick_filter(
    streamflow: np.ndarray,
    alpha: float = 0.925,
    n_passes: int = 3,
) -> np.ndarray:
    """
    Lyne & Hollick (1979) digital filter for baseflow separation.

    Forward-backward pass repeated n_passes times to remove phase distortion.
    Alternative to Eckhardt filter.

    Args:
        streamflow: Total streamflow array.
        alpha: Filter parameter (0.9-0.95 typical). Higher = more smoothing.
        n_passes: Number of forward-backward passes.

    Returns:
        Baseflow array.
    """
    Q = np.asarray(streamflow, dtype=np.float64).copy()
    n = len(Q)
    if n == 0:
        return np.array([], dtype=np.float64)

    quickflow = np.zeros(n, dtype=np.float64)

    for p in range(n_passes):
        if p % 2 == 0:
            # Forward pass
            quickflow[0] = Q[0] * 0.5
            for t in range(1, n):
                quickflow[t] = alpha * quickflow[t - 1] + (1.0 + alpha) / 2.0 * (Q[t] - Q[t - 1])
                quickflow[t] = max(quickflow[t], 0.0)
                quickflow[t] = min(quickflow[t], Q[t])
        else:
            # Backward pass
            quickflow[n - 1] = Q[n - 1] * 0.5
            for t in range(n - 2, -1, -1):
                quickflow[t] = alpha * quickflow[t + 1] + (1.0 + alpha) / 2.0 * (Q[t] - Q[t + 1])
                quickflow[t] = max(quickflow[t], 0.0)
                quickflow[t] = min(quickflow[t], Q[t])

        # Update Q for next pass
        Q = np.maximum(Q - quickflow, 0.0)

    baseflow = np.asarray(streamflow, dtype=np.float64) - quickflow
    baseflow = np.clip(baseflow, 0.0, streamflow)
    return baseflow


def calculate_bfi(streamflow: np.ndarray, baseflow: np.ndarray) -> float:
    """
    Calculate Baseflow Index (BFI) = sum(baseflow) / sum(total_flow).

    Args:
        streamflow: Total streamflow array.
        baseflow: Baseflow array (from filter).

    Returns:
        BFI value (0 to 1). Higher = more groundwater-dominated.
    """
    total = np.nansum(streamflow)
    if total <= 0:
        return 0.0
    return float(np.nansum(baseflow) / total)


# ---------------------------------------------------------------------------
# B. Peak Flow Analysis
# ---------------------------------------------------------------------------

def detect_peaks(
    streamflow: np.ndarray,
    dates: np.ndarray = None,
    min_distance_days: int = 7,
    prominence_factor: float = 0.3,
) -> pd.DataFrame:
    """
    Detect peak flow events using scipy.signal.find_peaks.

    Args:
        streamflow: Streamflow array.
        dates: Date array (optional, same length as streamflow).
        min_distance_days: Minimum number of timesteps between peaks.
        prominence_factor: Minimum prominence as fraction of flow range.

    Returns:
        DataFrame with columns: index, value, prominence, date (if dates provided).
    """
    from scipy.signal import find_peaks

    Q = np.asarray(streamflow, dtype=np.float64)
    if len(Q) == 0:
        return pd.DataFrame()
    Q_clean = np.where(np.isnan(Q), 0.0, Q)

    flow_range = np.nanmax(Q_clean) - np.nanmin(Q_clean)
    min_prominence = flow_range * prominence_factor if flow_range > 0 else 0

    indices, properties = find_peaks(
        Q_clean,
        distance=min_distance_days,
        prominence=min_prominence,
    )

    records = []
    for i, idx in enumerate(indices):
        rec = {
            "index": int(idx),
            "value": float(Q_clean[idx]),
            "prominence": float(properties["prominences"][i]),
        }
        if dates is not None and idx < len(dates):
            rec["date"] = dates[idx]
        records.append(rec)

    return pd.DataFrame(records)


def compare_peaks(
    observed: np.ndarray,
    simulated: np.ndarray,
    dates: np.ndarray = None,
    min_distance_days: int = 7,
    timing_window_days: int = 3,
    prominence_factor: float = 0.3,
) -> Dict:
    """
    Compare observed vs simulated peak events.

    Matches peaks by proximity in time (within timing_window_days).

    Args:
        observed: Observed streamflow array.
        simulated: Simulated streamflow array.
        dates: Date array (optional).
        min_distance_days: Minimum distance between peaks.
        timing_window_days: Maximum days offset to consider a match.
        prominence_factor: Minimum prominence for peak detection.

    Returns:
        Dict with:
            peak_magnitude_ratio: median(sim_peak / obs_peak) for matched peaks
            peak_timing_error_days: median timing offset (+ve = sim lags obs)
            n_matched: number of matched peak pairs
            n_missed: observed peaks not matched in simulated
            n_false: simulated peaks not matched in observed
            peak_pairs: list of dicts with obs/sim peak info
    """
    obs_peaks = detect_peaks(observed, dates, min_distance_days, prominence_factor)
    sim_peaks = detect_peaks(simulated, dates, min_distance_days, prominence_factor)

    if obs_peaks.empty or sim_peaks.empty:
        return {
            "peak_magnitude_ratio": np.nan,
            "peak_timing_error_days": np.nan,
            "n_matched": 0,
            "n_missed": len(obs_peaks),
            "n_false": len(sim_peaks),
            "peak_pairs": [],
        }

    obs_indices = obs_peaks["index"].values
    sim_indices = sim_peaks["index"].values
    obs_values = obs_peaks["value"].values
    sim_values = sim_peaks["value"].values

    matched_pairs = []
    matched_sim = set()

    for i, obs_idx in enumerate(obs_indices):
        # Find closest simulated peak within window
        offsets = sim_indices - obs_idx
        within_window = np.abs(offsets) <= timing_window_days
        candidates = np.where(within_window)[0]

        if len(candidates) == 0:
            continue

        # Pick the closest candidate not yet matched
        best_j = None
        best_dist = timing_window_days + 1
        for j in candidates:
            if j not in matched_sim and abs(offsets[j]) < best_dist:
                best_dist = abs(offsets[j])
                best_j = j

        if best_j is not None:
            matched_sim.add(best_j)
            pair = {
                "obs_index": int(obs_idx),
                "sim_index": int(sim_indices[best_j]),
                "obs_value": float(obs_values[i]),
                "sim_value": float(sim_values[best_j]),
                "timing_error": int(sim_indices[best_j] - obs_idx),
                "magnitude_ratio": float(sim_values[best_j] / obs_values[i]) if obs_values[i] > 0 else np.nan,
            }
            if dates is not None:
                pair["obs_date"] = dates[obs_idx] if obs_idx < len(dates) else None
                pair["sim_date"] = dates[sim_indices[best_j]] if sim_indices[best_j] < len(dates) else None
            matched_pairs.append(pair)

    n_matched = len(matched_pairs)
    n_missed = len(obs_peaks) - n_matched
    n_false = len(sim_peaks) - n_matched

    if n_matched > 0:
        ratios = [p["magnitude_ratio"] for p in matched_pairs if not np.isnan(p["magnitude_ratio"])]
        offsets = [p["timing_error"] for p in matched_pairs]
        peak_magnitude_ratio = float(np.median(ratios)) if ratios else np.nan
        peak_timing_error = float(np.median(offsets))
    else:
        peak_magnitude_ratio = np.nan
        peak_timing_error = np.nan

    return {
        "peak_magnitude_ratio": peak_magnitude_ratio,
        "peak_timing_error_days": peak_timing_error,
        "n_matched": n_matched,
        "n_missed": n_missed,
        "n_false": n_false,
        "peak_pairs": matched_pairs,
    }


# ---------------------------------------------------------------------------
# C. Volume Balance Analysis
# ---------------------------------------------------------------------------

def volume_balance(
    observed: np.ndarray,
    simulated: np.ndarray,
    dates: np.ndarray = None,
) -> Dict:
    """
    Calculate volume balance metrics between observed and simulated flows.

    Args:
        observed: Observed flow values.
        simulated: Simulated flow values.
        dates: Date array (pd.DatetimeIndex or array of datetime).
            Required for seasonal and annual breakdown.

    Returns:
        Dict with:
            total_volume_ratio: sum(sim) / sum(obs)
            total_pbias: percent bias
            seasonal_bias: {season: pbias} if dates provided
            high_flow_bias: pbias for flows > Q25 (top 25% flows)
            low_flow_bias: pbias for flows < Q75 (bottom 25% flows)
            annual_bias: {year: pbias} if dates provided
    """
    obs = np.asarray(observed, dtype=np.float64)
    sim = np.asarray(simulated, dtype=np.float64)

    # Remove NaN pairs
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    result = {}

    # Total volume
    sum_obs = np.sum(obs)
    sum_sim = np.sum(sim)
    result["total_volume_ratio"] = float(sum_sim / sum_obs) if sum_obs > 0 else np.nan
    result["total_pbias"] = float(100.0 * (sum_obs - sum_sim) / sum_obs) if sum_obs > 0 else np.nan

    # Flow-regime based metrics (using percentiles of observed)
    if len(obs) > 10:
        q25 = np.percentile(obs, 75)  # Q25 exceedance = 75th percentile value
        q75 = np.percentile(obs, 25)  # Q75 exceedance = 25th percentile value

        # High flows (above Q25 exceedance)
        high_mask = obs >= q25
        if np.sum(high_mask) > 0:
            result["high_flow_bias"] = float(
                100.0 * (np.sum(obs[high_mask]) - np.sum(sim[high_mask])) / np.sum(obs[high_mask])
            )
        else:
            result["high_flow_bias"] = np.nan

        # Low flows (below Q75 exceedance)
        low_mask = obs <= q75
        if np.sum(low_mask) > 0 and np.sum(obs[low_mask]) > 0:
            result["low_flow_bias"] = float(
                100.0 * (np.sum(obs[low_mask]) - np.sum(sim[low_mask])) / np.sum(obs[low_mask])
            )
        else:
            result["low_flow_bias"] = np.nan
    else:
        result["high_flow_bias"] = np.nan
        result["low_flow_bias"] = np.nan

    # Seasonal and annual breakdowns require dates
    if dates is not None:
        dates_clean = np.asarray(dates)[mask] if len(dates) > len(obs) - np.sum(~mask) else np.asarray(dates)[:len(obs)]
        try:
            dt_index = pd.DatetimeIndex(dates_clean)
        except Exception:
            result["seasonal_bias"] = {}
            result["annual_bias"] = {}
            return result

        # Seasonal bias
        season_map = {12: "DJF", 1: "DJF", 2: "DJF",
                      3: "MAM", 4: "MAM", 5: "MAM",
                      6: "JJA", 7: "JJA", 8: "JJA",
                      9: "SON", 10: "SON", 11: "SON"}
        months = dt_index.month
        seasonal_bias = {}
        for season in ["DJF", "MAM", "JJA", "SON"]:
            s_mask = np.array([season_map.get(m) == season for m in months])
            if np.sum(s_mask) > 0 and np.sum(obs[s_mask]) > 0:
                seasonal_bias[season] = float(
                    100.0 * (np.sum(obs[s_mask]) - np.sum(sim[s_mask])) / np.sum(obs[s_mask])
                )
        result["seasonal_bias"] = seasonal_bias

        # Annual bias
        years = dt_index.year
        annual_bias = {}
        for year in sorted(set(years)):
            y_mask = years == year
            if np.sum(y_mask) > 0 and np.sum(obs[y_mask]) > 0:
                annual_bias[int(year)] = float(
                    100.0 * (np.sum(obs[y_mask]) - np.sum(sim[y_mask])) / np.sum(obs[y_mask])
                )
        result["annual_bias"] = annual_bias
    else:
        result["seasonal_bias"] = {}
        result["annual_bias"] = {}

    return result


# ---------------------------------------------------------------------------
# C2. Flow Duration Curve Metrics (Yilmaz et al. 2008)
# ---------------------------------------------------------------------------

def flow_duration_curve_metrics(
    observed: np.ndarray,
    simulated: np.ndarray,
) -> Dict[str, float]:
    """
    Calculate FDC-based signature metrics (Yilmaz et al. 2008).

    Three metrics decompose FDC bias into flow regimes:
    - FHV: % bias of high flows (top 2% exceedance) — captures peak volume
    - FMS: % bias of mid-segment FDC slope (20-70%) — captures drainage behavior
    - FLV: % bias of low flows (bottom 30%) — captures baseflow volume

    Args:
        observed: Observed flow array.
        simulated: Simulated flow array (same length).

    Returns:
        Dict with keys "FHV", "FMS", "FLV". Values are % bias
        (0 = perfect, positive = sim overestimates).

    Reference:
        Yilmaz, K.K., Gupta, H.V., Wagener, T. (2008). A process-based
        diagnostic approach to model evaluation. Water Resources Research,
        44(1), W01442.
    """
    obs = np.asarray(observed, dtype=np.float64)
    sim = np.asarray(simulated, dtype=np.float64)
    n = len(obs)

    # Sort descending for exceedance probabilities
    obs_sorted = np.sort(obs)[::-1]
    sim_sorted = np.sort(sim)[::-1]

    # FHV: high-flow volume — sum of top 2%
    h = max(1, int(np.ceil(0.02 * n)))
    obs_high = np.sum(obs_sorted[:h])
    fhv = ((np.sum(sim_sorted[:h]) - obs_high) / obs_high * 100.0
           if obs_high > 0 else 0.0)

    # FMS: mid-segment slope (between 20% and 70% exceedance)
    # Slope of the log-FDC between these exceedance probabilities
    idx_20 = max(0, int(np.round(0.2 * n)) - 1)
    idx_70 = min(n - 1, int(np.round(0.7 * n)) - 1)

    eps = 1e-6  # avoid log(0)
    obs_slope = (np.log(obs_sorted[idx_20] + eps) - np.log(obs_sorted[idx_70] + eps))
    sim_slope = (np.log(sim_sorted[idx_20] + eps) - np.log(sim_sorted[idx_70] + eps))
    fms = ((sim_slope - obs_slope) / obs_slope * 100.0
           if abs(obs_slope) > eps else 0.0)

    # FLV: low-flow volume — sum of log-transformed bottom 30%
    l_start = int(np.round(0.7 * n))
    obs_low = obs_sorted[l_start:]
    sim_low = sim_sorted[l_start:]

    obs_log_sum = np.sum(np.log(obs_low + eps))
    sim_log_sum = np.sum(np.log(sim_low + eps))
    flv = ((sim_log_sum - obs_log_sum) / obs_log_sum * -100.0
           if abs(obs_log_sum) > eps else 0.0)

    return {"FHV": fhv, "FMS": fms, "FLV": flv}


# ---------------------------------------------------------------------------
# C3. KGE Component Helper
# ---------------------------------------------------------------------------

def kge_components(
    observed: np.ndarray,
    simulated: np.ndarray,
) -> Dict[str, float]:
    """
    Extract KGE and its decomposed components.

    Convenience wrapper around ``kge(return_components=True)`` for use
    by the diagnostic calibrator.

    Returns:
        Dict with keys "kge", "r" (correlation), "alpha" (variability ratio),
        "beta" (bias ratio).
    """
    result = kge(observed, simulated, return_components=True)
    kge_val, r, alpha, beta = result
    return {"kge": kge_val, "r": r, "alpha": alpha, "beta": beta}


# ---------------------------------------------------------------------------
# C4. Magnitude Estimation for Diagnostic Calibration
# ---------------------------------------------------------------------------

def estimate_adjustment(
    parameter: str,
    direction: str,
    error_magnitude: float,
    param_range: Tuple[float, float],
    sensitivity_weight: float = 0.5,
    history: Optional[List[Dict]] = None,
    damping: float = 0.5,
    n_concurrent: int = 1,
) -> float:
    """
    Estimate how much to adjust a parameter to correct a metric error.

    Two strategies:
    1. **Proportional heuristic** (first iteration, no history):
       ``adjustment = sign * normalized_error * sensitivity_weight * 0.15 * range_width``
       where ``normalized_error = min(|error|, 1.0)`` — errors on a percentage
       scale (like PBIAS, which can be 0-100+) are divided by 100 first so
       the heuristic stays in a sensible range.
    2. **Secant method** (subsequent iterations, with history):
       Uses two (param, metric) pairs to linearly interpolate the needed step:
       ``slope = (metric2 - metric1) / (param2 - param1)``
       ``adjustment = damping * (target_metric - current_metric) / slope``

    When multiple parameters are adjusted simultaneously (``n_concurrent > 1``),
    both the proportional heuristic and the secant result are divided by
    ``n_concurrent`` so their combined effect approximates a single-parameter
    step.  This prevents compounding overshoots (e.g. ESCO + CN2 both at
    max step doubling the intended flow reduction).

    The result is clamped to +/-10% of the parameter range to prevent divergence.

    Args:
        parameter: Parameter name (for logging only).
        direction: "increase" or "decrease" — sign of the first-iteration heuristic.
        error_magnitude: Signed error to correct (e.g. PBIAS value, 1 - BFI_ratio).
            For the secant method this is the current metric value and the
            target is 0 (for PBIAS) or 1.0 (for ratios).
        param_range: (min_value, max_value) tuple.
        sensitivity_weight: Scaling factor for proportional heuristic (0-1).
            Higher = more aggressive first step.
        history: List of dicts with keys "param_value" and "metric_value"
            from previous iterations. If len >= 2, secant method is used.
        damping: Damping factor for secant method (0-1). Lower = more cautious.
        n_concurrent: Number of parameters being adjusted in the same step.
            Adjustments are divided by this to prevent compounding.

    Returns:
        Signed adjustment to add to the current parameter value.
    """
    range_width = param_range[1] - param_range[0]
    max_step = 0.10 * range_width  # never jump more than 10% of range

    sign = 1.0 if direction == "increase" else -1.0

    # Normalize error for the proportional heuristic.  PBIAS is on a 0-100+
    # scale while ratio metrics (BFI, peak) are 0-2.  Without normalising,
    # a PBIAS of 30 produces 30x larger raw adjustment than an equivalent
    # ratio error of 0.30, always saturating at max_step.
    abs_error = abs(error_magnitude)
    if abs_error > 2.0:
        # Likely a percentage-scale metric (PBIAS).  Convert to fraction.
        normalized_error = abs_error / 100.0
    else:
        normalized_error = abs_error

    if history is not None and len(history) >= 2:
        # Secant method: use last two data points
        h1, h2 = history[-2], history[-1]
        dp = h2["param_value"] - h1["param_value"]
        dm = h2["metric_value"] - h1["metric_value"]

        if abs(dp) < 1e-12 or abs(dm) < 1e-12:
            # Degenerate case: fall back to proportional
            adjustment = sign * normalized_error * sensitivity_weight * 0.15 * range_width
        else:
            slope = dm / dp
            # Target is 0 for error-type metrics (PBIAS, timing offset)
            # error_magnitude here is the current metric value
            adjustment = damping * (-error_magnitude) / slope
    else:
        # Proportional heuristic
        adjustment = sign * normalized_error * sensitivity_weight * 0.15 * range_width

    # Scale down when multiple parameters are adjusted simultaneously so
    # their combined effect doesn't overshoot.
    if n_concurrent > 1:
        adjustment /= n_concurrent

    # Clamp to prevent divergence
    return max(-max_step, min(max_step, adjustment))


# ---------------------------------------------------------------------------
# D. Parameter-Process Knowledge Base
# ---------------------------------------------------------------------------

@dataclass
class DiagnosticRule:
    """A diagnostic rule mapping a hydrograph finding to parameter suggestions."""
    condition_name: str
    description: str
    parameters: List[str]
    directions: List[str]  # "increase" or "decrease" per parameter
    confidence: str  # "high", "medium", "low"
    category: str  # "peaks", "baseflow", "volume", "timing", "seasonal", "sediment", "phosphorus", "nitrogen"


@dataclass
class ParameterRecommendation:
    """A single parameter adjustment recommendation."""
    parameter: str
    direction: str  # "increase" or "decrease"
    reason: str
    confidence: str
    category: str


# Thresholds for triggering diagnostic rules
DIAGNOSTIC_THRESHOLDS = {
    "peak_magnitude_high": 1.20,  # sim/obs peak ratio above this = overestimation
    "peak_magnitude_low": 0.80,   # below this = underestimation
    "peak_timing_late": 1.0,      # days (positive = late)
    "peak_timing_early": -1.0,    # days (negative = early)
    "bfi_ratio_high": 1.20,       # sim/obs BFI ratio above this = too much baseflow
    "bfi_ratio_low": 0.80,        # below this = too little baseflow
    "volume_over": -10.0,         # PBIAS below -10 = overestimation (PBIAS convention: pos=under)
    "volume_under": 10.0,         # PBIAS above 10 = underestimation
    "seasonal_threshold": 15.0,   # abs(PBIAS) > 15% for seasonal diagnosis
    "recession_fast_ratio": 0.70, # sim recession rate / obs recession rate > this = too fast
    "recession_slow_ratio": 1.30,
    # Sediment thresholds
    "rating_slope_high": 1.30,
    "rating_slope_low": 0.70,
    "event_sed_ratio_high": 1.20,
    "event_sed_ratio_low": 0.80,
    "sed_timing_threshold": 2.0,
    # Phosphorus thresholds
    "p_highflow_bias_threshold": 20.0,
    "p_lowflow_bias_threshold": 20.0,
    # Nitrogen thresholds
    "n_highflow_bias_threshold": 20.0,
    "n_lowflow_bias_threshold": 20.0,
}

# The knowledge base: rules mapping diagnostic findings to parameters
DIAGNOSTIC_RULES: List[DiagnosticRule] = [
    # --- Peak flow rules ---
    DiagnosticRule(
        condition_name="peak_overestimation",
        description="Simulated peaks are too high (>{:.0f}% above observed)".format(
            (DIAGNOSTIC_THRESHOLDS["peak_magnitude_high"] - 1) * 100
        ),
        parameters=["CN2", "SURLAG"],
        directions=["decrease", "increase"],
        confidence="high",
        category="peaks",
    ),
    DiagnosticRule(
        condition_name="peak_underestimation",
        description="Simulated peaks are too low (>{:.0f}% below observed)".format(
            (1 - DIAGNOSTIC_THRESHOLDS["peak_magnitude_low"]) * 100
        ),
        parameters=["CN2", "SURLAG"],
        directions=["increase", "decrease"],
        confidence="high",
        category="peaks",
    ),

    # --- Baseflow rules ---
    DiagnosticRule(
        condition_name="baseflow_too_low",
        description="Simulated baseflow is too low (BFI ratio < {:.2f})".format(
            DIAGNOSTIC_THRESHOLDS["bfi_ratio_low"]
        ),
        parameters=["GWQMN", "ALPHA_BF", "GW_DELAY", "RCHRG_DP"],
        directions=["decrease", "increase", "decrease", "decrease"],
        confidence="high",
        category="baseflow",
    ),
    DiagnosticRule(
        condition_name="baseflow_too_high",
        description="Simulated baseflow is too high (BFI ratio > {:.2f})".format(
            DIAGNOSTIC_THRESHOLDS["bfi_ratio_high"]
        ),
        parameters=["GWQMN", "ALPHA_BF", "GW_DELAY", "RCHRG_DP"],
        directions=["increase", "decrease", "increase", "increase"],
        confidence="high",
        category="baseflow",
    ),
    DiagnosticRule(
        condition_name="recession_too_fast",
        description="Post-peak recession is too fast",
        parameters=["ALPHA_BF", "GW_DELAY", "SOL_AWC"],
        directions=["decrease", "increase", "increase"],
        confidence="medium",
        category="baseflow",
    ),
    DiagnosticRule(
        condition_name="recession_too_slow",
        description="Post-peak recession is too slow",
        parameters=["ALPHA_BF", "GW_DELAY", "SOL_AWC"],
        directions=["increase", "decrease", "decrease"],
        confidence="medium",
        category="baseflow",
    ),

    # --- Volume balance rules ---
    DiagnosticRule(
        condition_name="volume_overestimation",
        description="Total simulated volume >10% above observed",
        parameters=["ESCO", "CN2", "EPCO", "CANMX"],
        directions=["decrease", "decrease", "increase", "increase"],
        confidence="medium",
        category="volume",
    ),
    DiagnosticRule(
        condition_name="volume_underestimation",
        description="Total simulated volume >10% below observed",
        parameters=["ESCO", "CN2", "EPCO"],
        directions=["increase", "increase", "decrease"],
        confidence="medium",
        category="volume",
    ),

    # --- Timing rules ---
    DiagnosticRule(
        condition_name="peak_timing_late",
        description="Simulated peaks arrive late (>1 day average lag)",
        parameters=["SURLAG", "CH_N2", "OV_N"],
        directions=["increase", "decrease", "decrease"],
        confidence="medium",
        category="timing",
    ),
    DiagnosticRule(
        condition_name="peak_timing_early",
        description="Simulated peaks arrive early (>1 day average lead)",
        parameters=["SURLAG", "CH_N2", "OV_N"],
        directions=["decrease", "increase", "increase"],
        confidence="medium",
        category="timing",
    ),

    # --- Seasonal rules ---
    DiagnosticRule(
        condition_name="summer_overestimation",
        description="Summer (JJA) flow volume significantly overestimated",
        parameters=["ESCO", "EPCO", "GW_REVAP", "REVAPMN"],
        directions=["decrease", "decrease", "increase", "decrease"],
        confidence="medium",
        category="seasonal",
    ),
    DiagnosticRule(
        condition_name="summer_underestimation",
        description="Summer (JJA) flow volume significantly underestimated",
        parameters=["ESCO", "EPCO", "GW_REVAP"],
        directions=["increase", "increase", "decrease"],
        confidence="medium",
        category="seasonal",
    ),
    DiagnosticRule(
        condition_name="winter_underestimation",
        description="Winter (DJF) flow volume significantly underestimated (possible snow issue)",
        parameters=["SFTMP", "SMTMP", "SMFMX"],
        directions=["increase", "decrease", "increase"],
        confidence="medium",
        category="seasonal",
    ),
    DiagnosticRule(
        condition_name="winter_overestimation",
        description="Winter (DJF) flow volume significantly overestimated (possible snow issue)",
        parameters=["SFTMP", "SMTMP", "SMFMN"],
        directions=["decrease", "increase", "decrease"],
        confidence="medium",
        category="seasonal",
    ),

    # --- Sediment rules ---
    DiagnosticRule(
        condition_name="sediment_overestimation",
        description="Simulated sediment load is too high",
        parameters=["USLE_P", "SPCON", "CH_COV1"],
        directions=["decrease", "decrease", "increase"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sediment_underestimation",
        description="Simulated sediment load is too low",
        parameters=["USLE_P", "SPCON", "CH_COV2"],
        directions=["increase", "increase", "decrease"],
        confidence="medium",
        category="sediment",
    ),

    # --- Sediment process-specific rules ---
    DiagnosticRule(
        condition_name="sed_rating_too_steep",
        description="Sediment rating curve slope ratio > 1.30: overresponse to high flows",
        parameters=["USLE_P", "USLE_K"],
        directions=["decrease", "decrease"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_rating_too_flat",
        description="Sediment rating curve slope ratio < 0.70: underresponse to high flows",
        parameters=["SPCON", "CH_COV1"],
        directions=["increase", "increase"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_event_too_high",
        description="Event sediment fraction too high (ratio > 1.20)",
        parameters=["SPCON", "SPEXP"],
        directions=["decrease", "decrease"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_event_too_low",
        description="Event sediment fraction too low (ratio < 0.80)",
        parameters=["SPCON", "SPEXP"],
        directions=["increase", "increase"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_spring_over",
        description="Spring (MAM) sediment significantly overestimated",
        parameters=["USLE_P"],
        directions=["decrease"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_spring_under",
        description="Spring (MAM) sediment significantly underestimated",
        parameters=["USLE_P"],
        directions=["increase"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_timing_late",
        description="Sediment peak arrives late relative to flow peak (lag diff > 2 days)",
        parameters=["PRF", "ADJ_PKR"],
        directions=["decrease", "decrease"],
        confidence="medium",
        category="sediment",
    ),
    DiagnosticRule(
        condition_name="sed_timing_early",
        description="Sediment peak arrives early relative to flow peak (lag diff < -2 days)",
        parameters=["PRF", "ADJ_PKR"],
        directions=["increase", "increase"],
        confidence="medium",
        category="sediment",
    ),

    # --- Phosphorus rules ---
    DiagnosticRule(
        condition_name="p_highflow_over",
        description="High-flow phosphorus significantly overestimated (particulate P too high)",
        parameters=["ERORGP", "PPERCO"],
        directions=["decrease", "decrease"],
        confidence="medium",
        category="phosphorus",
    ),
    DiagnosticRule(
        condition_name="p_highflow_under",
        description="High-flow phosphorus significantly underestimated (particulate P too low)",
        parameters=["ERORGP", "PPERCO"],
        directions=["increase", "increase"],
        confidence="medium",
        category="phosphorus",
    ),
    DiagnosticRule(
        condition_name="p_lowflow_over",
        description="Low-flow phosphorus significantly overestimated (dissolved P too high)",
        parameters=["GWSOLP", "PSP"],
        directions=["decrease", "decrease"],
        confidence="medium",
        category="phosphorus",
    ),
    DiagnosticRule(
        condition_name="p_lowflow_under",
        description="Low-flow phosphorus significantly underestimated (dissolved P too low)",
        parameters=["GWSOLP", "PSP"],
        directions=["increase", "increase"],
        confidence="medium",
        category="phosphorus",
    ),
    DiagnosticRule(
        condition_name="p_spring_over",
        description="Spring (MAM) phosphorus significantly overestimated",
        parameters=["PSP", "PHOSKD"],
        directions=["decrease", "increase"],
        confidence="medium",
        category="phosphorus",
    ),
    DiagnosticRule(
        condition_name="p_summer_under",
        description="Summer (JJA) phosphorus significantly underestimated",
        parameters=["P_UPDIS"],
        directions=["decrease"],
        confidence="medium",
        category="phosphorus",
    ),

    # --- Nitrogen rules ---
    DiagnosticRule(
        condition_name="n_overestimation",
        description="Total nitrogen significantly overestimated",
        parameters=["ERORGN", "NPERCO", "CMN"],
        directions=["decrease", "decrease", "decrease"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_underestimation",
        description="Total nitrogen significantly underestimated",
        parameters=["NPERCO", "CMN", "ERORGN"],
        directions=["increase", "increase", "increase"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_highflow_over",
        description="High-flow nitrogen significantly overestimated (particulate/organic N too high)",
        parameters=["ERORGN"],
        directions=["decrease"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_highflow_under",
        description="High-flow nitrogen significantly underestimated (particulate/organic N too low)",
        parameters=["ERORGN"],
        directions=["increase"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_lowflow_over",
        description="Low-flow nitrogen significantly overestimated (dissolved NO3 in baseflow too high)",
        parameters=["NPERCO", "CDN"],
        directions=["decrease", "increase"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_lowflow_under",
        description="Low-flow nitrogen significantly underestimated (dissolved NO3 in baseflow too low)",
        parameters=["NPERCO", "CDN"],
        directions=["increase", "decrease"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_spring_over",
        description="Spring (MAM) nitrogen significantly overestimated (mineralization/runoff)",
        parameters=["CMN", "NPERCO"],
        directions=["decrease", "decrease"],
        confidence="medium",
        category="nitrogen",
    ),
    DiagnosticRule(
        condition_name="n_summer_under",
        description="Summer (JJA) nitrogen significantly underestimated (plant uptake effect)",
        parameters=["N_UPDIS"],
        directions=["decrease"],
        confidence="medium",
        category="nitrogen",
    ),
]

# Build lookup for fast access
_RULES_BY_NAME = {r.condition_name: r for r in DIAGNOSTIC_RULES}


def _estimate_recession_rate(
    streamflow: np.ndarray,
    baseflow: np.ndarray,
) -> float:
    """Estimate average recession rate from post-peak quickflow decay.

    Returns the median ratio of Q(t)/Q(t-1) during recession periods
    (when quickflow is decreasing). Values < 1 indicate recession.
    """
    quickflow = streamflow - baseflow
    if len(quickflow) < 3:
        return np.nan

    # Recession = consecutive decreasing quickflow
    ratios = []
    for t in range(1, len(quickflow)):
        if quickflow[t - 1] > 0 and quickflow[t] < quickflow[t - 1]:
            ratios.append(quickflow[t] / quickflow[t - 1])

    return float(np.median(ratios)) if ratios else np.nan


# ---------------------------------------------------------------------------
# D2. Sediment and Phosphorus Diagnostic Helpers
# ---------------------------------------------------------------------------

def _seasonal_pbias(
    dates: np.ndarray,
    obs: np.ndarray,
    sim: np.ndarray,
) -> Dict[str, float]:
    """Compute PBIAS per meteorological season.

    Seasons: DJF (winter), MAM (spring), JJA (summer), SON (fall).

    Args:
        dates: Array of datetime-like objects.
        obs: Observed values.
        sim: Simulated values.

    Returns:
        Dict mapping season name to PBIAS (%). Positive = underestimation.
    """
    dates_pd = pd.DatetimeIndex(dates)
    months = dates_pd.month

    season_map = {
        "DJF": [12, 1, 2],
        "MAM": [3, 4, 5],
        "JJA": [6, 7, 8],
        "SON": [9, 10, 11],
    }

    result = {}
    for season_name, month_list in season_map.items():
        mask = np.isin(months, month_list)
        if mask.sum() > 0:
            obs_s = obs[mask]
            sim_s = sim[mask]
            total_obs = np.sum(obs_s)
            if total_obs > 0:
                result[season_name] = float(
                    100.0 * (np.sum(obs_s) - np.sum(sim_s)) / total_obs
                )
            else:
                result[season_name] = 0.0
    return result


def sediment_rating_curve_analysis(
    obs_flow: np.ndarray,
    obs_sed: np.ndarray,
    sim_flow: np.ndarray,
    sim_sed: np.ndarray,
) -> Dict:
    """Log-log regression of sediment vs flow for observed and simulated.

    Compares the power-law exponent (slope in log-log space) between
    observed and simulated sediment-discharge relationships.

    Args:
        obs_flow: Observed flow array.
        obs_sed: Observed sediment array.
        sim_flow: Simulated flow array.
        sim_sed: Simulated sediment array.

    Returns:
        Dict with obs_slope, sim_slope, slope_ratio (sim/obs).
    """
    result = {"obs_slope": np.nan, "sim_slope": np.nan, "slope_ratio": np.nan}

    # Observed rating curve
    obs_valid = (obs_flow > 0) & (obs_sed > 0)
    if np.sum(obs_valid) > 10:
        log_q = np.log10(obs_flow[obs_valid])
        log_s = np.log10(obs_sed[obs_valid])
        coeffs = np.polyfit(log_q, log_s, 1)
        result["obs_slope"] = float(coeffs[0])

    # Simulated rating curve
    sim_valid = (sim_flow > 0) & (sim_sed > 0)
    if np.sum(sim_valid) > 10:
        log_q = np.log10(sim_flow[sim_valid])
        log_s = np.log10(sim_sed[sim_valid])
        coeffs = np.polyfit(log_q, log_s, 1)
        result["sim_slope"] = float(coeffs[0])

    # Slope ratio
    if not np.isnan(result["obs_slope"]) and not np.isnan(result["sim_slope"]):
        if abs(result["obs_slope"]) > 1e-6:
            result["slope_ratio"] = result["sim_slope"] / result["obs_slope"]

    return result


def sediment_event_partition(
    flow: np.ndarray,
    obs_sed: np.ndarray,
    sim_sed: np.ndarray,
    flow_threshold_pct: float = 75,
) -> Dict:
    """Split sediment into high-flow (event) and low-flow (baseflow) fractions.

    Args:
        flow: Flow array used for partitioning.
        obs_sed: Observed sediment array.
        sim_sed: Simulated sediment array.
        flow_threshold_pct: Percentile threshold separating event from baseflow.

    Returns:
        Dict with obs_event_frac, sim_event_frac, event_ratio (sim/obs).
    """
    threshold = np.percentile(flow, flow_threshold_pct)
    high = flow >= threshold

    obs_total = np.sum(obs_sed)
    sim_total = np.sum(sim_sed)

    result = {
        "obs_event_frac": np.nan,
        "sim_event_frac": np.nan,
        "event_ratio": np.nan,
    }

    if obs_total > 0:
        result["obs_event_frac"] = float(np.sum(obs_sed[high]) / obs_total)
    if sim_total > 0:
        result["sim_event_frac"] = float(np.sum(sim_sed[high]) / sim_total)

    if not np.isnan(result["obs_event_frac"]) and result["obs_event_frac"] > 0:
        result["event_ratio"] = result["sim_event_frac"] / result["obs_event_frac"]

    return result


def sediment_timing_analysis(
    obs_flow: np.ndarray,
    obs_sed: np.ndarray,
    sim_flow: np.ndarray,
    sim_sed: np.ndarray,
) -> Dict:
    """Cross-correlation lag analysis between sediment and flow peaks.

    Computes the lag (in time steps) of maximum cross-correlation between
    flow and sediment for both observed and simulated, then reports the
    difference.

    Args:
        obs_flow: Observed flow array.
        obs_sed: Observed sediment array.
        sim_flow: Simulated flow array.
        sim_sed: Simulated sediment array.

    Returns:
        Dict with obs_lag, sim_lag, lag_diff (sim_lag - obs_lag).
    """
    result = {"obs_lag": np.nan, "sim_lag": np.nan, "lag_diff": np.nan}

    max_lag = min(30, len(obs_flow) // 4)
    if max_lag < 1:
        return result

    def _xcorr_lag(x, y, max_lag):
        """Find lag of maximum cross-correlation."""
        x_norm = (x - np.mean(x)) / (np.std(x) + 1e-10)
        y_norm = (y - np.mean(y)) / (np.std(y) + 1e-10)
        best_lag = 0
        best_corr = -np.inf
        for lag in range(-max_lag, max_lag + 1):
            if lag >= 0:
                corr = np.mean(x_norm[lag:] * y_norm[:len(y_norm) - lag]) if lag < len(x) else 0
            else:
                corr = np.mean(x_norm[:len(x_norm) + lag] * y_norm[-lag:]) if -lag < len(y) else 0
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        return best_lag

    if np.std(obs_flow) > 1e-10 and np.std(obs_sed) > 1e-10:
        result["obs_lag"] = float(_xcorr_lag(obs_flow, obs_sed, max_lag))

    if np.std(sim_flow) > 1e-10 and np.std(sim_sed) > 1e-10:
        result["sim_lag"] = float(_xcorr_lag(sim_flow, sim_sed, max_lag))

    if not np.isnan(result["obs_lag"]) and not np.isnan(result["sim_lag"]):
        result["lag_diff"] = result["sim_lag"] - result["obs_lag"]

    return result


def phosphorus_flow_partition(
    flow: np.ndarray,
    obs_p: np.ndarray,
    sim_p: np.ndarray,
    threshold_pct: float = 75,
) -> Dict:
    """Split phosphorus into high-flow (particulate) and low-flow (dissolved) periods.

    Args:
        flow: Flow array for partitioning.
        obs_p: Observed phosphorus array.
        sim_p: Simulated phosphorus array.
        threshold_pct: Percentile threshold.

    Returns:
        Dict with highflow_pbias, lowflow_pbias, obs_highflow_frac, sim_highflow_frac.
    """
    threshold = np.percentile(flow, threshold_pct)
    high = flow >= threshold
    low = ~high

    result = {
        "highflow_pbias": np.nan,
        "lowflow_pbias": np.nan,
        "obs_highflow_frac": np.nan,
        "sim_highflow_frac": np.nan,
    }

    obs_high_sum = np.sum(obs_p[high])
    obs_low_sum = np.sum(obs_p[low])
    obs_total = np.sum(obs_p)

    if obs_high_sum > 0:
        result["highflow_pbias"] = float(
            100.0 * (obs_high_sum - np.sum(sim_p[high])) / obs_high_sum
        )
    if obs_low_sum > 0:
        result["lowflow_pbias"] = float(
            100.0 * (obs_low_sum - np.sum(sim_p[low])) / obs_low_sum
        )
    if obs_total > 0:
        result["obs_highflow_frac"] = float(obs_high_sum / obs_total)
    sim_total = np.sum(sim_p)
    if sim_total > 0:
        result["sim_highflow_frac"] = float(np.sum(sim_p[high]) / sim_total)

    return result


def nitrogen_flow_partition(
    flow: np.ndarray,
    obs_n: np.ndarray,
    sim_n: np.ndarray,
    threshold_pct: float = 75,
) -> Dict:
    """Split nitrogen into high-flow (particulate/organic) and low-flow (dissolved NO3) periods.

    High-flow nitrogen is dominated by erosion-bound organic N and surface
    runoff NO3, while low-flow nitrogen is dominated by groundwater NO3
    contributions (baseflow).

    Args:
        flow: Flow array for partitioning.
        obs_n: Observed nitrogen array.
        sim_n: Simulated nitrogen array.
        threshold_pct: Percentile threshold separating high-flow from low-flow.

    Returns:
        Dict with highflow_pbias, lowflow_pbias, obs_highflow_frac, sim_highflow_frac.
    """
    threshold = np.percentile(flow, threshold_pct)
    high = flow >= threshold
    low = ~high

    result = {
        "highflow_pbias": np.nan,
        "lowflow_pbias": np.nan,
        "obs_highflow_frac": np.nan,
        "sim_highflow_frac": np.nan,
    }

    obs_high_sum = np.sum(obs_n[high])
    obs_low_sum = np.sum(obs_n[low])
    obs_total = np.sum(obs_n)

    if obs_high_sum > 0:
        result["highflow_pbias"] = float(
            100.0 * (obs_high_sum - np.sum(sim_n[high])) / obs_high_sum
        )
    if obs_low_sum > 0:
        result["lowflow_pbias"] = float(
            100.0 * (obs_low_sum - np.sum(sim_n[low])) / obs_low_sum
        )
    if obs_total > 0:
        result["obs_highflow_frac"] = float(obs_high_sum / obs_total)
    sim_total = np.sum(sim_n)
    if sim_total > 0:
        result["sim_highflow_frac"] = float(np.sum(sim_n[high]) / sim_total)

    return result


def _aggregate_recommendations(
    findings: List[DiagnosticRule],
) -> List[ParameterRecommendation]:
    """Deduplicate and aggregate parameter recommendations from findings.

    Keeps the highest-confidence recommendation for each parameter.
    On conflict (opposite directions, same confidence), first wins.
    """
    param_recs: Dict[str, ParameterRecommendation] = {}
    confidence_order = {"high": 3, "medium": 2, "low": 1}

    for finding in findings:
        for param, direction in zip(finding.parameters, finding.directions):
            existing = param_recs.get(param)
            new_conf = confidence_order.get(finding.confidence, 0)

            if existing is None:
                param_recs[param] = ParameterRecommendation(
                    parameter=param,
                    direction=direction,
                    reason=finding.description,
                    confidence=finding.confidence,
                    category=finding.category,
                )
            else:
                old_conf = confidence_order.get(existing.confidence, 0)
                if existing.direction == direction and new_conf > old_conf:
                    param_recs[param] = ParameterRecommendation(
                        parameter=param,
                        direction=direction,
                        reason=finding.description,
                        confidence=finding.confidence,
                        category=finding.category,
                    )
                elif existing.direction != direction and new_conf > old_conf:
                    param_recs[param] = ParameterRecommendation(
                        parameter=param,
                        direction=direction,
                        reason=finding.description,
                        confidence=finding.confidence,
                        category=finding.category,
                    )

    return sorted(
        param_recs.values(),
        key=lambda r: confidence_order.get(r.confidence, 0),
        reverse=True,
    )


@dataclass
class SedimentDiagnosticReport:
    """Diagnostic report for sediment calibration analysis."""

    overall_metrics: Dict
    rating_curve: Dict = field(default_factory=dict)
    event_partition: Dict = field(default_factory=dict)
    seasonal_bias: Dict = field(default_factory=dict)
    timing: Dict = field(default_factory=dict)
    findings: List[DiagnosticRule] = field(default_factory=list)
    recommendations: List[ParameterRecommendation] = field(default_factory=list)

    def summary_dict(self) -> Dict:
        """Return condensed summary as a dictionary."""
        d = {
            "total_pbias": self.overall_metrics.get("pbias", np.nan),
            "overall_metrics": self.overall_metrics,
            "rating_slope_ratio": self.rating_curve.get("slope_ratio", np.nan),
            "event_sed_ratio": self.event_partition.get("event_ratio", np.nan),
            "nse": self.overall_metrics.get("nse", np.nan),
            "r2": self.overall_metrics.get("r_squared", np.nan),
            "seasonal_bias": self.seasonal_bias,
            "timing": self.timing,
            "n_findings": len(self.findings),
            "finding_names": [f.condition_name for f in self.findings],
            "recommendations": [
                {"parameter": r.parameter, "direction": r.direction, "reason": r.reason}
                for r in self.recommendations
            ],
        }
        # Include all overall_metrics keys at top level
        for key, val in self.overall_metrics.items():
            if key not in d:
                d[key] = val
        return d


@dataclass
class PhosphorusDiagnosticReport:
    """Diagnostic report for phosphorus calibration analysis."""

    overall_metrics: Dict
    flow_partition: Dict = field(default_factory=dict)
    seasonal_bias: Dict = field(default_factory=dict)
    findings: List[DiagnosticRule] = field(default_factory=list)
    recommendations: List[ParameterRecommendation] = field(default_factory=list)

    def summary_dict(self) -> Dict:
        """Return condensed summary as a dictionary."""
        d = {
            "total_pbias": self.overall_metrics.get("pbias", np.nan),
            "overall_metrics": self.overall_metrics,
            "nse": self.overall_metrics.get("nse", np.nan),
            "r2": self.overall_metrics.get("r_squared", np.nan),
            "highflow_pbias": self.flow_partition.get("highflow_pbias", np.nan),
            "lowflow_pbias": self.flow_partition.get("lowflow_pbias", np.nan),
            "seasonal_bias": self.seasonal_bias,
            "n_findings": len(self.findings),
            "finding_names": [f.condition_name for f in self.findings],
            "recommendations": [
                {"parameter": r.parameter, "direction": r.direction, "reason": r.reason}
                for r in self.recommendations
            ],
        }
        for key, val in self.overall_metrics.items():
            if key not in d:
                d[key] = val
        return d


@dataclass
class NitrogenDiagnosticReport:
    """Diagnostic report for nitrogen calibration analysis."""

    overall_metrics: Dict
    flow_partition: Dict = field(default_factory=dict)
    seasonal_bias: Dict = field(default_factory=dict)
    findings: List[DiagnosticRule] = field(default_factory=list)
    recommendations: List[ParameterRecommendation] = field(default_factory=list)

    def summary_dict(self) -> Dict:
        """Return condensed summary as a dictionary."""
        d = {
            "total_pbias": self.overall_metrics.get("pbias", np.nan),
            "overall_metrics": self.overall_metrics,
            "nse": self.overall_metrics.get("nse", np.nan),
            "r2": self.overall_metrics.get("r_squared", np.nan),
            "highflow_pbias": self.flow_partition.get("highflow_pbias", np.nan),
            "lowflow_pbias": self.flow_partition.get("lowflow_pbias", np.nan),
            "seasonal_bias": self.seasonal_bias,
            "n_findings": len(self.findings),
            "finding_names": [f.condition_name for f in self.findings],
            "recommendations": [
                {"parameter": r.parameter, "direction": r.direction, "reason": r.reason}
                for r in self.recommendations
            ],
        }
        for key, val in self.overall_metrics.items():
            if key not in d:
                d[key] = val
        return d


def diagnose_sediment(
    obs_sed: np.ndarray,
    sim_sed: np.ndarray,
    obs_flow: np.ndarray = None,
    sim_flow: np.ndarray = None,
    dates: np.ndarray = None,
    thresholds: Dict = None,
) -> SedimentDiagnosticReport:
    """Run sediment diagnostic analysis.

    Computes overall metrics (NSE, KGE, PBIAS, R2, RMSE, RSR), then
    optionally performs rating curve, event partition, and timing analyses
    if flow data is provided. Seasonal analysis is performed if dates are
    provided. Evaluates sediment-specific diagnostic rules.

    Args:
        obs_sed: Observed sediment values.
        sim_sed: Simulated sediment values.
        obs_flow: Observed flow values (optional, enables rating/event/timing).
        sim_flow: Simulated flow values (optional).
        dates: Date array (optional, for seasonal analysis).
        thresholds: Optional override for DIAGNOSTIC_THRESHOLDS.

    Returns:
        SedimentDiagnosticReport with analysis results and recommendations.
    """
    obs = np.asarray(obs_sed, dtype=np.float64)
    sim = np.asarray(sim_sed, dtype=np.float64)

    # Remove NaN pairs
    mask = ~(np.isnan(obs) | np.isnan(sim))
    if obs_flow is not None:
        flow_obs = np.asarray(obs_flow, dtype=np.float64)
        flow_sim = np.asarray(sim_flow, dtype=np.float64) if sim_flow is not None else flow_obs
        mask &= ~(np.isnan(flow_obs) | np.isnan(flow_sim))
    else:
        flow_obs = flow_sim = None

    obs_clean = obs[mask]
    sim_clean = sim[mask]
    dates_clean = np.asarray(dates)[mask] if dates is not None else None
    if flow_obs is not None:
        flow_obs_clean = flow_obs[mask]
        flow_sim_clean = flow_sim[mask]
    else:
        flow_obs_clean = flow_sim_clean = None

    thresh = {**DIAGNOSTIC_THRESHOLDS, **(thresholds or {})}

    # 1. Overall metrics
    overall = evaluate_model(obs_clean, sim_clean)

    # 2. Rating curve analysis
    rating = {}
    if flow_obs_clean is not None:
        rating = sediment_rating_curve_analysis(
            flow_obs_clean, obs_clean, flow_sim_clean, sim_clean
        )

    # 3. Event partition
    event = {}
    if flow_obs_clean is not None:
        event = sediment_event_partition(flow_obs_clean, obs_clean, sim_clean)

    # 4. Timing analysis
    timing = {}
    if flow_obs_clean is not None:
        timing = sediment_timing_analysis(
            flow_obs_clean, obs_clean, flow_sim_clean, sim_clean
        )

    # 5. Seasonal bias
    seasonal = {}
    if dates_clean is not None:
        seasonal = _seasonal_pbias(dates_clean, obs_clean, sim_clean)

    # 6. Evaluate diagnostic rules
    findings = []
    total_pbias = overall.get("pbias", np.nan)

    # Overall sediment bias
    if not np.isnan(total_pbias):
        if total_pbias < thresh["volume_over"]:
            findings.append(_RULES_BY_NAME["sediment_overestimation"])
        elif total_pbias > thresh["volume_under"]:
            findings.append(_RULES_BY_NAME["sediment_underestimation"])

    # Rating curve
    slope_ratio = rating.get("slope_ratio", np.nan)
    if not np.isnan(slope_ratio):
        if slope_ratio > thresh["rating_slope_high"]:
            findings.append(_RULES_BY_NAME["sed_rating_too_steep"])
        elif slope_ratio < thresh["rating_slope_low"]:
            findings.append(_RULES_BY_NAME["sed_rating_too_flat"])

    # Event partition
    event_ratio = event.get("event_ratio", np.nan)
    if not np.isnan(event_ratio):
        if event_ratio > thresh["event_sed_ratio_high"]:
            findings.append(_RULES_BY_NAME["sed_event_too_high"])
        elif event_ratio < thresh["event_sed_ratio_low"]:
            findings.append(_RULES_BY_NAME["sed_event_too_low"])

    # Seasonal
    s_thresh = thresh["seasonal_threshold"]
    mam_bias = seasonal.get("MAM", 0)
    if mam_bias < -s_thresh:
        findings.append(_RULES_BY_NAME["sed_spring_over"])
    elif mam_bias > s_thresh:
        findings.append(_RULES_BY_NAME["sed_spring_under"])

    # Timing
    lag_diff = timing.get("lag_diff", np.nan)
    if not np.isnan(lag_diff):
        if lag_diff > thresh["sed_timing_threshold"]:
            findings.append(_RULES_BY_NAME["sed_timing_late"])
        elif lag_diff < -thresh["sed_timing_threshold"]:
            findings.append(_RULES_BY_NAME["sed_timing_early"])

    # 7. Aggregate recommendations
    recommendations = _aggregate_recommendations(findings)

    return SedimentDiagnosticReport(
        overall_metrics=overall,
        rating_curve=rating,
        event_partition=event,
        seasonal_bias=seasonal,
        timing=timing,
        findings=findings,
        recommendations=recommendations,
    )


def diagnose_phosphorus(
    obs_p: np.ndarray,
    sim_p: np.ndarray,
    obs_flow: np.ndarray = None,
    sim_flow: np.ndarray = None,
    dates: np.ndarray = None,
    thresholds: Dict = None,
) -> PhosphorusDiagnosticReport:
    """Run phosphorus diagnostic analysis.

    Computes overall metrics, then optionally performs flow-based partitioning
    (high-flow particulate vs low-flow dissolved P) and seasonal analysis.

    Args:
        obs_p: Observed phosphorus values.
        sim_p: Simulated phosphorus values.
        obs_flow: Observed flow values (optional, enables flow partition).
        sim_flow: Simulated flow values (optional).
        dates: Date array (optional, for seasonal analysis).
        thresholds: Optional override for DIAGNOSTIC_THRESHOLDS.

    Returns:
        PhosphorusDiagnosticReport with analysis results and recommendations.
    """
    obs = np.asarray(obs_p, dtype=np.float64)
    sim = np.asarray(sim_p, dtype=np.float64)

    mask = ~(np.isnan(obs) | np.isnan(sim))
    if obs_flow is not None:
        flow_obs = np.asarray(obs_flow, dtype=np.float64)
        mask &= ~np.isnan(flow_obs)
    else:
        flow_obs = None

    obs_clean = obs[mask]
    sim_clean = sim[mask]
    dates_clean = np.asarray(dates)[mask] if dates is not None else None
    flow_clean = flow_obs[mask] if flow_obs is not None else None

    thresh = {**DIAGNOSTIC_THRESHOLDS, **(thresholds or {})}

    # 1. Overall metrics
    overall = evaluate_model(obs_clean, sim_clean)

    # 2. Flow partition
    flow_part = {}
    if flow_clean is not None:
        flow_part = phosphorus_flow_partition(flow_clean, obs_clean, sim_clean)

    # 3. Seasonal bias
    seasonal = {}
    if dates_clean is not None:
        seasonal = _seasonal_pbias(dates_clean, obs_clean, sim_clean)

    # 4. Evaluate diagnostic rules
    findings = []

    # Flow-partitioned bias
    hf_bias = flow_part.get("highflow_pbias", np.nan)
    lf_bias = flow_part.get("lowflow_pbias", np.nan)
    p_hf_thresh = thresh["p_highflow_bias_threshold"]
    p_lf_thresh = thresh["p_lowflow_bias_threshold"]

    if not np.isnan(hf_bias):
        if hf_bias < -p_hf_thresh:
            findings.append(_RULES_BY_NAME["p_highflow_over"])
        elif hf_bias > p_hf_thresh:
            findings.append(_RULES_BY_NAME["p_highflow_under"])

    if not np.isnan(lf_bias):
        if lf_bias < -p_lf_thresh:
            findings.append(_RULES_BY_NAME["p_lowflow_over"])
        elif lf_bias > p_lf_thresh:
            findings.append(_RULES_BY_NAME["p_lowflow_under"])

    # Seasonal
    s_thresh = thresh["seasonal_threshold"]
    mam_bias = seasonal.get("MAM", 0)
    jja_bias = seasonal.get("JJA", 0)

    if mam_bias < -s_thresh:
        findings.append(_RULES_BY_NAME["p_spring_over"])
    if jja_bias > s_thresh:
        findings.append(_RULES_BY_NAME["p_summer_under"])

    # 5. Aggregate recommendations
    recommendations = _aggregate_recommendations(findings)

    return PhosphorusDiagnosticReport(
        overall_metrics=overall,
        flow_partition=flow_part,
        seasonal_bias=seasonal,
        findings=findings,
        recommendations=recommendations,
    )


def diagnose_nitrogen(
    obs_n: np.ndarray,
    sim_n: np.ndarray,
    obs_flow: np.ndarray = None,
    sim_flow: np.ndarray = None,
    dates: np.ndarray = None,
    thresholds: Dict = None,
) -> NitrogenDiagnosticReport:
    """Run nitrogen diagnostic analysis.

    Computes overall metrics (NSE, KGE, PBIAS, R2, RMSE, RSR), then
    optionally performs flow-based partitioning (high-flow particulate/organic N
    vs low-flow dissolved NO3) and seasonal analysis. Evaluates nitrogen-specific
    diagnostic rules and produces parameter recommendations.

    Args:
        obs_n: Observed nitrogen values.
        sim_n: Simulated nitrogen values.
        obs_flow: Observed flow values (optional, enables flow partition).
        sim_flow: Simulated flow values (optional, unused but accepted for
            API consistency with diagnose_sediment/diagnose_phosphorus).
        dates: Date array (optional, for seasonal analysis).
        thresholds: Optional override for DIAGNOSTIC_THRESHOLDS.

    Returns:
        NitrogenDiagnosticReport with analysis results and recommendations.
    """
    obs = np.asarray(obs_n, dtype=np.float64)
    sim = np.asarray(sim_n, dtype=np.float64)

    mask = ~(np.isnan(obs) | np.isnan(sim))
    if obs_flow is not None:
        flow_obs = np.asarray(obs_flow, dtype=np.float64)
        mask &= ~np.isnan(flow_obs)
    else:
        flow_obs = None

    obs_clean = obs[mask]
    sim_clean = sim[mask]
    dates_clean = np.asarray(dates)[mask] if dates is not None else None
    flow_clean = flow_obs[mask] if flow_obs is not None else None

    thresh = {**DIAGNOSTIC_THRESHOLDS, **(thresholds or {})}

    # 1. Overall metrics
    overall = evaluate_model(obs_clean, sim_clean)

    # 2. Flow partition
    flow_part = {}
    if flow_clean is not None:
        flow_part = nitrogen_flow_partition(flow_clean, obs_clean, sim_clean)

    # 3. Seasonal bias
    seasonal = {}
    if dates_clean is not None:
        seasonal = _seasonal_pbias(dates_clean, obs_clean, sim_clean)

    # 4. Evaluate diagnostic rules
    findings = []
    total_pbias = overall.get("pbias", np.nan)

    # Overall nitrogen bias
    if not np.isnan(total_pbias):
        if total_pbias < thresh["volume_over"]:
            findings.append(_RULES_BY_NAME["n_overestimation"])
        elif total_pbias > thresh["volume_under"]:
            findings.append(_RULES_BY_NAME["n_underestimation"])

    # Flow-partitioned bias
    hf_bias = flow_part.get("highflow_pbias", np.nan)
    lf_bias = flow_part.get("lowflow_pbias", np.nan)
    n_hf_thresh = thresh["n_highflow_bias_threshold"]
    n_lf_thresh = thresh["n_lowflow_bias_threshold"]

    if not np.isnan(hf_bias):
        if hf_bias < -n_hf_thresh:
            findings.append(_RULES_BY_NAME["n_highflow_over"])
        elif hf_bias > n_hf_thresh:
            findings.append(_RULES_BY_NAME["n_highflow_under"])

    if not np.isnan(lf_bias):
        if lf_bias < -n_lf_thresh:
            findings.append(_RULES_BY_NAME["n_lowflow_over"])
        elif lf_bias > n_lf_thresh:
            findings.append(_RULES_BY_NAME["n_lowflow_under"])

    # Seasonal
    s_thresh = thresh["seasonal_threshold"]
    mam_bias = seasonal.get("MAM", 0)
    jja_bias = seasonal.get("JJA", 0)

    if mam_bias < -s_thresh:
        findings.append(_RULES_BY_NAME["n_spring_over"])
    if jja_bias > s_thresh:
        findings.append(_RULES_BY_NAME["n_summer_under"])

    # 5. Aggregate recommendations
    recommendations = _aggregate_recommendations(findings)

    return NitrogenDiagnosticReport(
        overall_metrics=overall,
        flow_partition=flow_part,
        seasonal_bias=seasonal,
        findings=findings,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# E. DiagnosticReport and diagnose() orchestrator
# ---------------------------------------------------------------------------

@dataclass
class DiagnosticReport:
    """Complete diagnostic report from hydrograph analysis."""

    # Baseflow separation
    obs_baseflow: np.ndarray
    sim_baseflow: np.ndarray
    bfi_observed: float
    bfi_simulated: float
    bfi_ratio: float

    # Peak analysis
    peak_comparison: Dict

    # Volume balance
    volume_metrics: Dict

    # Overall metrics
    overall_metrics: Dict

    # Recession
    obs_recession_rate: float
    sim_recession_rate: float

    # FDC metrics (Yilmaz 2008)
    fdc_metrics: Dict = field(default_factory=dict)

    # KGE components (Gupta 2009)
    kge_comp: Dict = field(default_factory=dict)

    # Diagnostic findings and recommendations
    findings: List[DiagnosticRule] = field(default_factory=list)
    recommendations: List[ParameterRecommendation] = field(default_factory=list)

    def summary(self) -> str:
        """Generate human-readable diagnostic summary."""
        lines = []
        lines.append("=" * 60)
        lines.append("HYDROGRAPH DIAGNOSTIC REPORT")
        lines.append("=" * 60)

        # Overall metrics
        lines.append("\n--- Overall Performance ---")
        for metric, value in self.overall_metrics.items():
            if isinstance(value, float):
                lines.append(f"  {metric:>10s}: {value:>10.3f}")

        # Baseflow
        lines.append("\n--- Baseflow Analysis ---")
        lines.append(f"  BFI (observed):  {self.bfi_observed:.3f}")
        lines.append(f"  BFI (simulated): {self.bfi_simulated:.3f}")
        lines.append(f"  BFI ratio:       {self.bfi_ratio:.3f}")

        # Peaks
        lines.append("\n--- Peak Flow Analysis ---")
        pc = self.peak_comparison
        lines.append(f"  Matched peaks:       {pc.get('n_matched', 0)}")
        lines.append(f"  Missed peaks:        {pc.get('n_missed', 0)}")
        lines.append(f"  False peaks:         {pc.get('n_false', 0)}")
        mag = pc.get("peak_magnitude_ratio", np.nan)
        timing = pc.get("peak_timing_error_days", np.nan)
        if not np.isnan(mag):
            lines.append(f"  Magnitude ratio:     {mag:.2f} (1.0 = perfect)")
        if not np.isnan(timing):
            lines.append(f"  Timing error:        {timing:+.1f} days (+ve = sim lags obs)")

        # Volume
        lines.append("\n--- Volume Balance ---")
        vm = self.volume_metrics
        lines.append(f"  Total volume ratio:  {vm.get('total_volume_ratio', np.nan):.3f}")
        lines.append(f"  Total PBIAS:         {vm.get('total_pbias', np.nan):.1f}%")
        lines.append(f"  High-flow bias:      {vm.get('high_flow_bias', np.nan):.1f}%")
        lines.append(f"  Low-flow bias:       {vm.get('low_flow_bias', np.nan):.1f}%")
        if vm.get("seasonal_bias"):
            lines.append("  Seasonal PBIAS:")
            for season, bias in vm["seasonal_bias"].items():
                lines.append(f"    {season}: {bias:+.1f}%")

        # FDC metrics
        if self.fdc_metrics:
            lines.append("\n--- Flow Duration Curve ---")
            lines.append(f"  FHV (high-flow bias):  {self.fdc_metrics.get('FHV', np.nan):+.1f}%")
            lines.append(f"  FMS (mid-slope bias):  {self.fdc_metrics.get('FMS', np.nan):+.1f}%")
            lines.append(f"  FLV (low-flow bias):   {self.fdc_metrics.get('FLV', np.nan):+.1f}%")

        # KGE components
        if self.kge_comp:
            lines.append("\n--- KGE Decomposition ---")
            lines.append(f"  KGE:       {self.kge_comp.get('kge', np.nan):.3f}")
            lines.append(f"  r (corr):  {self.kge_comp.get('r', np.nan):.3f}")
            lines.append(f"  alpha:     {self.kge_comp.get('alpha', np.nan):.3f}")
            lines.append(f"  beta:      {self.kge_comp.get('beta', np.nan):.3f}")

        # Findings
        if self.findings:
            lines.append("\n--- Diagnostic Findings ---")
            for f in self.findings:
                lines.append(f"  [{f.confidence.upper()}] {f.description}")
        else:
            lines.append("\n--- No significant diagnostic issues found ---")

        # Recommendations
        if self.recommendations:
            lines.append("\n--- Parameter Recommendations ---")
            for r in self.recommendations:
                lines.append(f"  {r.parameter:>12s}: {r.direction:<10s} ({r.reason}) [{r.confidence}]")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def summary_dict(self) -> Dict:
        """Return a condensed summary as a dictionary (for storage in CalibrationStep)."""
        return {
            "bfi_observed": self.bfi_observed,
            "bfi_simulated": self.bfi_simulated,
            "bfi_ratio": self.bfi_ratio,
            "peak_magnitude_ratio": self.peak_comparison.get("peak_magnitude_ratio", np.nan),
            "peak_timing_error": self.peak_comparison.get("peak_timing_error_days", np.nan),
            "n_matched_peaks": self.peak_comparison.get("n_matched", 0),
            "total_pbias": self.volume_metrics.get("total_pbias", np.nan),
            "high_flow_bias": self.volume_metrics.get("high_flow_bias", np.nan),
            "low_flow_bias": self.volume_metrics.get("low_flow_bias", np.nan),
            "seasonal_bias": self.volume_metrics.get("seasonal_bias", {}),
            "overall_metrics": self.overall_metrics,
            "fdc_metrics": self.fdc_metrics,
            "kge_components": self.kge_comp,
            "n_findings": len(self.findings),
            "finding_names": [f.condition_name for f in self.findings],
            "recommendations": [
                {"parameter": r.parameter, "direction": r.direction, "reason": r.reason}
                for r in self.recommendations
            ],
        }


def diagnose(
    observed: np.ndarray,
    simulated: np.ndarray,
    dates: np.ndarray = None,
    alpha: float = 0.98,
    bfi_max: float = 0.80,
    thresholds: Dict = None,
) -> DiagnosticReport:
    """
    Run complete hydrograph diagnostic analysis.

    This is the main entry point. It:
    1. Separates baseflow (Eckhardt filter) for both obs and sim
    2. Detects and compares peaks
    3. Calculates volume balance (total, seasonal, flow-regime)
    4. Estimates recession characteristics
    5. Evaluates all diagnostic rules against thresholds
    6. Aggregates parameter recommendations

    Works both pre-calibration (baseline diagnosis) and post-calibration.

    Args:
        observed: Observed flow values.
        simulated: Simulated flow values.
        dates: Date array (optional, for seasonal/annual analysis).
        alpha: Eckhardt filter recession constant.
        bfi_max: Eckhardt filter maximum BFI.
        thresholds: Optional override for DIAGNOSTIC_THRESHOLDS.

    Returns:
        DiagnosticReport with all analysis results and recommendations.
    """
    obs = np.asarray(observed, dtype=np.float64)
    sim = np.asarray(simulated, dtype=np.float64)

    # Remove NaN pairs
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs_clean = obs[mask]
    sim_clean = sim[mask]
    dates_clean = np.asarray(dates)[mask] if dates is not None else None

    thresh = {**DIAGNOSTIC_THRESHOLDS, **(thresholds or {})}

    # 1. Baseflow separation
    obs_bf = eckhardt_baseflow_filter(obs_clean, alpha, bfi_max)
    sim_bf = eckhardt_baseflow_filter(sim_clean, alpha, bfi_max)
    bfi_obs = calculate_bfi(obs_clean, obs_bf)
    bfi_sim = calculate_bfi(sim_clean, sim_bf)
    bfi_ratio = bfi_sim / bfi_obs if bfi_obs > 0 else np.nan

    # 2. Peak analysis
    peak_comp = compare_peaks(obs_clean, sim_clean, dates_clean)

    # 3. Volume balance
    vol_metrics = volume_balance(obs_clean, sim_clean, dates_clean)

    # 4. Overall metrics
    overall = evaluate_model(obs_clean, sim_clean)

    # 5. Recession analysis
    obs_recession = _estimate_recession_rate(obs_clean, obs_bf)
    sim_recession = _estimate_recession_rate(sim_clean, sim_bf)

    # 5b. FDC metrics
    fdc = flow_duration_curve_metrics(obs_clean, sim_clean)

    # 5c. KGE decomposition
    kge_comp_dict = kge_components(obs_clean, sim_clean)

    # 6. Evaluate diagnostic rules
    findings = []
    mag_ratio = peak_comp.get("peak_magnitude_ratio", np.nan)
    timing_err = peak_comp.get("peak_timing_error_days", np.nan)
    total_pbias = vol_metrics.get("total_pbias", np.nan)
    seasonal = vol_metrics.get("seasonal_bias", {})

    # Peak magnitude
    if not np.isnan(mag_ratio):
        if mag_ratio > thresh["peak_magnitude_high"]:
            findings.append(_RULES_BY_NAME["peak_overestimation"])
        elif mag_ratio < thresh["peak_magnitude_low"]:
            findings.append(_RULES_BY_NAME["peak_underestimation"])

    # Peak timing
    if not np.isnan(timing_err):
        if timing_err > thresh["peak_timing_late"]:
            findings.append(_RULES_BY_NAME["peak_timing_late"])
        elif timing_err < thresh["peak_timing_early"]:
            findings.append(_RULES_BY_NAME["peak_timing_early"])

    # Baseflow
    if not np.isnan(bfi_ratio):
        if bfi_ratio < thresh["bfi_ratio_low"]:
            findings.append(_RULES_BY_NAME["baseflow_too_low"])
        elif bfi_ratio > thresh["bfi_ratio_high"]:
            findings.append(_RULES_BY_NAME["baseflow_too_high"])

    # Recession
    if not np.isnan(obs_recession) and not np.isnan(sim_recession) and obs_recession > 0:
        recession_ratio = sim_recession / obs_recession
        if recession_ratio < thresh["recession_fast_ratio"]:
            findings.append(_RULES_BY_NAME["recession_too_fast"])
        elif recession_ratio > thresh["recession_slow_ratio"]:
            findings.append(_RULES_BY_NAME["recession_too_slow"])

    # Volume balance
    if not np.isnan(total_pbias):
        if total_pbias < thresh["volume_over"]:  # negative PBIAS = overestimation
            findings.append(_RULES_BY_NAME["volume_overestimation"])
        elif total_pbias > thresh["volume_under"]:
            findings.append(_RULES_BY_NAME["volume_underestimation"])

    # Seasonal bias
    s_thresh = thresh["seasonal_threshold"]
    jja_bias = seasonal.get("JJA", 0)
    djf_bias = seasonal.get("DJF", 0)

    if jja_bias < -s_thresh:
        findings.append(_RULES_BY_NAME["summer_overestimation"])
    elif jja_bias > s_thresh:
        findings.append(_RULES_BY_NAME["summer_underestimation"])

    if djf_bias > s_thresh:
        findings.append(_RULES_BY_NAME["winter_underestimation"])
    elif djf_bias < -s_thresh:
        findings.append(_RULES_BY_NAME["winter_overestimation"])

    # 7. Aggregate recommendations (deduplicate, keep highest confidence)
    param_recs: Dict[str, ParameterRecommendation] = {}
    confidence_order = {"high": 3, "medium": 2, "low": 1}

    for finding in findings:
        for param, direction in zip(finding.parameters, finding.directions):
            existing = param_recs.get(param)
            new_conf = confidence_order.get(finding.confidence, 0)

            if existing is None:
                param_recs[param] = ParameterRecommendation(
                    parameter=param,
                    direction=direction,
                    reason=finding.description,
                    confidence=finding.confidence,
                    category=finding.category,
                )
            else:
                # If same direction, keep higher confidence
                old_conf = confidence_order.get(existing.confidence, 0)
                if existing.direction == direction and new_conf > old_conf:
                    param_recs[param] = ParameterRecommendation(
                        parameter=param,
                        direction=direction,
                        reason=finding.description,
                        confidence=finding.confidence,
                        category=finding.category,
                    )
                elif existing.direction != direction:
                    # Conflict: different rules suggest opposite directions.
                    # Keep the higher-confidence one; if equal, mark as "conflicted"
                    if new_conf > old_conf:
                        param_recs[param] = ParameterRecommendation(
                            parameter=param,
                            direction=direction,
                            reason=finding.description,
                            confidence=finding.confidence,
                            category=finding.category,
                        )
                    # If same confidence and conflicting, leave existing (first wins)

    recommendations = sorted(
        param_recs.values(),
        key=lambda r: confidence_order.get(r.confidence, 0),
        reverse=True,
    )

    return DiagnosticReport(
        obs_baseflow=obs_bf,
        sim_baseflow=sim_bf,
        bfi_observed=bfi_obs,
        bfi_simulated=bfi_sim,
        bfi_ratio=bfi_ratio,
        peak_comparison=peak_comp,
        volume_metrics=vol_metrics,
        overall_metrics=overall,
        obs_recession_rate=obs_recession,
        sim_recession_rate=sim_recession,
        fdc_metrics=fdc,
        kge_comp=kge_comp_dict,
        findings=findings,
        recommendations=recommendations,
    )
