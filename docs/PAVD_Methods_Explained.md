# PAVD Methods: Technical Documentation

## Overview

This document provides a detailed explanation of the Plant Area Volume Density (PAVD) and Plant Area Index (PAI) estimation methods implemented in `pylidar_tls_canopy`, based on the methodology from **Jupp et al. (2009)**.

### Key Concepts

- **PAI (Plant Area Index)**: The one-sided plant area per unit ground area (m²/m²), cumulative from the top of the canopy down to a given height
- **PAVD (Plant Area Volume Density)**: The one-sided plant area per unit volume (m²/m³), representing the vertical derivative of PAI
- **Pgap (Gap Probability)**: The probability that a laser beam passes through the canopy without hitting vegetation at a given angle and height

---

## Table of Contents

1. [Theoretical Foundation](#theoretical-foundation)
2. [Data Binning and Organization](#data-binning-and-organization)
3. [Gap Probability Calculation](#gap-probability-calculation)
4. [PAI Estimation Methods](#pai-estimation-methods)
   - [Hinge Method](#1-hinge-method)
   - [Linear Method](#2-linear-method)
   - [Weighted/Solid Angle Method](#3-weightedsolid-angle-method)
5. [PAVD Calculation](#pavd-calculation)
6. [Mean Leaf Angle Estimation](#mean-leaf-angle-estimation)
7. [Ground Plane Fitting](#ground-plane-fitting)
8. [Target Weighting Schemes](#target-weighting-schemes)
9. [Mathematical Summary](#mathematical-summary)
10. [References](#references)

---

## Theoretical Foundation

### Beer-Lambert Law for Vegetation

The fundamental relationship underlying all methods is the Beer-Lambert law adapted for vegetation canopies:

```
Pgap(θ, z) = exp[-k(θ) × PAI(z)]
```

Where:
- `Pgap(θ, z)` = gap probability at zenith angle θ and height z
- `k(θ)` = extinction coefficient (function of zenith angle θ and leaf angle distribution)
- `PAI(z)` = cumulative plant area index from canopy top to height z

Rearranging to solve for PAI:

```
PAI(z) = -ln[Pgap(θ, z)] / k(θ)
```

The challenge is estimating the extinction coefficient k(θ), which depends on the Mean Leaf Angle (MLA) distribution. The three methods (Hinge, Linear, Weighted) represent different approaches to handling this uncertainty.

---

## Data Binning and Organization

### 3D Binning Structure

The TLS data is organized into a 3D array with dimensions:

1. **Zenith angle bins** (θ): Typically 5° resolution, from min_z to max_z (e.g., 35° to 70°)
2. **Azimuth angle bins** (φ): Typically 90° resolution, covering 0° to 360°
3. **Height bins** (z): Typically 0.5 m resolution, from ground to max canopy height

```python
# In code:
self.target_output = np.zeros((nzbins, nabins, nhbins), dtype=np.float32)
self.shot_output = np.zeros((nzbins, nabins, 1), dtype=np.float32)
```

### Coordinate System

- **Zenith angle (θ)**: Angle from vertical (nadir = 0°, horizontal = 90°)
- **Azimuth angle (φ)**: Horizontal angle from north
- **Height (z)**: Height above the fitted ground plane

---

## Gap Probability Calculation

### Step 1: Target and Shot Counting

For each bin (θ, φ, z):
- **Shots**: Total number of laser pulses fired in that angular direction
- **Targets**: Weighted count of returns at each height

### Step 2: Cover Calculation

The canopy cover at each zenith-azimuth-height bin is:

```
Cover(θ, φ, z) = Cumulative_Targets(θ, φ, z) / Shots(θ, φ)
```

The cumulative sum is taken along the height axis (from top to bottom), representing the total number of returns above each height level.

### Step 3: Gap Probability

```
Pgap(θ, φ, z) = 1 - Cover(θ, φ, z)
```

### Step 4: Azimuthal Averaging

Gap probability is averaged across azimuth bins to reduce noise:

```
Pgap(θ, z) = mean_φ[Pgap(θ, φ, z)]
```

**Implementation** (from `plant_profile.py:184-202`):
```python
def get_pgap_theta_z(self, min_azimuth=0, max_azimuth=360, invert=False):
    # Calculate cover as cumulative targets / shots
    cover_theta_z = np.cumsum(self.target_output, axis=2) / self.shot_output

    # Average over specified azimuth range
    cover_theta_z = np.nanmean(cover_theta_z[:, idx, :], axis=1)

    # Convert to gap probability
    self.pgap_theta_z = 1 - cover_theta_z
```

---

## PAI Estimation Methods

All three methods estimate PAI from the gap probability Pgap(θ, z), but differ in how they handle the extinction coefficient k(θ).

### 1. Hinge Method

**Principle**: Uses a single "hinge" angle where the extinction coefficient is theoretically constant, regardless of leaf angle distribution.

**Hinge Angle**: θ_h = arctan(π/2) ≈ 57.5°

At this angle, for a spherical leaf angle distribution:
```
k(θ_h) = 1.1
```

**Formula**:
```
PAI(z) = -1.1 × ln[Pgap(θ_h, z)]
```

**Advantages**:
- Simple and robust
- Not sensitive to leaf angle distribution assumptions
- Good for comparing across different canopies

**Disadvantages**:
- Uses only one angle, ignoring other available data
- May be noisy if few returns at hinge angle

**Implementation** (`plant_profile.py:236-250`):
```python
def calcHingePlantProfiles(self):
    zenith_bin_r = np.radians(self.zenith_bin)

    # Find bin closest to hinge angle
    hingeindex = np.argmin(np.abs(zenith_bin_r - np.arctan(np.pi / 2)))

    # Calculate PAI from gap probability at hinge angle
    pai = -1.1 * np.log(self.pgap_theta_z[hingeindex, :])

    return pai
```

---

### 2. Linear Method

**Principle**: Uses multiple zenith angles and assumes a linear relationship between contact number and a transformed zenith variable.

**Theory**: For randomly distributed leaves, the extinction coefficient can be approximated as:

```
k(θ) ≈ PAI_v × G(θ) / cos(θ)
```

Where G(θ) is the projection function. Jupp et al. (2009) showed this can be linearized:

```
-ln[Pgap(θ, z)] = PAI_v(z) × x(θ) + PAI_h(z)
```

Where:
- `x(θ) = 2 × tan(θ) / π` (transformed zenith variable)
- `PAI_v(z)` = vertical component of PAI
- `PAI_h(z)` = horizontal component of PAI
- `PAI(z) = PAI_v(z) + PAI_h(z)` (total PAI)

**Procedure**:
1. Transform contact number: `y = -ln[Pgap(θ, z)]`
2. Transform zenith angle: `x = 2 × tan(θ) / π`
3. Fit linear regression: `y = PAI_v × x + PAI_h`
4. Calculate total: `PAI = PAI_v + PAI_h`

**Constraints**:
- If PAI_v < 0, set PAI_v = 0 and PAI_h = mean(y)
- If PAI_h < 0, set PAI_h = 0 and PAI_v = mean(y/x)

**Advantages**:
- Uses all available zenith angles
- Provides additional information (Mean Leaf Angle)
- More stable than single-angle methods

**Disadvantages**:
- Assumes linear relationship holds
- Sensitive to outliers at extreme angles
- Requires sufficient zenith angle range

**Implementation** (`plant_profile.py:204-234`):
```python
def calcLinearPlantProfiles(self, calc_mla=False):
    zenith_bin_r = np.radians(self.zenith_bin)

    # Calculate contact number (K_theta)
    kthetal = np.log(self.pgap_theta_z)

    # Transform zenith angle
    xtheta = np.abs(2 * np.tan(zenith_bin_r) / np.pi)

    # Fit linear model for each height
    for i, h in enumerate(self.height_bin):
        y = -kthetal[:, i]

        # Linear regression: y = PAI_v * x + PAI_h
        result = np.linalg.lstsq([[xtheta], [ones]], y)
        paiv[i] = result[0]  # Vertical component
        paih[i] = result[1]  # Horizontal component

        # Apply constraints
        if result[0] < 0:
            paih[i] = np.nanmean(y)
            paiv[i] = 0.0
        if result[1] < 0:
            paiv[i] = np.mean(y / xtheta)
            paih[i] = 0.0

    pai = paiv + paih

    if calc_mla:
        # Mean Leaf Angle from components
        mla = np.degrees(np.arctan2(paiv, paih))
        return pai, mla
    else:
        return pai
```

---

### 3. Weighted/Solid Angle Method

**Principle**: Combines information from all zenith angles using solid angle weighting, normalized by the gap probability at the bottom of the profile.

**Theory**: The method weights contributions from each zenith angle by the solid angle it represents in the hemisphere.

**Solid Angle Weight**:
```
w(θ) = 2π × sin(θ) × Δθ
```

**Normalized Weight**:
```
w_n(θ) = w(θ) / Σw(θ)   [for valid angles]
```

**Formula**:
```
PAI(z) = PAI_total × Σ[w_n(θ) × ln[Pgap(θ, z)] / ln[Pgap(θ, z_max)]]
```

Where:
- `PAI_total` = total PAI (estimated from hinge method)
- `z_max` = maximum height (canopy top)
- The ratio `ln[Pgap(θ, z)] / ln[Pgap(θ, z_max)]` normalizes the profile

**Advantages**:
- Uses all available angles optimally
- Accounts for geometric sampling differences
- Generally most accurate for complex canopies
- Smooths out noise through weighted averaging

**Disadvantages**:
- Depends on total PAI estimate (uses hinge method)
- More computationally complex
- Harder to interpret physically

**Implementation** (`plant_profile.py:252-276`):
```python
def calcSolidAnglePlantProfiles(self, total_pai=None):
    zenith_bin_r = np.radians(self.zenith_bin)
    zenith_bin_size = zenith_bin_r[1] - zenith_bin_r[0]

    # Calculate solid angle weight for each zenith bin
    w = 2 * np.pi * np.sin(zenith_bin_r) * zenith_bin_size

    # Normalize weights (only for valid angles with Pgap < 1)
    wn = w / np.sum(w[self.pgap_theta_z[:, -1] < 1])

    ratio = np.zeros(self.pgap_theta_z.shape[1])

    # For each zenith angle with valid data
    for i in range(zenith_bin_r.shape[0]):
        if self.pgap_theta_z[i, -1] < 1:
            # Numerator: contact number at each height
            num = np.log(self.pgap_theta_z[i, :])

            # Denominator: contact number at canopy bottom
            den = np.log(self.pgap_theta_z[i, -1])

            # Accumulate weighted ratio
            ratio += wn[i] * num / den

    # Scale by total PAI (from hinge method if not provided)
    if total_pai is None:
        hpp_pai = self.calcHingePlantProfiles()
        total_pai = np.max(hpp_pai)

    pai = total_pai * ratio

    return pai
```

---

## PAVD Calculation

PAVD is the vertical derivative of PAI, representing plant area density per unit volume.

### Formula

```
PAVD(z) = dPAI/dz ≈ ΔPAI / Δz
```

### Two Methods

**1. Central Difference (default)**:
```python
pavd = np.gradient(pai_z, hres)
```

Uses central differences, which is more accurate for smooth profiles.

**2. Forward Difference**:
```python
pavd = np.diff(pai_z, append=0) / hres
```

Simpler but can be noisier.

### Physical Interpretation

- **PAI**: Total one-sided leaf area above height z, per unit ground area
- **PAVD**: One-sided leaf area between z and z+dz, per unit volume
- **Units**: PAI is dimensionless (m²/m²), PAVD has units of m⁻¹ (m²/m³)

**Implementation** (`plant_profile.py:278-286`):
```python
def get_pavd(self, pai_z, central=True):
    if not central:
        pavd = np.diff(pai_z, n=1, append=0) / self.hres
    else:
        pavd = np.gradient(pai_z, self.hres)
    return pavd
```

---

## Mean Leaf Angle Estimation

The linear method provides an estimate of the Mean Leaf Angle (MLA) from the vertical and horizontal PAI components.

### Formula

```
MLA = arctan(PAI_v / PAI_h)
```

### Physical Interpretation

- **MLA ≈ 0°**: Horizontal leaves (planophile)
- **MLA ≈ 45°**: Uniform distribution
- **MLA ≈ 57.5°**: Spherical distribution (most common assumption)
- **MLA ≈ 90°**: Vertical leaves (erectophile)

### Relationship to Leaf Angle Distribution

The MLA relates to the leaf angle distribution through the G-function (projection function):

```
G(θ) = ∫[0 to π/2] cos(θ_L) × f(θ_L) dθ_L
```

Where:
- `θ_L` = leaf inclination angle
- `f(θ_L)` = leaf angle distribution

For ellipsoidal distributions, the MLA approximates the mean of f(θ_L).

**Implementation** (from `calcLinearPlantProfiles`):
```python
# After calculating PAI_v and PAI_h from linear regression:
mla = np.degrees(np.arctan2(paiv, paih))
```

---

## Ground Plane Fitting

Accurate height estimation requires fitting a ground plane to the lowest returns.

### Method: Huber's T-Norm Robust Regression

Uses robust linear regression to fit a plane to minimum-z grid points, resistant to outliers from vegetation or noise.

### Plane Equation

```
z = a + b×x + c×y
```

Where:
- `a` = ground intercept (elevation at origin)
- `b` = slope in x-direction
- `c` = slope in y-direction

### Procedure

1. **Create minimum-z grid**: For each grid cell, find the lowest z value
2. **Weight by range**: Closer points get higher weight (w = 1/r)
3. **Robust fit**: Use Huber's T-norm to fit plane, downweighting outliers
4. **Height correction**: Calculate height above ground for each point

```
height = z - (b×x + c×y + a)
```

### Slope and Aspect

From the plane parameters:

```
Slope = arctan(√(b² + c²))
Aspect = arctan(b / c)
```

**Implementation** (`plant_profile.py:446-470`):
```python
def plane_fit_hubers(x, y, z, w=None, reportfile=None):
    if w is None:
        w = np.ones(z.shape)

    # Weighted coordinates
    wz = w * z
    wxy = np.vstack((w, x*w, y*w)).T

    # Robust regression using Huber's T-norm
    huber_t = sm.RLM(wz, wxy, M=sm.robust.norms.HuberT())
    huber_results = huber_t.fit()

    # Extract parameters [intercept, slope_x, slope_y]
    params = huber_results.params

    return {
        'Parameters': params,
        'Slope': np.degrees(np.arctan(np.sqrt(params[1]**2 + params[2]**2))),
        'Aspect': np.degrees(np.arctan(params[1] / params[2]))
    }
```

---

## Target Weighting Schemes

Different weighting schemes handle multi-return pulses differently.

### 1. WEIGHTED (Recommended)

Each return is weighted inversely by the total number of returns in that pulse:

```
w = 1 / target_count
```

**Purpose**: Normalizes for varying number of returns per pulse, preventing over-counting dense areas.

### 2. FIRST

Only the first return from each pulse is counted:

```
w = 1 if target_index == 1, else 0
```

**Purpose**: Emphasizes canopy top, reduces multiple scattering effects.

### 3. ALL

All returns are counted equally:

```
w = 1 for all returns
```

**Purpose**: Maximizes point density but may overestimate in dense canopies.

### 4. FIRSTLAST

First and last returns each get weight 0.5:

```
w = 0.5 for first and last returns, 0 otherwise
```

**Purpose**: Balances canopy top and bottom information.

**Implementation** (`plant_profile.py:56-80`):
```python
def add_targets(self, target_height, target_index, target_count,
                target_zenith, target_azimuth, method='WEIGHTED'):

    h_idx = (target_height - self.min_h) // self.hres
    z_idx = (target_zenith - self.min_z_r) // self.zres_r
    a_idx = target_azimuth // self.ares_r

    if method == 'WEIGHTED':
        w = 1 / target_count
    elif method == 'FIRST':
        idx = (target_index == 1)
        w = np.ones(np.count_nonzero(idx))
    elif method == 'ALL':
        w = np.ones(target_height.shape[0])
    elif method == 'FIRSTLAST':
        w = np.full(target_count.shape[0], 0.5)

    # Accumulate weighted returns into bins
    sum_by_index_3d(w, z_idx, a_idx, h_idx, self.target_output)
```

---

## Mathematical Summary

### Complete Workflow

1. **Data binning**:
   ```
   Targets(θ, φ, z) = Σ[w_i]  for points in bin (θ, φ, z)
   Shots(θ, φ) = count of pulses in direction (θ, φ)
   ```

2. **Gap probability**:
   ```
   Cover(θ, φ, z) = CumulativeSum_z[Targets(θ, φ, z)] / Shots(θ, φ)
   Pgap(θ, z) = 1 - Mean_φ[Cover(θ, φ, z)]
   ```

3. **Contact number**:
   ```
   K(θ, z) = -ln[Pgap(θ, z)]
   ```

4. **PAI estimation**:

   **Hinge**:
   ```
   PAI(z) = 1.1 × K(θ_h, z)
   ```

   **Linear**:
   ```
   K(θ, z) = PAI_v(z) × 2tan(θ)/π + PAI_h(z)
   PAI(z) = PAI_v(z) + PAI_h(z)
   MLA(z) = arctan[PAI_v(z) / PAI_h(z)]
   ```

   **Weighted**:
   ```
   w(θ) = 2π sin(θ) Δθ
   w_n(θ) = w(θ) / Σw(θ)
   PAI(z) = PAI_max × Σ[w_n(θ) × K(θ,z) / K(θ,z_max)]
   ```

5. **PAVD**:
   ```
   PAVD(z) = dPAI(z)/dz
   ```

---

## Comparison of Methods

| Method | Advantages | Disadvantages | Best Use Case |
|--------|-----------|---------------|---------------|
| **Hinge** | Simple, robust, fast | Uses only one angle | Quick assessment, method comparison |
| **Linear** | Provides MLA, uses multiple angles | Assumes linear model | Research, leaf angle analysis |
| **Weighted** | Most accurate, uses all data optimally | Complex, depends on PAI_total | Final analysis, complex canopies |

### Typical Agreement

In practice:
- Hinge and Weighted typically agree within 5-10%
- Linear may differ more if leaf angle deviates from spherical
- All methods should show similar vertical profile shape

---

## References

### Primary Reference

**Jupp, D.L.B., Culvenor, D.S., Lovell, J.L., Newnham, G.J., Strahler, A.H., and Woodcock, C.E. (2009)**
*Estimating forest LAI profiles and structural parameters using a ground-based laser called 'Echidna'®*
Tree Physiology, 29(2), 171-181.
DOI: [10.1093/treephys/tpn022](https://doi.org/10.1093/treephys/tpn022)

### Related References

**Calders, K., Newnham, G., Burt, A., Murphy, S., Raumonen, P., Herold, M., Culvenor, D., Avitabile, V., Disney, M., Armston, J., and Kaasalainen, M. (2015)**
*Nondestructive estimates of above-ground biomass using terrestrial laser scanning*
Methods in Ecology and Evolution, 6(2), 198-208.

**Ni-Meister, W., Jupp, D.L.B., and Dubayah, R. (2001)**
*Modeling lidar waveforms in heterogeneous and discrete canopies*
IEEE Transactions on Geoscience and Remote Sensing, 39(9), 1943-1958.

**Norman, J.M. and Campbell, G.S. (1989)**
*Canopy structure*
In: Plant Physiological Ecology, pp. 301-325. Springer.

---

## Implementation Notes

### Processing Parameters

Typical values used in `batch_pavd_profiles.py`:

- **Height resolution (hres)**: 0.5 m
- **Zenith resolution (zres)**: 5°
- **Azimuth resolution (ares)**: 90°
- **Zenith range**: 35° to 70°
- **Height range**: 0 to 50 m
- **Reflectance threshold**: -20 dB
- **Target weighting**: WEIGHTED

### Quality Considerations

1. **Zenith angle range**:
   - Too narrow: Insufficient angular diversity
   - Too wide: Low return density at extreme angles
   - Optimal: 35-70° balances coverage and density

2. **Height resolution**:
   - Finer (0.25 m): More detail but noisier
   - Coarser (1.0 m): Smoother but less vertical detail
   - 0.5 m is typical compromise

3. **Minimum returns threshold**:
   - Bins with few returns produce unreliable Pgap
   - Linear method requires sufficient zenith bins (>2) per height

4. **Ground plane fitting**:
   - Critical for accurate height assignment
   - Robust fitting handles outliers from understory
   - Grid resolution affects smoothness vs. detail

---

## Troubleshooting

### Common Issues

**1. Negative PAI values**
- Cause: Pgap > 1 due to insufficient shots or registration errors
- Solution: Check scan quality, alignment, and shot counts

**2. Unrealistic MLA values**
- Cause: Insufficient zenith angle range or poor linear fit
- Solution: Expand zenith range, check for outliers

**3. Noisy PAVD profiles**
- Cause: Low point density or small height bins
- Solution: Increase height resolution (hres) or apply smoothing

**4. Underestimation near ground**
- Cause: Occlusion, incomplete scanning of understory
- Solution: Use multiple scan positions, check minimum zenith angle

**5. Method disagreement**
- Cause: Non-spherical leaf angle distribution or clumping
- Solution: Use linear method to check MLA, consider clumping corrections

---

## Glossary

- **Beer-Lambert Law**: Exponential attenuation of radiation through a medium
- **Contact Number**: -ln(Pgap), proportional to PAI
- **Extinction Coefficient**: k(θ), relates gap probability to PAI for a given angle
- **G-function**: Projection function describing leaf orientation effects
- **Gap Probability**: Probability a laser beam penetrates to a given height
- **Hinge Angle**: Zenith angle (≈57.5°) where k is constant for spherical distribution
- **Mean Leaf Angle**: Average angle of leaves from horizontal
- **PAI**: Plant Area Index, cumulative one-sided plant area
- **PAVD**: Plant Area Volume Density, vertical derivative of PAI
- **Solid Angle**: Angular area on unit sphere, proportional to sin(θ)
- **Zenith Angle**: Angle from vertical (nadir)

---

*Document created: 2025-10-25*
*Author: Tim Devereux*
*Version: 1.0*
