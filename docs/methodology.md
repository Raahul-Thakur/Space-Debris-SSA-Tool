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
grid (`step_sec`, 60 s by default). For each object pair and each grid interval
we look at the **range-rate**

$$ g(t) = \mathbf{dr}(t)\cdot \mathbf{dv}(t) $$

where $\mathbf{dr}$ and $\mathbf{dv}$ are the relative position and velocity.
An interval where $g$ goes from negative (closing) to non-negative (opening)
contains a local minimum of the separation, whatever the separations at the two
samples are.

Whether that minimum can be close is decided from a **bound on the distance
inside the interval**, not from the samples. The relative motion is
extrapolated as a straight line forward from the left sample and backward from
the right one; the exact closest approach of each line over the interval is
taken, and a pad of $|\Delta\mathbf{dv}|\,h/2$ (the change in relative velocity
across the step $h$ acting for half the step) is subtracted to cover the
curvature of the real path. Only intervals whose bound is within
`coarse_threshold_km` are refined. This is vectorised over all pairs and costs
about the same as the old sampled-distance check.

!!! note "Why the bound matters"
    Relative speeds in LEO reach about 15 km/s, so at a 60 s step consecutive
    samples can be ~900 km apart. A 0.4 km head-on pass midway between them
    shows a *sampled* distance of ~450 km; screening on sampled distances
    discarded it. With the range-rate bracket and the in-interval bound it is
    found and refined at any step. The regression test builds exactly this
    case from real SGP4 elements.

Besides interior minima, the edges of the window (and of any span where SGP4
fails for one of the objects) are kept as candidates when the pair is already
receding at the start, or still closing at the end, within the threshold: the
closest in-window distance is then at the edge. A pair with no range-rate sign
change at all (for example two identical element sets) falls back to its
closest sample.

**Remaining assumption.** Each grid interval is assumed to hold at most one
minimum. Two minima within one step need a maximum in between, i.e. a
relative-motion turnaround within `step_sec`, which only happens for nearly
co-moving objects at very small separations.

## 3. Time of Closest Approach (TCA)

Every candidate interval is refined separately, so **a pair can have several
events in one window** (for example crossing orbits that meet every half
revolution), each with its own TCA. Events are reported for every refined
minimum within `report_threshold_km`.

Refinement solves $g(t) = 0$ inside the bracket with **Brent's method**,
**re-propagating both objects with SGP4** at every trial time instead of
interpolating between grid samples. It stops when the bracket is narrower than
`tca_tolerance_sec` (1 ms by default). The miss distance and relative velocity
are then taken from the exact SGP4 states at the TCA.

**Numerical accuracy.** Against a brute-force search (1 s scan plus a bounded
scalar minimisation on SGP4 states) over a synthetic 200-object catalogue,
three targets and 72 h, every one of the 10 minima within 25 km was reported,
with TCA within ~1.3 ms and miss distance within 2.5 cm of the reference
(about the reference's own resolution: the refined miss was never larger than
the brute-force one). The previous screen, on the same catalogue, reported 3 of
those 10.
This is numerical agreement *with SGP4*; it says nothing about how close SGP4
is to the real orbits (see section 1), which is the dominant error.

## 4. RAC (RIC) decomposition

The relative position at TCA is projected into the target's **RIC** frame:

$$ \hat{R} = \frac{\mathbf{r}}{|\mathbf{r}|}, \quad
   \hat{C} = \frac{\mathbf{r}\times\mathbf{v}}{|\mathbf{r}\times\mathbf{v}|}, \quad
   \hat{I} = \hat{C}\times\hat{R} $$

giving the **radial**, **along-track**, and **cross-track** miss components.
Conjunction geometry is usually along-track dominated.

## 5. Collision probability (Pc)

We use the **encounter-plane** formulation of Foster: the combined position
uncertainty is projected onto the plane perpendicular to the relative velocity
at TCA and the resulting 2D Gaussian is integrated over the circular hard-body
cross-section of radius $R$.

1. Build the **conjunction plane** perpendicular to the relative velocity at TCA.
2. Project the combined position covariance and the miss vector into that plane.
3. Rotate to the covariance's principal axes ($\sigma_x \ge \sigma_y$, miss
   $(x_m, y_m)$) and integrate over the disk. The integral across each chord
   is a normal-CDF difference, so one adaptive quadrature remains:

$$ P_c = \int_{-R}^{R} \frac{e^{-(x-x_m)^2/2\sigma_x^2}}{\sigma_x\sqrt{2\pi}}
   \left[\Phi\!\left(\frac{\sqrt{R^2-x^2}-y_m}{\sigma_y}\right)
       - \Phi\!\left(\frac{-\sqrt{R^2-x^2}-y_m}{\sigma_y}\right)\right] dx $$

   This is exact for any aspect ratio (it agrees with brute-force 2D
   integration to better than $10^{-6}$ relative in the tests) and costs about
   0.3 ms per event.

**Chan's series** is kept as an alternative (`method="chan"`):

$$ P_c = e^{-v/2}\sum_{m=0}^{\infty}\frac{v^m}{2^m m!}
   \left[1 - e^{-u/2}\sum_{k=0}^{m}\frac{u^k}{2^k k!}\right],
   \quad u=\frac{R^2}{\sigma_x\sigma_y},\;
   v=\frac{x_m^2}{\sigma_x^2}+\frac{y_m^2}{\sigma_y^2} $$

Each term is a Poisson($v/2$) weight times a regularised incomplete gamma
function, so it is summed in log space over the window of significant weights
(no fixed term count, no overflow), returning 0 when the probability
underflows. It is exact for a circular covariance, but its equal-area
treatment of the disk is an approximation otherwise. Against brute-force
integration, with $R$ at 0.1, 0.2 and 0.3 of the minor sigma, it was within
1-8% out to 3σ but up to 3%, 14% and 29% low at 6σ along the minor axis, and
off by tens of per cent to several times once $R$ is comparable to the minor
sigma. That is why it is no longer the default.

**Degenerate inputs.** A combined covariance with no in-plane extent above
1 mm is treated as a point mass: Pc is 1 if the miss lies inside the hard
body, otherwise 0. A covariance flat along only one axis is floored at 1 mm
there and handled exactly by the integral. Pc is always a finite number in $[0, 1]$; the final clamp is
NaN-safe (a NaN, which should no longer occur, maps to 0 with a logged warning
and the event is still tiered on its miss distance). Previously a 25 km miss
with a 1 m sigma overflowed to NaN and the clamp turned it into Pc = 1, a
critical event.

**TLE age.** The synthetic covariance below grows with TLE age; the age used,
and reported on each event, is the age **at that event's TCA**, not at the
start of the window.

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

- TLE/SGP4 position accuracy (~km, degrading with age). TCA refinement is
  exact *with respect to SGP4*, not to the true orbits.
- Synthetic (age-based) covariance, **not** real operator covariance.
- 2D Pc assumes Gaussian, linear relative motion through the encounter (the
  short-encounter assumption).
- At most one minimum per grid interval is assumed (see section 2).
- No atmospheric-drag re-fitting, maneuver detection, or sensor tasking.
