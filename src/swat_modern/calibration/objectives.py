"""
Objective functions for SWAT model calibration.

This module provides standard hydrological model evaluation metrics:
- NSE (Nash-Sutcliffe Efficiency)
- KGE (Kling-Gupta Efficiency)
- PBIAS (Percent Bias)
- RMSE (Root Mean Square Error)
- R-squared (Coefficient of Determination)
- Log-NSE (NSE of log-transformed values)
- RSR (RMSE-observations Standard deviation Ratio)

All functions follow the convention:
    func(observed, simulated) -> float

Higher values are better for NSE, KGE, R-squared.
Lower values are better for PBIAS (absolute), RMSE.

Example:
    >>> import numpy as np
    >>> obs = np.array([10, 20, 30, 40, 50])
    >>> sim = np.array([12, 18, 32, 38, 52])
    >>> print(f"NSE = {nse(obs, sim):.3f}")
    NSE = 0.960
"""

from typing import Union, Callable
import numpy as np

# Type alias for array-like inputs
ArrayLike = Union[np.ndarray, list]


def _to_array(data: ArrayLike) -> np.ndarray:
    """Convert input to numpy array and validate."""
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError("Input must be 1-dimensional")
    return arr


def _validate_inputs(observed: ArrayLike, simulated: ArrayLike) -> tuple:
    """Validate and prepare inputs."""
    obs = _to_array(observed)
    sim = _to_array(simulated)

    if len(obs) != len(sim):
        raise ValueError(
            f"Arrays must have same length: observed={len(obs)}, simulated={len(sim)}"
        )

    if len(obs) == 0:
        raise ValueError("Arrays cannot be empty")

    # Remove NaN values (pairwise)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs = obs[mask]
    sim = sim[mask]

    if len(obs) < 2:
        raise ValueError("Need at least 2 valid data points after removing NaN")

    return obs, sim


def nse(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate Nash-Sutcliffe Efficiency (NSE).

    NSE = 1 - sum((obs - sim)^2) / sum((obs - mean(obs))^2)

    Range: -inf to 1 (1 = perfect fit, 0 = mean prediction, <0 = worse than mean)

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        NSE value (float)

    References:
        Nash, J.E. and Sutcliffe, J.V. (1970). River flow forecasting through
        conceptual models part I. Journal of Hydrology, 10(3), 282-290.
    """
    obs, sim = _validate_inputs(observed, simulated)

    numerator = np.sum((obs - sim) ** 2)
    denominator = np.sum((obs - np.mean(obs)) ** 2)

    if denominator == 0:
        # If observed values are constant
        if numerator == 0:
            return 1.0  # Perfect match
        return -np.inf

    return 1 - (numerator / denominator)


def log_nse(observed: ArrayLike, simulated: ArrayLike, epsilon: float = 0.01) -> float:
    """
    Calculate NSE of log-transformed values.

    Emphasizes low-flow periods, reducing influence of peak flows.

    Args:
        observed: Observed values
        simulated: Simulated values
        epsilon: Small value added to avoid log(0)

    Returns:
        Log-NSE value (float)
    """
    obs, sim = _validate_inputs(observed, simulated)

    # Add epsilon to avoid log(0) for zero or negative values
    obs_log = np.log(np.maximum(obs, epsilon))
    sim_log = np.log(np.maximum(sim, epsilon))

    return nse(obs_log, sim_log)


def kge(
    observed: ArrayLike,
    simulated: ArrayLike,
    return_components: bool = False
) -> Union[float, tuple]:
    """
    Calculate Kling-Gupta Efficiency (KGE).

    KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)

    where:
        r = Pearson correlation coefficient
        alpha = std(sim) / std(obs)  (variability ratio)
        beta = mean(sim) / mean(obs) (bias ratio)

    Range: -inf to 1 (1 = perfect fit)

    Args:
        observed: Observed values
        simulated: Simulated values
        return_components: If True, return (KGE, r, alpha, beta)

    Returns:
        KGE value, or tuple of (KGE, r, alpha, beta) if return_components=True

    References:
        Gupta, H.V., Kling, H., Yilmaz, K.K., Martinez, G.F. (2009).
        Decomposition of the mean squared error and NSE performance criteria.
        Journal of Hydrology, 377(1-2), 80-91.
    """
    obs, sim = _validate_inputs(observed, simulated)

    # Correlation coefficient
    r = np.corrcoef(obs, sim)[0, 1]

    # Variability ratio
    std_obs = np.std(obs, ddof=1)
    std_sim = np.std(sim, ddof=1)

    if std_obs == 0:
        alpha = np.inf if std_sim > 0 else 1.0
    else:
        alpha = std_sim / std_obs

    # Bias ratio
    mean_obs = np.mean(obs)
    mean_sim = np.mean(sim)

    if mean_obs == 0:
        beta = np.inf if mean_sim > 0 else 1.0
    else:
        beta = mean_sim / mean_obs

    # KGE
    kge_value = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

    if return_components:
        return kge_value, r, alpha, beta
    return kge_value


def pbias(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate Percent Bias (PBIAS).

    PBIAS = 100 * sum(obs - sim) / sum(obs)

    Positive PBIAS = model underestimates
    Negative PBIAS = model overestimates

    Target: 0% (optimal), <10% excellent, <15% good, <25% satisfactory

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        PBIAS value in percent (float)

    References:
        Moriasi, D.N., et al. (2007). Model evaluation guidelines for systematic
        quantification of accuracy in watershed simulations. ASABE, 50(3), 885-900.
    """
    obs, sim = _validate_inputs(observed, simulated)

    sum_obs = np.sum(obs)

    if sum_obs == 0:
        return np.inf if np.sum(sim) != 0 else 0.0

    return 100 * np.sum(obs - sim) / sum_obs


def rmse(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate Root Mean Square Error (RMSE).

    RMSE = sqrt(mean((obs - sim)^2))

    Lower is better. Units are same as input data.

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        RMSE value (float)
    """
    obs, sim = _validate_inputs(observed, simulated)

    return np.sqrt(np.mean((obs - sim) ** 2))


def r_squared(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate coefficient of determination (R-squared).

    R² = (correlation coefficient)^2

    Range: 0 to 1 (1 = perfect correlation)
    Note: R² can indicate good correlation even with systematic bias.

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        R-squared value (float)
    """
    obs, sim = _validate_inputs(observed, simulated)

    r = np.corrcoef(obs, sim)[0, 1]

    return r ** 2


def mse(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate Mean Square Error (MSE).

    MSE = mean((obs - sim)^2)

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        MSE value (float)
    """
    obs, sim = _validate_inputs(observed, simulated)

    return np.mean((obs - sim) ** 2)


def mae(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate Mean Absolute Error (MAE).

    MAE = mean(|obs - sim|)

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        MAE value (float)
    """
    obs, sim = _validate_inputs(observed, simulated)

    return np.mean(np.abs(obs - sim))


def rsr(observed: ArrayLike, simulated: ArrayLike) -> float:
    """
    Calculate RMSE-observations Standard deviation Ratio (RSR).

    RSR = RMSE / STDEVobs = sqrt(sum((obs - sim)^2)) / sqrt(sum((obs - mean(obs))^2))

    Range: 0 to +inf (0 = perfect fit, lower is better)

    Performance ratings (Moriasi et al., 2007):
    - RSR <= 0.50: Very good
    - 0.50 < RSR <= 0.60: Good
    - 0.60 < RSR <= 0.70: Satisfactory
    - RSR > 0.70: Unsatisfactory

    Note: RSR = sqrt(1 - NSE) when NSE >= 0

    Args:
        observed: Observed values
        simulated: Simulated values

    Returns:
        RSR value (float)

    References:
        Moriasi, D.N., et al. (2007). Model evaluation guidelines for systematic
        quantification of accuracy in watershed simulations. ASABE, 50(3), 885-900.
    """
    obs, sim = _validate_inputs(observed, simulated)

    rmse_value = np.sqrt(np.sum((obs - sim) ** 2))
    stdev_obs = np.sqrt(np.sum((obs - np.mean(obs)) ** 2))

    if stdev_obs == 0:
        return np.inf if rmse_value > 0 else 0.0

    return rmse_value / stdev_obs


class ObjectiveFunction:
    """
    Wrapper class for objective functions with configuration.

    Supports maximization/minimization direction and weight for multi-objective.

    Example:
        >>> obj = ObjectiveFunction("nse", maximize=True, weight=1.0)
        >>> score = obj.evaluate(observed, simulated)
        >>> print(f"{obj.name}: {score:.3f}")
    """

    # Available functions
    FUNCTIONS = {
        "nse": (nse, True),        # (function, is_maximize)
        "log_nse": (log_nse, True),
        "kge": (kge, True),
        "pbias": (pbias, True),    # already converted to maximization in score()
        "rmse": (rmse, False),
        "r_squared": (r_squared, True),
        "mse": (mse, False),
        "mae": (mae, False),
        "rsr": (rsr, False),       # minimize (lower is better)
    }

    def __init__(
        self,
        name: str,
        maximize: bool = None,
        weight: float = 1.0,
        target: float = None,
    ):
        """
        Initialize objective function.

        Args:
            name: Function name (nse, kge, pbias, etc.)
            maximize: Whether higher is better (auto-detected if None)
            weight: Weight for multi-objective optimization
            target: Target value (optional, for constraint-based optimization)
        """
        name = name.lower()

        if name not in self.FUNCTIONS:
            available = ", ".join(self.FUNCTIONS.keys())
            raise ValueError(f"Unknown function '{name}'. Available: {available}")

        self.name = name
        self._func, default_maximize = self.FUNCTIONS[name]
        self.maximize = maximize if maximize is not None else default_maximize
        self.weight = weight
        self.target = target

    def evaluate(self, observed: ArrayLike, simulated: ArrayLike) -> float:
        """
        Evaluate objective function.

        Args:
            observed: Observed values
            simulated: Simulated values

        Returns:
            Objective function value
        """
        return self._func(observed, simulated)

    def score(self, observed: ArrayLike, simulated: ArrayLike) -> float:
        """
        Calculate weighted score for optimization.

        Returns value suitable for SPOTPY optimization:
        - Positive values for maximization targets
        - Handles sign conversion for minimize functions

        Args:
            observed: Observed values
            simulated: Simulated values

        Returns:
            Weighted score (higher is better for optimizer)
        """
        value = self.evaluate(observed, simulated)

        # For PBIAS, we want absolute value close to zero
        if self.name == "pbias":
            # Convert PBIAS to a maximization metric
            # Perfect = 0% -> score = 100
            # 10% bias -> score = 90
            value = 100 - abs(value)

        # For minimization functions (RMSE, MSE, MAE), negate
        if not self.maximize:
            value = -value

        return self.weight * value

    def __repr__(self) -> str:
        direction = "maximize" if self.maximize else "minimize"
        return f"ObjectiveFunction('{self.name}', {direction}, weight={self.weight})"


def evaluate_model(
    observed: ArrayLike,
    simulated: ArrayLike,
    metrics: list = None,
) -> dict:
    """
    Evaluate model with multiple metrics.

    Args:
        observed: Observed values
        simulated: Simulated values
        metrics: List of metric names (default: all)

    Returns:
        Dictionary of {metric_name: value}

    Example:
        >>> results = evaluate_model(obs, sim, metrics=["nse", "kge", "pbias"])
        >>> print(results)
        {'nse': 0.85, 'kge': 0.78, 'pbias': 5.2}
    """
    if metrics is None:
        metrics = ["nse", "kge", "pbias", "rmse", "r_squared", "rsr"]

    results = {}
    for metric in metrics:
        obj = ObjectiveFunction(metric)
        try:
            results[metric] = obj.evaluate(observed, simulated)
        except Exception as e:
            results[metric] = np.nan

    return results


def model_performance_rating(nse_value: float) -> str:
    """
    Rate model performance based on NSE value.

    Based on Moriasi et al. (2007) guidelines:
    - NSE > 0.75: Very good
    - 0.65 < NSE <= 0.75: Good
    - 0.50 < NSE <= 0.65: Satisfactory
    - NSE <= 0.50: Unsatisfactory

    Args:
        nse_value: Nash-Sutcliffe Efficiency value

    Returns:
        Performance rating string
    """
    if nse_value > 0.75:
        return "Very Good"
    elif nse_value > 0.65:
        return "Good"
    elif nse_value > 0.50:
        return "Satisfactory"
    else:
        return "Unsatisfactory"
