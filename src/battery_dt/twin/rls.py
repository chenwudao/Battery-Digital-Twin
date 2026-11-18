"""Scalar recursive least-squares tracker for pack resistance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class R0Tracker:
    r0_ohm: float
    covariance: float = 0.05
    forgetting_factor: float = 0.9995
    min_abs_current_A: float = 2.0
    max_innovation_V: float = 0.6
    min_r0_ohm: float = 0.05
    max_r0_ohm: float = 0.35
    updates: int = 0

    def update(self, regressor_A: float, target_V: float) -> float:
        """Track theta in ``target = theta * regressor``.

        ``target`` is OCV(SoC) - V_measured - v1 and the regressor is current.
        Updates are gated when excitation is small or the measurement is
        implausible, which prevents the estimate from running away during rest.
        """
        phi = float(regressor_A)
        if abs(phi) < self.min_abs_current_A:
            return self.r0_ohm
        prediction = self.r0_ohm * phi
        innovation = float(target_V) - prediction
        if abs(innovation) > self.max_innovation_V:
            return self.r0_ohm
        lam = min(max(self.forgetting_factor, 0.9), 1.0)
        denominator = lam + phi * self.covariance * phi
        gain = self.covariance * phi / denominator
        theta = self.r0_ohm + gain * innovation
        covariance = (1.0 - gain * phi) * self.covariance / lam
        self.r0_ohm = float(min(self.max_r0_ohm, max(self.min_r0_ohm, theta)))
        self.covariance = float(max(1e-8, min(1.0, covariance)))
        self.updates += 1
        return self.r0_ohm

    @property
    def covariance_value(self) -> float:
        return self.covariance

    def reset(self, r0_ohm: float) -> None:
        self.r0_ohm = float(r0_ohm)
        self.covariance = 0.05
        self.updates = 0


class ResidualRegressor:
    """Windowed regression residual = offset + slope * current.

    A resistance change creates a current-proportional voltage residual, while
    a voltage-sensor offset creates a current-independent intercept.  This
    separates the two fault signatures much faster than a slow scalar RLS.
    """

    def __init__(
        self,
        *,
        window_s: float = 90.0,
        min_points: int = 20,
        min_current_span_A: float = 4.0,
        max_abs_residual_V: float = 2.0,
    ) -> None:
        from collections import deque

        self.window_s = float(window_s)
        self.min_points = int(min_points)
        self.min_current_span_A = float(min_current_span_A)
        self.max_abs_residual_V = float(max_abs_residual_V)
        self._samples: deque[tuple[float, float, float]] = deque()
        self.offset_V = 0.0
        self.slope_V_per_A = 0.0
        self.valid = False
        self.current_span_A = 0.0

    def add(self, time_s: float, current_A: float, residual_V: float) -> None:
        if abs(current_A) < 0.5 or abs(residual_V) > self.max_abs_residual_V:
            return
        self._samples.append((float(time_s), float(current_A), float(residual_V)))
        cutoff = float(time_s) - self.window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        self._fit()

    def _fit(self) -> None:
        import numpy as np

        if len(self._samples) < self.min_points:
            self.valid = False
            return
        data = np.asarray(self._samples, dtype=float)
        current = data[:, 1]
        residual = data[:, 2]
        span = float(np.ptp(current))
        self.current_span_A = span
        if span < self.min_current_span_A:
            self.valid = False
            return
        design = np.column_stack([np.ones_like(current), current])
        try:
            beta, *_ = np.linalg.lstsq(design, residual, rcond=None)
        except np.linalg.LinAlgError:
            self.valid = False
            return
        self.offset_V = float(beta[0])
        self.slope_V_per_A = float(beta[1])
        self.valid = True

    @property
    def r0_delta_ohm(self) -> float:
        return max(0.0, -self.slope_V_per_A)

    def reset(self) -> None:
        self._samples.clear()
        self.offset_V = 0.0
        self.slope_V_per_A = 0.0
        self.valid = False
        self.current_span_A = 0.0
