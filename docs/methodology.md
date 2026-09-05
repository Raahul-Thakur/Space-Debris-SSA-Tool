# Scientific methodology

This page documents the models behind the numbers and, importantly, their
**limitations**.

## 1. Orbit propagation (SGP4)

TLEs are propagated with the standard **SGP4** model (via the `sgp4` library),
producing position and velocity in the **TEME** (True Equator, Mean Equinox)
ECI frame. SGP4 is the analytic model TLEs are *fitted to*, so it is the correct
propagator for this data source.

**Accuracy.** SGP4/TLE position error is typically on the order of ~1 km near
epoch and grows to several km over days. This is fundamental to the data source
and bounds everything downstream.

## 2. Close-approach screening

For a chosen **target**, every catalog object is propagated over the same time
grid. A cheap per-step Euclidean distance gives a coarse minimum; objects whose
coarse minimum exceeds `coarse_threshold_km` are discarded.

## 3. Time of Closest Approach (TCA)

The coarse grid brackets but rarely lands on the true minimum. At the true TCA
the **range-rate** vanishes:

$$ g(t) = \mathbf{dr}(t)\cdot \mathbf{dv}(t) = 0 $$

where $\mathbf{dr}$ and $\mathbf{dv}$ are the relative position and velocity. We
locate the coarse minimum, then **bisect** $g$ over the neighbouring interval,
interpolating both state vectors to the root. This refines the miss distance and
the relative velocity at closest approach.

## 4. RAC (RIC) decomposition

The relative position at TCA is projected into the target's **RIC** frame:

$$ \hat{R} = \frac{\mathbf{r}}{|\mathbf{r}|}, \quad
   \hat{C} = \frac{\mathbf{r}\times\mathbf{v}}{|\mathbf{r}\times\mathbf{v}|}, \quad
   \hat{I} = \hat{C}\times\hat{R} $$

giving the **radial**, **along-track**, and **cross-track** miss components.
Conjunction geometry is usually along-track dominated.

## 5. Collision probability (Pc)

We use **Foster's 2D method**:

1. Build the **conjunction plane** perpendicular to the relative velocity at TCA.
2. Project the combined position covariance and the miss vector into that plane.
3. Rotate to the covariance's principal axes ($\sigma_x, \sigma_y$) and evaluate
   **Chan's series** for a circular hard-body cross-section of radius $R$:

$$ P_c = e^{-v/2}\sum_{m=0}^{\infty}\frac{v^m}{2^m m!}
   \left[1 - e^{-u/2}\sum_{k=0}^{m}\frac{u^k}{2^k k!}\right],
   \quad u=\frac{R^2}{\sigma_x\sigma_y},\;
   v=\frac{x_m^2}{\sigma_x^2}+\frac{y_m^2}{\sigma_y^2} $$

### Where the covariance comes from — and the big caveat

!!! danger "TLEs carry no covariance"
    Operational Pc uses covariance supplied by the owner/operator or the
    18th Space Defense Squadron. **TLEs do not include uncertainty.** This tool
    therefore *synthesises* a covariance as a documented surrogate:

    - A diagonal **RIC** 1-σ uncertainty (radial / along-track / cross-track),
      with along-track the largest — matching how SGP4 error actually behaves.
    - The 1-σ values **grow linearly with TLE age** (`age_growth_m_per_day`),
      encoding the intuition that stale elements are less trustworthy.

    Consequently the Pc values here are **illustrative, not operational**. They
    are useful for *relative* ranking and for demonstrating the method — not for
    real conjunction-avoidance decisions.

## 6. Risk classification

Each event takes the highest tier whose **miss-distance OR Pc** condition is met:

| Tier      | Default trigger                                  |
|-----------|--------------------------------------------------|
| critical  | miss ≤ 1 km **or** Pc ≥ 1e-4                      |
| watch     | miss ≤ 5 km **or** Pc ≥ 1e-5                      |
| nominal   | everything else                                  |

Thresholds are fully configurable in `configs/default.yaml`.

## Summary of limitations

- TLE/SGP4 position accuracy (~km, degrading with age).
- Synthetic (age-based) covariance, **not** real operator covariance.
- 2D analytic Pc assumes Gaussian, linear relative motion through the encounter.
- No atmospheric-drag re-fitting, maneuver detection, or sensor tasking.
