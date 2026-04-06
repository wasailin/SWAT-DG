# Sensitivity Analysis & Calibration Methods: A Comprehensive Guide

**Context:** SWAT hydrological model calibration using SPOTPY
**Date:** March 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Part I: Sensitivity Analysis Methods](#2-part-i-sensitivity-analysis-methods)
   - [2.1 What is Sensitivity Analysis?](#21-what-is-sensitivity-analysis)
   - [2.2 FAST (Fourier Amplitude Sensitivity Test)](#22-fast-fourier-amplitude-sensitivity-test)
   - [2.3 Sobol Method](#23-sobol-method)
   - [2.4 FAST vs. Sobol: Side-by-Side Comparison](#24-fast-vs-sobol-side-by-side-comparison)
3. [Part II: Calibration Algorithms](#3-part-ii-calibration-algorithms)
   - [3.1 What is Model Calibration?](#31-what-is-model-calibration)
   - [3.2 Monte Carlo (MC)](#32-monte-carlo-mc)
   - [3.3 Latin Hypercube Sampling (LHS)](#33-latin-hypercube-sampling-lhs)
   - [3.4 SCE-UA](#34-sce-ua-shuffled-complex-evolution---university-of-arizona)
   - [3.5 DREAM](#35-dream-differential-evolution-adaptive-metropolis)
   - [3.6 Calibration Algorithms: Side-by-Side Comparison](#36-calibration-algorithms-side-by-side-comparison)
4. [Part III: SPOTPY Implementation Notes](#4-part-iii-spotpy-implementation-notes)
5. [Part IV: Additional Algorithms — SUFI-2 & NSGA-II](#5-part-iv-additional-algorithms--sufi-2--nsga-ii)
   - [5.1 SUFI-2 (Sequential Uncertainty Fitting)](#51-sufi-2-sequential-uncertainty-fitting)
   - [5.2 NSGA-II (Multi-Objective Genetic Algorithm)](#52-nsga-ii-multi-objective-genetic-algorithm)
   - [5.3 Should We Add Them?](#53-should-we-add-them)
6. [Part V: Diagnostic-Guided Calibration](#6-part-v-diagnostic-guided-calibration)
   - [6.1 The Core Idea](#61-the-core-idea)
   - [6.2 Hydrograph Components and Their SWAT Parameters](#62-hydrograph-components-and-their-swat-parameters)
   - [6.3 Key Methodologies](#63-key-methodologies)
   - [6.4 Diagnostic-Guided Calibration Algorithm](#64-diagnostic-guided-calibration-algorithm)
   - [6.5 What Already Exists in SWAT-DG](#65-what-already-exists-in-swat-dg)
   - [6.6 Gaps and Implementation Roadmap](#66-gaps-and-implementation-roadmap)
7. [Part VI: Practical Workflow Recommendations](#7-part-vi-practical-workflow-recommendations)
8. [References](#8-references)

---

## 1. Introduction

Hydrological models like SWAT have many parameters (often 10-30+) that control
processes like surface runoff, groundwater flow, evapotranspiration, and channel
routing. Two fundamental questions arise:

1. **Which parameters matter most?** → *Sensitivity Analysis (SA)*
2. **What are the best parameter values?** → *Calibration*

This report explains the major methods available for each task, written for
practitioners who need to understand *what these methods do*, *when to use them*,
and *what their limitations are*.

---

## 2. Part I: Sensitivity Analysis Methods

### 2.1 What is Sensitivity Analysis?

Sensitivity analysis answers: **"If I change parameter X, how much does the
model output change?"**

There are two broad categories:

| Type | What it measures | Example |
|------|-----------------|---------|
| **Local SA** | Effect of small perturbation around one point | One-at-a-time (OAT) method |
| **Global SA** | Effect across the entire parameter range, including interactions | FAST, Sobol |

Both FAST and Sobol are **global, variance-based** methods. They decompose the
total variance of the model output into contributions from each parameter.

**Key concept — Sensitivity Indices:**

- **First-order index (S1):** The fraction of output variance explained by
  varying parameter *i* alone, averaging over all other parameters. Measures the
  *direct, individual* effect.

- **Total-order index (ST):** The fraction of output variance explained by
  parameter *i* including all its interactions with other parameters. Always
  ST >= S1.

- **Interaction effect:** ST - S1. If this is large, the parameter's influence
  depends heavily on the values of other parameters.

Think of it like a team sport analogy:
> **S1** = how many goals a player scores independently.
> **ST** = how many goals involve that player (solo + assists).
> **ST - S1** = how many goals come from teamwork with others.

---

### 2.2 FAST (Fourier Amplitude Sensitivity Test)

#### How It Works — The Core Idea

FAST uses a clever mathematical trick to explore a multi-dimensional parameter
space using a **single curve** through that space.

**Step-by-step:**

1. **Assign a unique frequency to each parameter.** For example, with 3
   parameters: CN2 gets frequency ω₁ = 1, ESCO gets ω₂ = 7, GW_DELAY gets
   ω₃ = 11. These frequencies must be *incommensurate* (no integer ratios
   between them).

2. **Define a search curve.** Each parameter value is written as a periodic
   function of a single variable *s*:
   ```
   x₁(s) = G₁(sin(ω₁ · s))
   x₂(s) = G₂(sin(ω₂ · s))
   x₃(s) = G₃(sin(ω₃ · s))
   ```
   where G is a transformation function that maps sin values to the parameter's
   range.

3. **Sample along the curve.** Run the model at N evenly-spaced points along *s*
   from -π to π.

4. **Fourier analysis.** Apply a Fourier transform to the model outputs. The
   power at frequency ω₁ (and its harmonics 2ω₁, 3ω₁, ...) tells you how
   much output variance is caused by parameter 1.

5. **Compute S1.** The first-order index for parameter *i* is:
   ```
   S1_i = (power at ω_i and harmonics) / (total variance)
   ```

#### Original FAST vs. Extended FAST (eFAST)

| Feature | Original FAST (Cukier 1973) | Extended FAST (Saltelli 1999) |
|---------|-----------------------------|-------------------------------|
| Computes S1 | Yes | Yes |
| Computes ST | No | **Yes** |
| How | Single search curve | Multiple search curves (one per parameter) |
| Cost | N total evaluations | N × k evaluations (k = number of parameters) |

**eFAST** is what SPOTPY implements. It runs k separate sampling sets — in each
set, one "target" parameter gets the highest frequency (so its contribution
dominates the spectrum), while the others share lower frequencies. This allows
computing both S1 and ST for the target parameter.

#### Minimum Sample Size

SPOTPY's FAST implementation uses interference factor M = 4. The minimum samples
per parameter for valid Fourier decomposition:

```
N_min_per_param = 2 × M × ω_max + 1 = 65
```

In the SWAT-DG codebase, this is enforced:
```python
_fast_min_per_param = 65  # calibrator.py line 714
```

Total model evaluations = N_per_param × k (number of parameters).

**Example:** 10 parameters × 65 samples = **650 model runs minimum**.
For more reliable results, 100-200 per parameter is recommended: **1,000-2,000
runs**.

#### Constraints and Limitations

| Constraint | Explanation |
|-----------|-------------|
| **Frequency aliasing** | If frequencies aren't chosen carefully, the Fourier spectrum of one parameter can "leak" into another's frequency. eFAST mitigates this but doesn't eliminate it. |
| **Assumes uniform distribution** | Standard FAST assumes parameters are uniformly distributed. Non-uniform distributions require transformation functions. |
| **No second-order indices** | FAST gives S1 and ST, but NOT S_ij (the specific pairwise interaction between parameters i and j). You can infer that interactions exist (ST - S1 > 0) but not *which* parameters interact. |
| **Order-dependent** | Results must arrive in the same order as the sampling curve. Cannot use unordered parallel execution. In SPOTPY: must use `parallel="mpc"` (ordered), not `"umpc"` (unordered). |
| **Assumes smoothness** | The method works best when the model response is a reasonably smooth function of the parameters. Highly discontinuous responses can produce noisy indices. |

#### When to Use FAST

- **Best for:** Ranking parameters by importance when you have a limited
  computational budget.
- **Sweet spot:** 5-30 parameters, 500-3,000 model evaluations.
- **In SWAT calibration:** Use FAST first to identify the 5-8 most sensitive
  parameters, then calibrate only those parameters (saving significant
  computation).

---

### 2.3 Sobol Method

#### How It Works — The Core Idea

Sobol's method decomposes the model output into a sum of terms of increasing
dimensionality — the **ANOVA-like decomposition** (Analysis of Variance):

```
f(x) = f₀ + Σ fᵢ(xᵢ) + Σ fᵢⱼ(xᵢ,xⱼ) + ... + f₁₂...ₖ(x₁,...,xₖ)
```

In plain English: the model output equals a constant (mean) + individual
parameter effects + pairwise interaction effects + three-way interactions + ...
all the way up to the k-parameter interaction.

**Step-by-step (Saltelli sampling scheme):**

1. **Generate two independent quasi-random matrices** A and B, each of size
   N × k (N samples, k parameters). These use **Sobol sequences** — special
   low-discrepancy sequences that fill the parameter space more uniformly than
   pure random numbers.

2. **Create cross-matrices.** For each parameter i, create matrix AB_i: take
   matrix A, but replace column i with column i from B. This isolates the
   effect of parameter i.

3. **Run the model** for all sample sets: A, B, and each AB_i.

4. **Compute indices** using the model outputs:
   - **S1_i** (first-order): How much does the output change when *only*
     parameter i changes (from A to AB_i), averaged over all other parameter
     combinations?
   - **ST_i** (total-order): How much residual variance remains when all
     parameters *except* i are fixed?
   - **S_ij** (second-order): The additional variance explained by the
     interaction between parameters i and j beyond their individual effects.

#### Sample Size Requirements

The Saltelli sampling scheme requires:

```
Total evaluations = N × (2k + 2)
```

where N = base sample size (typically 500-1,000) and k = number of parameters.

**Example:** 10 parameters, N = 1,000:
```
1,000 × (2 × 10 + 2) = 22,000 model evaluations
```

Compare this to FAST for the same 10 parameters:
```
FAST: 10 × 100 = 1,000 evaluations
Sobol: 22,000 evaluations → 22x more expensive!
```

This is why Sobol is significantly more computationally demanding.

#### Sobol Sequences — Why They Matter

Regular random numbers tend to clump and leave gaps. Sobol sequences are
**low-discrepancy** (quasi-random): they systematically fill the space so
every region gets roughly equal coverage.

```
Random (MC):          Sobol sequence:
·  · ··               ·   ·   ·   ·
  ·     ·             ·   ·   ·   ·
·    ·                ·   ·   ·   ·
  ··    ·             ·   ·   ·   ·
     ·   ·  ·         ·   ·   ·   ·
```

This matters because better space coverage means the variance estimates converge
faster (i.e., you need fewer samples to get stable sensitivity indices).

#### Constraints and Limitations

| Constraint | Explanation |
|-----------|-------------|
| **Very high computational cost** | N × (2k + 2) evaluations. For k = 20 parameters with N = 1,000: **42,000 runs**. Often impractical for expensive models. |
| **Convergence issues** | With too few base samples (small N), the indices can be noisy, negative, or greater than 1 — indicating insufficient convergence. N >= 500 per parameter is recommended. |
| **Assumes independence** | Parameters must be sampled independently. Correlated parameters require special treatment (e.g., Kucherenko's extension). |
| **SPOTPY limitation** | SPOTPY does not implement the full Saltelli sampling scheme. Instead, the SWAT-DG codebase uses an **approximate** approach: LHS sampling + binned variance analysis. This gives rough first-order indices but is not a rigorous Sobol analysis. A warning is emitted in the code. |

#### When to Use Sobol

- **Best for:** When you need the **full interaction structure** — not just
  which parameters matter, but which pairs (or groups) of parameters interact.
- **Typical use:** Research publications requiring rigorous sensitivity analysis.
- **In SWAT calibration:** Rarely used due to cost. A SWAT model running 60
  seconds per evaluation with 20 parameters needs ~42,000 × 60s = **29 days**
  of computation. FAST achieves comparable ranking in a fraction of the time.

---

### 2.4 FAST vs. Sobol: Side-by-Side Comparison

| Criterion | FAST (eFAST) | Sobol |
|-----------|-------------|-------|
| **What it computes** | S1, ST | S1, ST, S_ij (pairwise) |
| **Cost (10 params)** | ~1,000 runs | ~22,000 runs |
| **Cost (20 params)** | ~2,000 runs | ~42,000 runs |
| **Cost scaling** | O(k) — linear in # params | O(k²) — quadratic |
| **Interaction detail** | Knows interactions exist (ST-S1) but not *which pairs* | Full pairwise decomposition |
| **Implementation in SPOTPY** | Native, rigorous (eFAST) | Approximate only (binned variance) |
| **Parallelization** | Must be ordered (`mpc`) | Can be unordered (`umpc`) |
| **Parameter ranking accuracy** | Excellent for S1 and ST | Gold standard (with enough samples) |
| **Practical for SWAT?** | Yes — the go-to method | Only for small models or HPC |
| **Recommended use** | Day-to-day SA before calibration | Deep research on parameter interactions |

**Bottom line:** For SWAT modeling, **FAST is the practical choice**. Use Sobol
only when you specifically need pairwise interaction indices and have the
computational budget.

---

## 3. Part II: Calibration Algorithms

### 3.1 What is Model Calibration?

Calibration is the process of finding parameter values that make the model's
output match observed data as closely as possible. This is formulated as an
**optimization problem:**

```
Find parameters θ that maximize (or minimize) an objective function:
    θ* = argmax  Obj(simulated(θ), observed)
              θ
```

Common objective functions in hydrology:

| Metric | Formula | Perfect Score | Meaning |
|--------|---------|---------------|---------|
| **NSE** | 1 - Σ(sim-obs)² / Σ(obs-mean)² | 1.0 | Fraction of observed variance explained |
| **KGE** | 1 - √[(r-1)² + (α-1)² + (β-1)²] | 1.0 | Balances correlation, variability, bias |
| **PBIAS** | 100 × Σ(sim-obs) / Σ(obs) | 0% | Systematic over/under-prediction |

The four algorithms below take different approaches to searching the parameter
space.

---

### 3.2 Monte Carlo (MC)

#### How It Works

Monte Carlo is the simplest possible approach: **pure random sampling**.

```
Repeat N times:
    1. Generate random parameter values (uniform distribution within bounds)
    2. Run the model
    3. Record the objective function value
Return the parameter set with the best objective
```

That's it. No learning, no optimization, no intelligence — just brute force
randomness.

#### Analogy

Imagine looking for the highest point in a mountain range **while blindfolded**.
Monte Carlo drops you at N random locations and you report the altitude at each.
Your "best" is simply the highest point you happened to land on.

#### Strengths

| Strength | Explanation |
|----------|-------------|
| **Dead simple** | No algorithm parameters to tune. No convergence issues. |
| **Embarrassingly parallel** | Every run is independent — perfect for distributing across CPU cores. |
| **No assumptions** | Makes no assumptions about the shape of the objective function. Works for discontinuous, multi-modal, noisy landscapes. |
| **Exploration** | Gives a broad overview of parameter space behavior. |

#### Constraints and Limitations

| Constraint | Explanation |
|-----------|-------------|
| **Extremely slow convergence** | Convergence rate is O(1/√N). To double the precision, you need 4x the samples. To get 10x better, 100x samples. |
| **No learning** | Sample 10,000 is just as "dumb" as sample 1 — the algorithm doesn't learn from previous results to search smarter. |
| **Curse of dimensionality** | With k parameters, the volume of parameter space grows as ranges^k. With 15 parameters, each having 100 possible values, there are 100¹⁵ = 10³⁰ combinations. Random sampling cannot meaningfully explore this. |
| **Poor coverage** | Random samples naturally clump in some areas and leave gaps in others. May completely miss the optimal region. |
| **Not a true optimizer** | Does not converge to the optimum — only finds the best of whatever it randomly sampled. |

#### Application Cases

- **Initial screening:** Run 500-1,000 MC samples to understand the general
  behavior of the objective function landscape before investing in a real
  optimizer.
- **Benchmark:** Use MC as a baseline to verify that a more sophisticated
  algorithm is actually performing better than random search.
- **Uncertainty analysis:** The set of "behavioral" parameter sets (those with
  acceptable performance, e.g., NSE > 0.5) provides a rough picture of
  parameter uncertainty (this is the GLUE methodology — Generalized Likelihood
  Uncertainty Estimation).

#### Typical Sample Sizes for SWAT

| Parameters | Minimum MC runs | Recommended |
|-----------|----------------|-------------|
| 5 | 1,000 | 5,000-10,000 |
| 10 | 5,000 | 20,000-50,000 |
| 20 | 50,000 | 100,000+ |

---

### 3.3 Latin Hypercube Sampling (LHS)

#### How It Works

LHS is a **stratified sampling** strategy that guarantees even coverage of each
parameter's range.

**Step-by-step:**

1. **Divide each parameter range into N equal intervals** (strata).
2. **Sample exactly once from each interval** for each parameter.
3. **Randomly pair** the samples across parameters.

**Visual example** (N = 5 samples, 2 parameters):

```
Pure MC sampling:              Latin Hypercube Sampling:
┌──┬──┬──┬──┬──┐              ┌──┬──┬──┬──┬──┐
│  │  │  │  │  │              │  │  │ ·│  │  │
├──┼──┼──┼──┼──┤              ├──┼──┼──┼──┼──┤
│  │ ·│  │  │  │              │  │  │  │  │ ·│
├──┼──┼──┼──┼──┤              ├──┼──┼──┼──┼──┤
│  │ ·│ ·│  │  │              │ ·│  │  │  │  │
├──┼──┼──┼──┼──┤              ├──┼──┼──┼──┼──┤
│  │  │  │  │  │              │  │  │  │ ·│  │
├──┼──┼──┼──┼──┤              ├──┼──┼──┼──┼──┤
│ ·│  │ ·│  │  │              │  │ ·│  │  │  │
└──┴──┴──┴──┴──┘              └──┴──┴──┴──┴──┘

Notice: MC has gaps and         LHS: every row and column
clusters. Bottom-right is       has exactly one sample.
completely empty.               Full marginal coverage.
```

#### The Key Advantage Over MC

LHS guarantees that the **marginal distribution** of each parameter is
perfectly sampled. Every part of CN2's range, every part of ESCO's range, etc.,
is represented. MC does not guarantee this — by chance, it might over-sample
one region and under-sample another.

#### Strengths

| Strength | Explanation |
|----------|-------------|
| **Better coverage than MC** | With the same N, LHS explores the parameter space more evenly. Variance of estimates is lower. |
| **Fewer samples needed** | For the same precision, LHS typically needs 20-50% fewer samples than MC. |
| **Fully parallel** | Like MC, all samples are independent. |
| **Good for screening** | Excellent for identifying sensitive parameters and understanding objective function landscape. |

#### Constraints and Limitations

| Constraint | Explanation |
|-----------|-------------|
| **Only marginal coverage guaranteed** | LHS ensures each parameter's range is fully covered, but the *joint* coverage (parameter combinations) depends on the random pairing. Corners of the multi-dimensional space can still be missed. |
| **No optimization** | Like MC, LHS is purely a sampling strategy. It does not learn or converge — it just generates a better-distributed set of samples. |
| **Fixed sample size** | You must choose N upfront. You cannot "add more samples" later because the stratification of the existing samples would be disrupted. |
| **Random pairing** | The random pairing step can create correlations between parameters. Improved variants (e.g., maximinLHS, optimumLHS) try to maximize the minimum distance between points. |

#### Application Cases

- **Sensitivity analysis:** The default sampling strategy for many SA methods
  (including the approximate Sobol method in SWAT-DG).
- **Parameter screening:** Run 500-2,000 LHS samples to identify which
  parameters affect the objective, then switch to SCE-UA for actual optimization.
- **Uncertainty analysis:** Better than MC for GLUE-type analysis because the
  parameter space is more evenly sampled.

#### MC vs. LHS: The Key Difference

| Criterion | MC | LHS |
|-----------|-----|-----|
| Sampling strategy | Pure random | Stratified random |
| Coverage guarantee | None | Marginal (per-parameter) |
| Samples for same precision | N | ~0.5N to 0.8N |
| Can add samples later? | Yes | No (must restart) |
| Are samples correlated? | No | Possible (from pairing) |

---

### 3.4 SCE-UA (Shuffled Complex Evolution - University of Arizona)

#### How It Works

SCE-UA is a **global optimization algorithm** specifically designed for
calibrating hydrological models. It combines ideas from:
- **Genetic algorithms** (population-based search)
- **Simplex method** (Nelder-Mead local search)
- **Competitive evolution** (survival of the fittest)
- **Shuffling** (information sharing between groups)

**Step-by-step:**

1. **Initialize:** Generate a population of random parameter sets (points) in
   the parameter space. Evaluate the objective function for each.

2. **Partition into complexes.** Divide the population into `ngs` groups
   (complexes), each containing `npg` points. Points are assigned to complexes
   by rank — the best point goes to complex 1, second-best to complex 2, etc.,
   cycling through.

3. **Evolve each complex independently** using the **Competitive Complex
   Evolution (CCE)** algorithm:
   - Select a sub-complex of `npg` points (weighted toward better points)
   - Apply a **simplex reflection/contraction** step (like Nelder-Mead) to
     generate a new trial point
   - If the trial point is better, it replaces the worst point
   - If not, try a contraction toward the best point
   - If that also fails, replace with a random point
   - Repeat for several iterations

4. **Shuffle.** Recombine all complexes back into one population, re-sort by
   objective value, and re-partition into new complexes. This shares information
   between complexes — good parameter combinations discovered in one complex
   spread to others.

5. **Repeat** steps 3-4 until convergence.

#### Analogy

Imagine N search parties looking for treasure on an island. Each party
(complex) explores its own area independently. Periodically, all parties meet
at camp (shuffling), share what they found, and form new parties mixing members
who found promising areas. Over time, all parties converge on the richest
treasure site.

#### Key Algorithm Parameters

| Parameter | Symbol | Default | Meaning |
|-----------|--------|---------|---------|
| Number of complexes | ngs | k + 1 | More complexes = better global search but slower |
| Points per complex | npg | 2k + 1 | Larger = more thorough local search |
| Points per sub-complex | nps | k + 1 | Used for the simplex evolution step |
| Max iterations | maxn | 10,000 | Maximum function evaluations |

where k = number of parameters.

#### Strengths

| Strength | Explanation |
|----------|-------------|
| **Global optimizer** | Designed to escape local optima through shuffling and multiple complexes. |
| **Robust** | The "gold standard" for hydrological model calibration since the 1990s. Extensive testing across thousands of catchments. |
| **Self-adaptive** | The complexes naturally contract toward good regions while maintaining diversity through shuffling. |
| **Well-tested** | Used in SWAT-CUP, PEST, SPOTPY, and virtually every hydrological calibration tool. |
| **Efficient** | Typically finds near-optimal solutions in 5,000-25,000 evaluations for 10-15 parameters. |

#### Constraints and Limitations

| Constraint | Explanation |
|-----------|-------------|
| **Single-objective only** | SCE-UA optimizes ONE objective function. Cannot natively handle multi-objective calibration (e.g., simultaneously optimizing NSE and PBIAS). Use NSGA-II or MOSCEM for multi-objective. |
| **No uncertainty quantification** | Returns a single "best" parameter set. Does not provide parameter distributions or confidence intervals. You don't know *how uncertain* the best parameters are. |
| **Scales poorly with dimensions** | Performance degrades with many parameters (>20-30). The complexes need to be large enough to span the high-dimensional space, which requires many points. |
| **Limited parallelism** | The CCE step within each complex is sequential. Only `ngs` complexes can be evaluated in parallel. With ngs = 10 and 8 cores, 2 cores sit idle. |
| **Sensitive to ngs** | Too few complexes → trapped in local optimum. Too many → slow convergence, wasted evaluations. The default (k+1) usually works but isn't always optimal. |
| **Convergence to local optimum** | While much better than simple local optimizers, SCE-UA can still converge to a local optimum in very complex, multi-modal landscapes, especially with too few complexes. |

#### Application Cases

- **Standard SWAT calibration** — The recommended default for most users.
- **Single-gauge streamflow** — SCE-UA excels at optimizing NSE or KGE against
  one observation station.
- **Operational calibration** — When you need a "best" parameter set for
  forecasting (not uncertainty bounds).

#### Typical Configuration for SWAT

```
Parameters: 8-15 (after SA screening)
ngs: 10-15 (or n_params + 1)
Max evaluations: 10,000-25,000
Expected runtime: 10,000 × 60s = ~7 days (serial)
                  10,000 × 60s / 10 cores ≈ 17 hours (parallel)
```

---

### 3.5 DREAM (DiffeRential Evolution Adaptive Metropolis)

#### How It Works

DREAM is fundamentally different from SCE-UA. Instead of finding a single
"best" parameter set, DREAM **maps out the entire probability distribution** of
good parameter sets. It is a **Bayesian method**.

**The Bayesian framework:**

```
P(θ|data) ∝ P(data|θ) × P(θ)
posterior  ∝ likelihood × prior
```

- **Prior P(θ):** Your initial belief about parameter ranges (usually uniform
  within bounds).
- **Likelihood P(data|θ):** How well the model with parameters θ reproduces the
  observed data.
- **Posterior P(θ|data):** The updated belief about parameters after seeing the
  data. This is what DREAM approximates.

**Step-by-step:**

1. **Initialize multiple Markov chains** (typically 4-10) at random starting
   points in parameter space.

2. **At each step, propose a new point** for each chain using **differential
   evolution**: pick two *other* chains randomly, compute their difference
   vector, scale it, and add it to the current chain position.
   ```
   θ_proposed = θ_current + γ × (θ_chain_a - θ_chain_b) + noise
   ```
   This is the key innovation — the proposal automatically adapts to the shape
   and scale of the target distribution.

3. **Accept/reject** the proposed point using the Metropolis criterion:
   - If the proposed point has higher likelihood: **always accept**
   - If lower: **accept with probability** = likelihood(proposed) / likelihood(current)

   This allows occasional "uphill" moves that can escape local optima.

4. **Adapt** the scaling and crossover parameters during the burn-in phase.

5. **Diagnose convergence** using the Gelman-Rubin R-hat statistic: if all
   chains are sampling from the same distribution, R-hat ≈ 1.0.

6. **After convergence**, the combined chain samples approximate the posterior
   distribution.

#### Analogy

SCE-UA is like sending search parties to find the single highest peak. DREAM is
like sending surveyors to **map the entire mountain range** — they report not
just where the peaks are, but how wide, how steep, and whether there are
multiple peaks of similar height.

#### What DREAM Gives You That SCE-UA Doesn't

1. **Parameter uncertainty:** Instead of CN2 = 72.5, DREAM says CN2 = 72.5
   ± 3.2 (95% confidence interval). This tells you how well-constrained each
   parameter is by the data.

2. **Parameter correlations:** DREAM reveals if CN2 and ESCO are correlated
   (i.e., multiple combinations produce equally good fits). This is called
   **equifinality** — a major issue in hydrological modeling.

3. **Prediction uncertainty:** By running the model with many posterior parameter
   sets, you get uncertainty bounds on predictions (e.g., "there's a 95% chance
   flow will be between 50-80 m³/s").

4. **Multi-modal detection:** If two very different parameter regions produce
   equally good fits, DREAM will find both modes.

#### Key Algorithm Parameters

| Parameter | Typical Value | Meaning |
|-----------|---------------|---------|
| nChains | 4-10 | Number of parallel Markov chains |
| nCR | 3 | Number of crossover values |
| burn-in | First 50% of samples | Discarded to allow chains to converge |
| convergence (R-hat) | < 1.2 | Gelman-Rubin diagnostic |

#### Strengths

| Strength | Explanation |
|----------|-------------|
| **Uncertainty quantification** | The primary advantage — provides full posterior distributions. |
| **Multi-modal** | Can identify multiple distinct parameter solutions (equifinality). |
| **Adaptive** | The differential evolution proposal automatically scales to the problem. |
| **Rigorous** | Produces statistically valid posterior distributions (after convergence). |
| **Correlation structure** | Reveals parameter interdependencies. |

#### Constraints and Limitations

| Constraint | Explanation |
|-----------|-------------|
| **Computationally expensive** | Requires 50,000-200,000+ evaluations for convergence with 10+ parameters. Much more than SCE-UA. |
| **Long burn-in** | The first 25-50% of samples are typically discarded as "burn-in" (the chains haven't converged yet). This means half your computation is "wasted." |
| **Convergence diagnosis** | Checking whether chains have truly converged is not trivial. R-hat < 1.2 is necessary but not sufficient. |
| **Likelihood function choice** | Results are sensitive to the choice of likelihood function. A Gaussian likelihood assumes normally distributed, independent residuals — which is rarely true for streamflow. |
| **Not an optimizer** | DREAM's "best" parameter set is typically slightly worse than SCE-UA's best, because DREAM is exploring the distribution rather than hill-climbing. |
| **Chain initialization** | Poor starting points can dramatically slow convergence. |
| **High-dimensional difficulty** | Like all MCMC methods, DREAM struggles in very high dimensions (>30 parameters) because the acceptance rate drops. |

#### Application Cases

- **Uncertainty analysis** — The primary use case. When you need to report
  confidence intervals on model predictions.
- **Research publications** — When reviewers expect rigorous uncertainty
  quantification.
- **Equifinality studies** — Understanding whether the model is over-parameterized
  (many different parameter sets give similar performance).
- **Flood frequency** — When prediction uncertainty directly affects design
  decisions.

#### Typical Configuration for SWAT

```
Parameters: 5-15 (fewer is much better for DREAM)
nChains: 4-8
Total evaluations: 50,000-200,000
Burn-in: first 50%
Usable posterior samples: 25,000-100,000
Expected runtime: 100,000 × 60s / 8 cores ≈ 9 days
```

---

### 3.6 Calibration Algorithms: Side-by-Side Comparison

| Criterion | Monte Carlo | Latin Hypercube | SCE-UA | DREAM |
|-----------|-------------|-----------------|--------|-------|
| **Type** | Random sampling | Stratified sampling | Global optimizer | Bayesian MCMC |
| **Goal** | Explore space | Explore space efficiently | Find best parameters | Map parameter distribution |
| **Intelligence** | None | None (smarter sampling) | Evolves toward optimum | Adapts proposals |
| **Output** | Set of random runs | Set of stratified runs | Single best θ | Posterior distribution |
| **Uncertainty?** | Crude (GLUE) | Crude (GLUE) | No | Yes (rigorous) |
| **Typical evaluations** | 5,000-50,000 | 1,000-10,000 | 5,000-25,000 | 50,000-200,000 |
| **Parallelism** | Perfect (100%) | Perfect (100%) | Limited (ngs cores) | Limited (nChains) |
| **# Parameters sweet spot** | 5-15 | 5-20 | 8-25 | 5-15 |
| **Finds global optimum?** | By luck only | By luck only | Very likely | Likely (as mode) |
| **Equifinality detection?** | Possible | Possible | No | Yes |
| **Implementation effort** | Trivial | Trivial | Moderate | Complex |
| **SPOTPY name** | `mc` | `lhs` | `sceua` | `dream` |

---

## 4. Part III: SPOTPY Implementation Notes

These notes are specific to the **SPOTPY 1.6.6** framework used by the
SWAT-DG project.

### 4.1 FAST: Two Implementations in SPOTPY

SPOTPY actually ships with **two** separate FAST implementations:

| Implementation | File | Variant | Cost | Computes |
|---|---|---|---|---|
| `spotpy.algorithms.fast` | `fast.py` | eFAST (Saltelli 1999), ported from SALib | k × N per param | S1 + ST |
| `spotpy.algorithms.efast` | `efast.py` | Original FAST (Cukier 1975 / McRae 1982), ported from R | Pre-computed optimal N (much less) | Partial variances + temporal sensitivity |

The **`fast`** variant (used by SWAT-DG's `calibrator.sensitivity_analysis()`)
runs k separate loops where the parameter of interest gets the highest frequency.
It requires **N_per_param x k** total evaluations (e.g., 65 x 10 = 650 minimum).

The **`efast`** variant uses hard-coded incommensurate frequency tables from
Cukier (1975) and McRae (1982), requiring significantly **fewer total runs**:

| # Parameters | fast variant (min) | efast variant (min, Cukier) |
|---|---|---|
| 5 | 325 (65 x 5) | 71 |
| 10 | 650 (65 x 10) | 403 |
| 15 | 975 (65 x 15) | 1,019 |
| 20 | 1,300 (65 x 20) | 2,087 |

The `efast` variant also supports **temporal sensitivity** — computing
sensitivity indices at each time step separately — useful for understanding
when different parameters dominate (e.g., CN2 during storms vs. ALPHA_BF
during recession).

### 4.2 Sobol: No Native SPOTPY Implementation

SPOTPY does **not** implement the Saltelli sampling scheme for Sobol analysis.
The SWAT-DG project's `method="sobol"` option uses an **approximate
workaround**: it runs LHS sampling, then bins each parameter into 10 intervals
and computes `Var(bin_means) / Var(total)` as a crude first-order index. A
warning is emitted in the code. For rigorous Sobol analysis, use the **SALib**
Python library directly.

### 4.3 MC: Unique Parameter Type Support

`spotpy.algorithms.mc` is the **only** SPOTPY algorithm that accepts
`parameter.List` types (pre-defined parameter sequences). All other algorithms
set `_unaccepted_parameter_types = (parameter.List,)`.

### 4.4 LHS: Uniform Stratification Only

SPOTPY's LHS stratifies using `minbound` and `maxbound` uniformly, **not** in
CDF (probability) space. Even if a parameter is defined as `spotpy.parameter.Normal`,
the LHS will stratify uniformly between bounds, not at equal probability intervals
of the normal distribution. SPOTPY also does **not** implement Iman & Conover
(1982) correlation control — the random column shuffling can introduce spurious
rank correlations, especially for small N.

### 4.5 DREAM: Minimum Chain Count

DREAM requires `nChains >= 2 * delta + 1` where `delta` (default 3) is the
number of chain pairs used for differential evolution proposals. With the
default `delta = 3`, this means **at least 7 chains**.

> **Note for SWAT-DG:** The project currently passes `nChains=4` in
> `calibrator.py` line 527. With the default `delta=3`, DREAM needs at least
> 7 chains — using 4 may cause SPOTPY to print an error and return None.
> Either increase to `nChains=7+` or decrease `delta` to 1 (minimum 3 chains).

### 4.6 Parallel Mode Summary

| Algorithm | Can use `umpc` (unordered)? | Recommended mode | Why |
|---|---|---|---|
| FAST | **No** — must use `mpc` | `mpc` (ordered) | FFT requires results in exact sampling-curve order |
| MC | Yes | `umpc` (unordered) | All samples independent; yields results as-ready |
| LHS | Yes | `umpc` (unordered) | All samples independent |
| SCE-UA | Limited | `mpc` (ordered) | Parallel over `ngs` complexes per evolution loop |
| DREAM | Limited | `mpc` (ordered) | Parallel over `nChains` per iteration |

---

## 5. Part IV: Additional Algorithms — SUFI-2 & NSGA-II

### 5.1 SUFI-2 (Sequential Uncertainty Fitting)

#### How It Works

SUFI-2 is the most widely used SWAT calibration method worldwide, implemented
in the **SWAT-CUP** software. It is neither a pure optimizer (like SCE-UA) nor
a Bayesian sampler (like DREAM). It is an **iterative uncertainty analysis
procedure** that alternates between Latin Hypercube sampling and parameter
range narrowing.

**Step-by-step (each "iteration" = one macro-cycle):**

1. **Define initial parameter ranges** — physically meaningful upper/lower
   bounds for each parameter.

2. **Latin Hypercube Sampling** — Draw 500-2,000 parameter sets using LHS
   within the current ranges.

3. **Run SWAT** for every parameter set. Compute the objective function
   (NSE, KGE, etc.) for each run.

4. **Build the 95PPU band** — From the simulation ensemble, compute the 2.5th
   and 97.5th percentile of outputs at each time step (after discarding the
   worst 5% of simulations). This envelope is the **95% Prediction Uncertainty**.

5. **Evaluate P-factor and R-factor:**
   - **P-factor** = fraction of observed data that falls within the 95PPU band.
     Target: > 0.70.
   - **R-factor** = average 95PPU band width / standard deviation of observed
     data. Target: < 1.5.

6. **Narrow parameter ranges** using a sensitivity/Jacobian matrix approach:
   - Compute regression of parameter values against objective function
     (effectively a Jacobian matrix J).
   - Compute covariance matrix C = (J^T J)^-1 * s^2.
   - Derive 95% confidence intervals for each parameter from C.
   - New ranges = confidence intervals centered on the best parameter values,
     clipped to physical bounds.
   - Sensitive parameters (narrow confidence intervals) get their ranges
     narrowed aggressively; insensitive ones retain wider ranges.

7. **Repeat** with narrowed ranges for 3-5 iterations.

#### Analogy

Think of SUFI-2 as progressively zooming in on a map. Each iteration you
photograph a wider area (LHS sampling), identify the most interesting
region (sensitivity analysis), then zoom in on that region for the next
photograph. After 3-5 zoom levels, you have a detailed picture of the
optimal area.

#### Strengths

| Strength | Explanation |
|----------|-------------|
| **Most efficient** | 1,500-10,000 total runs (vs 50,000+ for DREAM) |
| **Built-in uncertainty** | Provides 95PPU bands, P-factor, R-factor |
| **Integrated sensitivity** | Global sensitivity (t-stat/p-value) computed per iteration |
| **Widely validated** | Thousands of SWAT publications use SUFI-2 |
| **Intuitive stopping** | P-factor > 0.70 and R-factor < 1.5 are easy to understand |

#### Constraints

| Constraint | Explanation |
|-----------|-------------|
| **Semi-automated** | User must review results between iterations and approve range narrowing. Not fully hands-off. |
| **No formal convergence** | Unlike DREAM's R-hat diagnostic, there is no mathematical proof of convergence. |
| **Range narrowing can be subjective** | Different users may modify the suggested ranges differently, reducing reproducibility. |
| **Sensitivity to initial ranges** | If initial ranges miss the true optimal region, SUFI-2 may converge to a suboptimal solution. |
| **Not truly Bayesian** | The 95PPU is an empirical Monte Carlo envelope, not a formal Bayesian credible interval. |
| **SWAT-CUP dependency** | The original is closed-source, Windows-only. No official open-source Python implementation exists. |

#### Typical Configuration

```
Iterations: 3-5 macro-cycles
Samples per iteration: 500-2,000 (rule of thumb: 50-100 per parameter)
Total evaluations: 1,500-10,000
Stopping: P-factor > 0.70, R-factor < 1.5
```

#### Comparison: SUFI-2 vs SCE-UA vs DREAM

| Criterion | SUFI-2 | SCE-UA | DREAM |
|-----------|--------|--------|-------|
| Total evaluations | 1,500-10,000 | 5,000-25,000 | 50,000-200,000 |
| Uncertainty output | 95PPU (empirical) | None | Posterior distribution (Bayesian) |
| Automation level | Semi-automated | Fully automated | Fully automated |
| Sensitivity analysis | Built-in (regression) | None | None |
| User intervention | Required between iterations | Set-and-run | Set-and-run |
| SPOTPY support | **Not built-in** | Native | Native |

---

### 5.2 NSGA-II (Multi-Objective Genetic Algorithm)

#### How It Works

NSGA-II finds the **Pareto front** — the set of all trade-off solutions where
no objective can be improved without worsening another. Instead of returning
one "best" answer, it returns an entire curve of equally optimal compromises.

**Step-by-step:**

1. **Initialize** a random population of N parameter sets.

2. **Evaluate** all objectives (e.g., NSE, PBIAS, KGE) for each set.

3. **For each generation:**
   a. Create N offspring via tournament selection, crossover, and mutation.
   b. Combine parents + offspring (2N individuals).
   c. **Non-dominated sort**: Rank solutions into Pareto fronts (F1, F2, ...).
      Solutions on F1 are not dominated by anything. F2 is dominated only by F1.
   d. **Crowding distance**: Within each front, measure how isolated each
      solution is (to preserve diversity along the front).
   e. Select the best N individuals for the next generation: all of F1, then
      F2, etc. If a front doesn't fit entirely, pick the most spread-out
      members by crowding distance.

4. **After G generations**, the final F1 (Pareto front) is the output.

#### Why Multi-Objective Matters for SWAT

Single-objective calibration has a fundamental blindspot: **NSE is dominated
by peak flows** (due to squared errors). Optimizing NSE alone often produces:

- Excellent peak reproduction but large volume bias (|PBIAS| > 20%)
- Poor low-flow representation
- Physically unrealistic parameter combinations

Multi-objective calibration simultaneously optimizes multiple criteria:

| Objective pair | What it reveals |
|---|---|
| NSE vs PBIAS | Accuracy vs water balance tradeoff |
| NSE vs log-NSE | Peak flow vs low-flow tradeoff |
| KGE vs FDC slope error | Overall fit vs flow regime realism |
| Flow NSE vs Sediment NSE | Multi-variable tradeoff |

The Pareto front shows **exactly what you give up** when favoring one metric
over another, enabling physically informed decision-making.

#### Key Algorithm Parameters

| Parameter | Typical | Notes |
|-----------|---------|-------|
| Population size (n_pop) | 100 | At least 4x number of parameters |
| Generations | 100-200 | Total evals = n_pop x generations |
| Number of objectives (n_obj) | 2-3 | NSGA-II degrades beyond 3-4 objectives |
| Crossover probability | 0.9 | Standard default |
| Mutation probability | 0.25 | Or 1/n_params for larger sets |

#### Strengths

| Strength | Explanation |
|----------|-------------|
| **Full Pareto front** | See all trade-off solutions in one run |
| **No weight selection needed** | Preferences applied post-hoc, not before optimization |
| **Diversity preservation** | Crowding distance prevents clustering on the front |
| **Non-convex fronts** | Finds solutions that weighted-sum methods miss |
| **In SPOTPY already** | `spotpy.algorithms.nsgaii` exists and is functional |

#### Constraints

| Constraint | Explanation |
|-----------|-------------|
| **Computationally expensive** | 10,000+ evaluations typical (100 pop x 100 gen) |
| **No single "best" answer** | User must choose from the Pareto front |
| **Degrades with many objectives** | > 3-4 objectives: crowding distance becomes ineffective. Need NSGA-III for "many-objective" problems. |
| **Not Bayesian** | No posterior distributions or formal uncertainty bounds |
| **Requires multi-objective setup** | `objectivefunction()` must return a list, not a single float |

#### SPOTPY Implementation Status

SPOTPY ships with a **complete NSGA-II** at `spotpy.algorithms.nsgaii`:
- Non-dominated sorting, crowding distance, tournament selection, crossover,
  polynomial mutation — all implemented.
- BUT it requires `objectivefunction()` to return **a list of M float values**
  (one per objective, minimization direction).

**Current project incompatibility**: The `SWATModelSetup.objectivefunction()`
returns a single `float`. To use NSGA-II, a `MultiObjectiveSetup` wrapper is
needed that returns `[1-NSE, abs(PBIAS)]` (converted to minimization).

---

### 5.3 Should We Add Them?

#### SUFI-2: Recommendation — **YES, implement**

| Factor | Assessment |
|--------|-----------|
| **Value added** | Fills the gap between "fast but no uncertainty" (SCE-UA) and "rigorous but slow" (DREAM). Most SWAT users expect SUFI-2. |
| **Implementation effort** | **Moderate**. Build as an iterative wrapper around SPOTPY's LHS: ~300-500 lines for the core loop, P/R-factor, and Jacobian-based range narrowing. |
| **SPOTPY compatibility** | Uses `spotpy.algorithms.lhs` as the sampling engine — fully compatible. |
| **What's needed** | (1) Iterative loop with parameter range updating, (2) 95PPU calculation requiring cached simulation time series, (3) P-factor/R-factor computation, (4) Jacobian-based range narrowing logic, (5) Global sensitivity via regression (t-stat/p-value). |
| **Risk** | The exact SWAT-CUP range-narrowing formula is proprietary. A Jacobian/covariance-based approximation (published in Abbaspour 2007, 2015) can be implemented but may differ in details from the original. |

#### NSGA-II: Recommendation — **YES, add as an option**

| Factor | Assessment |
|--------|-----------|
| **Value added** | Enables multi-variable calibration (flow + sediment + nutrients) and reveals objective trade-offs. Essential for multi-site calibration. |
| **Implementation effort** | **Low-moderate**. SPOTPY already has the algorithm. Need: (1) `MultiObjectiveSetup` wrapper class, (2) Handle different `sample()` signature in `Calibrator`, (3) `ParetoResult` container, (4) Direction conversion (maximize→minimize). |
| **SPOTPY compatibility** | Native — `spotpy.algorithms.nsgaii` is a complete implementation. |
| **What's needed** | (1) Multi-objective setup class (~100 lines), (2) Calibrator integration (~50 lines), (3) Pareto front result class + visualization (~200 lines). |
| **Risk** | Low. SPOTPY's NSGA-II works with the standard `_algorithm` interface. Only the `objectivefunction()` return type differs. |

#### Priority Order

```
1. SUFI-2 (high priority — most requested by SWAT community)
2. NSGA-II (medium priority — important for multi-variable calibration)
3. Diagnostic-guided calibration (high priority — see next section)
```

---

## 6. Part V: Diagnostic-Guided Calibration

### 6.1 The Core Idea

Traditional calibration algorithms (SCE-UA, DREAM, MC) are **blind** — they
treat the model as a black box and explore parameter space without
understanding what the parameters physically control. An expert hydrologist,
in contrast, would look at the hydrograph and immediately know:

> "The peaks are too high and the baseflow is too low. I need to decrease CN2
> (less surface runoff) and decrease GWQMN (allow groundwater to discharge
> sooner)."

**Diagnostic-guided calibration** automates this expert reasoning. It:

1. **Decomposes** the model-observation discrepancy into interpretable
   components (peaks, baseflow, recession, volume, timing).
2. **Maps** each component to the SWAT parameters that control it.
3. **Estimates** the direction and approximate magnitude of needed adjustments.
4. **Pre-conditions** the parameter space before handing off to an optimizer.

**Benefits:**
- Reduces calibration iterations by 40-60% (narrowed search space)
- Ensures physically meaningful parameter combinations
- Provides interpretable diagnostic reports
- Catches model structural problems early

---

### 6.2 Hydrograph Components and Their SWAT Parameters

Each part of the hydrograph is controlled by different physical processes and
therefore different parameters:

#### Master Parameter-Process Mapping Table

| Hydrograph Feature | If Error Is... | Primary Parameters | Direction | Secondary Parameters |
|---|---|---|---|---|
| **Peak magnitude** | Too high | CN2 | Decrease | SOL_K (increase), SOL_AWC (increase), OV_N (increase) |
| **Peak magnitude** | Too low | CN2 | Increase | SOL_K (decrease), SURLAG (decrease) |
| **Peak timing** | Too early | SURLAG | Decrease | CH_N2 (increase), OV_N (increase) |
| **Peak timing** | Too late | SURLAG | Increase | CH_N2 (decrease), OV_N (decrease) |
| **Baseflow level** | Too low | GWQMN | Decrease | RCHRG_DP (decrease), GW_DELAY (decrease), GW_REVAP (decrease) |
| **Baseflow level** | Too high | GWQMN | Increase | RCHRG_DP (increase), GW_REVAP (increase) |
| **Recession rate** | Too fast | ALPHA_BF | Decrease | GW_DELAY (increase), SOL_AWC (increase) |
| **Recession rate** | Too slow | ALPHA_BF | Increase | GW_DELAY (decrease) |
| **Total volume** | Too high (+PBIAS) | ESCO | Decrease | CN2 (decrease), EPCO (increase), CANMX (increase) |
| **Total volume** | Too low (-PBIAS) | ESCO | Increase | CN2 (increase), EPCO (decrease) |
| **Rising limb** | Too steep | CN2, SURLAG | Decrease, Increase | OV_N (increase) |
| **Falling limb** | Too steep | ALPHA_BF | Decrease | GW_DELAY (increase), SURLAG (decrease) |
| **Flashiness** | Too flashy | CN2 | Decrease | GWQMN (decrease), SOL_AWC (increase) |
| **Flashiness** | Too damped | CN2 | Increase | GWQMN (increase) |
| **Summer flow** | Overestimated | ESCO | Decrease | EPCO (decrease), GW_REVAP (increase) |
| **Winter flow** | Underestimated | SFTMP | Increase | SMTMP (decrease), SMFMX (increase) |

#### Physical Logic

The mapping is grounded in SWAT's water balance:

```
Precipitation = Surface Runoff + Infiltration
Infiltration  = Soil Storage + Lateral Flow + Percolation
Percolation   = Shallow Aquifer Recharge (after GW_DELAY days)
Shallow Aq.   = Baseflow (if depth > GWQMN) + Deep Perc. (RCHRG_DP) + Revap (GW_REVAP)
Baseflow      = decays at rate ALPHA_BF
```

- **CN2** controls the Precipitation → Surface Runoff split
- **ESCO** controls how much soil moisture is available for ET (volume balance)
- **ALPHA_BF** is literally the baseflow recession constant
- **GWQMN** is the threshold depth for baseflow to begin
- **SURLAG** controls how quickly surface runoff reaches the channel

---

### 6.3 Key Methodologies

#### A. KGE Decomposition (Gupta et al. 2009)

KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2), where:

| Component | Meaning | If value deviates... | Fix with... |
|---|---|---|---|
| **r** (correlation) | Timing and shape match | Low r → timing errors | SURLAG, CH_N2, OV_N |
| **alpha** (variability) | sigma_sim / sigma_obs | alpha > 1 → too flashy | Decrease CN2, decrease GWQMN |
| | | alpha < 1 → too smooth | Increase CN2 |
| **beta** (bias) | mean_sim / mean_obs | beta > 1 → volume too high | Decrease ESCO |
| | | beta < 1 → volume too low | Increase ESCO, increase CN2 |

The power of KGE decomposition is that it immediately tells you **whether
your problem is timing, variability, or volume** — three fundamentally
different issues requiring different parameters.

#### B. Flow Duration Curve Decomposition (Yilmaz et al. 2008)

The FDC (plot of flow magnitude vs exceedance probability) is divided into
three diagnostic segments:

```
Exceedance 0%──────2%───────20%──────────70%──────────100%
             │ High-flow │  Midsegment  │  Low-flow   │
             │   (FHV)   │    (FMS)     │   (FLV)     │
             │           │              │             │
             │ CN2,      │ ESCO,        │ RCHRG_DP,   │
             │ SURLAG    │ SOL_AWC,     │ GWQMN,      │
             │           │ GW_DELAY     │ GW_REVAP    │
```

- **FHV** (high-flow volume bias): Overestimated peaks? → Decrease CN2
- **FMS** (midsegment slope bias): Too flashy? → Decrease ESCO, increase SOL_AWC
- **FLV** (low-flow volume bias): Baseflow too low? → Decrease RCHRG_DP

Each segment maps to a **distinct parameter group**, making diagnosis
unambiguous.

#### C. Baseflow Separation (Eckhardt 2005)

The Eckhardt recursive digital filter separates baseflow from total flow:

```
b(t) = ((1-BFI_max) * alpha * b(t-1) + (1-alpha) * BFI_max * Q(t))
       / (1 - alpha * BFI_max)
b(t) = min(b(t), Q(t))
```

**BFI** (Baseflow Index) = sum(baseflow) / sum(total_flow)

Comparing BFI_obs vs BFI_sim immediately tells you whether the model's
surface/subsurface flow partition is correct — the single most important
diagnostic for SWAT.

#### D. Recession Analysis

ALPHA_BF in SWAT **directly corresponds** to the baseflow recession constant.
This is one of the most directly diagnosable relationships:

```
Observed recession: fit log(Q) = log(Q0) - alpha_obs * t
If alpha_sim ≠ alpha_obs → set ALPHA_BF ≈ alpha_obs
```

This single adjustment often dramatically improves baseflow simulation.

---

### 6.4 Diagnostic-Guided Calibration Algorithm

The following algorithm uses expert rules to pre-condition the parameter space
before handing off to SCE-UA, reducing total iterations by 40-60%.

```
PHASE 0: BASELINE (1 SWAT run)
    Run model with default parameters
    Compute KGE, PBIAS, BFI, peak analysis, recession analysis, FDC metrics
    If KGE >= 0.75: STOP (already good)

PHASE 1: VOLUME CORRECTION (1-3 runs)
    Goal: |PBIAS| < 10%
    If PBIAS > +10%: decrease ESCO proportionally
    If PBIAS < -10%: increase ESCO proportionally
    If |PBIAS| > 20%: also adjust CN2
    Verify adjustment, iterate if needed

PHASE 2: BASEFLOW PARTITION (2-4 runs)
    Goal: BFI_ratio within [0.85, 1.15]
    If BFI_sim/BFI_obs < 0.85: decrease GWQMN, decrease RCHRG_DP
    If BFI_sim/BFI_obs > 1.15: increase GWQMN, increase RCHRG_DP
    Simultaneously fix recession: set ALPHA_BF ≈ observed recession constant
    Verify and iterate

PHASE 3: PEAK FLOW CORRECTION (2-3 runs)
    Goal: peak_ratio within [0.85, 1.15], |timing_error| < 1 day
    If peaks too high: decrease CN2 (carefully — don't undo volume fix)
    If peaks too early/late: adjust SURLAG
    Verify and iterate

PHASE 4: RANGE NARROWING
    For each adjusted parameter:
        narrowed_range = current_value ± 30% of original range
    Generate diagnostic report (before/after comparison)

PHASE 5: SCE-UA FINE-TUNING (3,000-10,000 runs)
    Start SCE-UA with diagnostic estimates as initial guess
    Use narrowed ranges from Phase 4
    Use multi-component objective:
        0.40 * KGE + 0.15 * (1-|FHV|/100) + 0.15 * (1-|FLV|/100)
        + 0.15 * (1-|FMS_bias|/100) + 0.15 * (1-BFI_error)
```

**Total SWAT runs**: 5-12 diagnostic + 3,000-10,000 optimization.
Compare to: 10,000-25,000 runs for SCE-UA without pre-conditioning.

---

### 6.5 What Already Exists in SWAT-DG

The project already has **substantial diagnostic infrastructure** in
`diagnostics.py` (939 lines):

| Component | Status | Implementation |
|---|---|---|
| Baseflow separation (Eckhardt) | **Complete** | `eckhardt_baseflow_filter()` |
| Baseflow separation (Lyne-Hollick) | **Complete** | `lyne_hollick_filter()` |
| BFI calculation | **Complete** | `calculate_bfi()` |
| Peak detection | **Complete** | `detect_peaks()` via scipy |
| Peak matching (obs vs sim) | **Complete** | `compare_peaks()` — magnitude ratio, timing error |
| Volume balance analysis | **Complete** | `volume_balance()` — total, high/low flow, seasonal, annual PBIAS |
| Recession analysis | **Complete** | `_estimate_recession_rate()` |
| Diagnostic rule engine | **Complete** | 14 rules with confidence levels |
| Parameter recommendations | **Complete** | `DiagnosticRule` → `ParameterRecommendation` |
| Conflict resolution | **Complete** | Higher confidence wins |
| `diagnose()` orchestrator | **Complete** | Runs all analyses, aggregates recommendations |
| Integration with sequential calibration | **Complete** | Used after each calibration step |

**Parameter-process groups** also exist in `parameters.py`:
- 41 parameters organized into groups (hydrology, groundwater, soil, snow, etc.)
- `get_streamflow_parameters()`, `get_sediment_parameters()`, etc.
- Sensitivity rankings built in

---

### 6.6 Gaps and Implementation Roadmap

Despite the strong diagnostic foundation, the following gaps remain:

| Gap | Priority | Effort | Description |
|---|---|---|---|
| **Diagnostic-guided calibration loop** | **High** | Medium | The algorithm from Section 6.4 — iterative pre-conditioning that runs Phases 0-4 automatically before SCE-UA. Currently `diagnose()` produces recommendations but nothing acts on them automatically. |
| **FDC metrics (FHV, FMS, FLV)** | **High** | Low | Three metrics from Yilmaz (2008). ~50 lines of code. Map to distinct parameter groups. |
| **KGE component analysis** | **High** | Low | Decompose KGE into r, alpha, beta and map each to parameters. ~30 lines. |
| **Magnitude estimation heuristics** | Medium | Medium | Rules for estimating HOW MUCH to adjust (not just direction). Lookup tables + elasticity-based estimation from SA results. |
| **Multi-component objective function** | Medium | Low | Weighted objective combining KGE + FHV + FLV + FMS + BFI. ~40 lines. |
| **Rising/falling limb analysis** | Low | Low | Slope computation for event limbs. ~40 lines. |
| **Flashiness index** | Low | Low | Richards-Baker index. ~10 lines. |

#### Recommended Implementation Order

```
Step 1: Add FDC metrics + KGE decomposition (small, high value)
Step 2: Build the diagnostic-guided calibration loop (Phases 0-4)
Step 3: Add magnitude estimation heuristics
Step 4: Create multi-component objective function
Step 5: Wire into Streamlit UI with before/after diagnostic visualization
```

---

## 7. Part VI: Practical Workflow Recommendations

### Recommended Workflow for SWAT Calibration

The recommended workflow combines traditional optimization with diagnostic-guided
calibration to achieve faster convergence and physically meaningful results.

```
Step 1: Sensitivity Analysis (FAST)
├── Goal: Identify the 5-10 most influential parameters
├── Method: FAST with 100+ samples/parameter
├── Total runs: ~1,000-2,000
└── Output: Parameter ranking by S1 and ST

Step 2: Diagnostic Pre-Conditioning (NEW — Recommended)
├── Goal: Set physically meaningful initial ranges using hydrograph analysis
├── Method: Run model with default parameters, compare to observations
├── Analysis:
│   ├── KGE decomposition → identify bias (β), variability (α), timing (r)
│   ├── Baseflow separation → BFI ratio → constrain GW parameters
│   ├── Peak analysis → magnitude/timing errors → constrain CN2, SURLAG
│   ├── Volume balance → seasonal/annual PBIAS → constrain ESCO, GWQMN
│   └── Recession analysis → recession rate → constrain ALPHA_BF, GW_DELAY
├── Total runs: 1 (just the default run!)
└── Output: Narrowed parameter ranges, targeted parameter groups

Step 3: Initial Screening (LHS)  [Optional]
├── Goal: Understand objective function landscape within narrowed ranges
├── Method: LHS with 500-2,000 samples
├── Total runs: 500-2,000
└── Output: Scatter plots, rough optima location

Step 4: Optimization (SCE-UA or SUFI-2)
├── Goal: Find the best parameter values
├── Method: SCE-UA with diagnostic-narrowed ranges (or SUFI-2 for iterative narrowing)
├── Total runs: 5,000-15,000 (fewer needed with narrowed ranges)
└── Output: Best parameter set, calibrated model

Step 5: Diagnostic Verification (NEW — Recommended)
├── Goal: Verify calibrated model is physically meaningful
├── Method: Re-run diagnostics on calibrated output
├── Check:
│   ├── BFI within expected range for the watershed?
│   ├── Peak timing errors < 1 day?
│   ├── Seasonal volume distribution realistic?
│   └── No compensating errors (e.g., high CN2 + high ESCO)?
├── Total runs: 0 (analysis only)
└── Output: Pass/fail with specific recommendations if issues found

Step 6: Multi-Objective Refinement (NSGA-II)  [If needed]
├── Goal: Explore trade-offs between conflicting objectives
├── Method: NSGA-II optimizing NSE + log-NSE + PBIAS simultaneously
├── Total runs: 5,000-20,000
└── Output: Pareto front of non-dominated solutions

Step 7: Uncertainty Analysis (DREAM)  [If needed]
├── Goal: Quantify parameter and prediction uncertainty
├── Method: DREAM initialized near the SCE-UA/SUFI-2 optimum
├── Total runs: 50,000-200,000
└── Output: Parameter distributions, prediction confidence intervals
```

### Why Diagnostic Pre-Conditioning Matters

Without diagnostics, optimization algorithms treat all errors equally and may
find mathematically "optimal" solutions that are physically unrealistic. For
example:

- **High CN2 + High ESCO**: Produces correct total volume (high runoff offset by
  high ET) but wrong flow partitioning — too much surface runoff, too little
  baseflow
- **Very low ALPHA_BF + High GW_REVAP**: Produces correct baseflow volume but
  wrong recession shape — water is being "manufactured" by groundwater revap
  instead of naturally draining

Diagnostic pre-conditioning catches these issues *before* optimization begins,
leading to:
- **Faster convergence**: 30-50% fewer evaluations needed (narrower ranges)
- **More realistic models**: Parameters stay within physically meaningful bounds
- **Better extrapolation**: Models calibrated with physical constraints perform
  better under climate change or land use scenarios

### Decision Guide: Which Algorithm Should I Use?

| Your situation | Recommended algorithm |
|---|---|
| "I just want a good calibration, fast" | Diagnostics → **SCE-UA** |
| "I need to know which parameters to calibrate" | **FAST** sensitivity analysis |
| "I need uncertainty bounds on my predictions" | **DREAM** |
| "I want a quick look at how the model behaves" | **LHS** (1,000 samples) |
| "I'm writing a research paper" | FAST → Diagnostics → SCE-UA → **DREAM** |
| "I have limited computation time" | Diagnostics → **SCE-UA** (skip DREAM) |
| "I have many parameters (>20)" | FAST to screen → Diagnostics → SCE-UA with top 10 |
| "I want to compare against random search" | **MC** as baseline |
| "I suspect the model has equifinality" | **DREAM** (reveals multi-modal posteriors) |
| "I need to optimize for multiple objectives" | Diagnostics → **NSGA-II** |
| "I want iterative range narrowing (SWAT-CUP style)" | **SUFI-2** |
| "I want physically meaningful parameters" | **Diagnostic-guided** workflow |

### Computation Budget Planning

For a SWAT model running **60 seconds per evaluation** on 8 CPU cores:

| Step | Method | Evaluations | Serial Time | Parallel (8 cores) |
|------|--------|-------------|-------------|---------------------|
| SA | FAST (10 params) | 1,000 | 17 hours | ~2 hours |
| Diagnostics | Default run + analysis | 1 | 1 minute | 1 minute |
| Screening | LHS | 1,000 | 17 hours | ~2 hours |
| Calibration | SCE-UA | 10,000 | 7 days | ~1 day* |
| Calibration | SUFI-2 (3 iterations) | 1,500 | 25 hours | ~3 hours |
| Multi-obj | NSGA-II | 10,000 | 7 days | ~1 day |
| Uncertainty | DREAM | 100,000 | 69 days | ~9 days* |

*SCE-UA and DREAM have limited parallelism — actual speedup depends on
ngs/nChains, not total cores. SUFI-2 and NSGA-II have better parallelism
(LHS batches and population evaluation, respectively).

---

## 8. References

### Sensitivity Analysis

- **Cukier, R.I., et al.** (1973). Study of the sensitivity of coupled reaction
  systems to uncertainties in rate coefficients. I Theory.
  *The Journal of Chemical Physics*, 59(8), 3873-3878.
  *(Original FAST method)*

- **Saltelli, A., Tarantola, S., & Chan, K.P.-S.** (1999). A quantitative
  model-independent method for global sensitivity analysis of model output.
  *Technometrics*, 41(1), 39-56.
  *(Extended FAST — eFAST)*

- **Sobol, I.M.** (1993). Sensitivity estimates for nonlinear mathematical
  models. *Mathematical Modelling and Computational Experiments*, 1(4), 407-414.
  *(Original Sobol method)*

- **Saltelli, A.** (2002). Making best use of model evaluations to compute
  sensitivity indices. *Computer Physics Communications*, 145(2), 280-297.
  *(Saltelli sampling scheme for Sobol)*

- **Saltelli, A., et al.** (2010). Variance based sensitivity analysis of model
  output. Design and estimator for the total sensitivity index.
  *Computer Physics Communications*, 181(2), 259-270.

### Calibration Algorithms

- **Duan, Q., Sorooshian, S., & Gupta, V.** (1992). Effective and efficient
  global optimization for conceptual rainfall-runoff models.
  *Water Resources Research*, 28(4), 1015-1031.
  *(Original SCE-UA)*

- **Duan, Q., Gupta, V.K., & Sorooshian, S.** (1993). Shuffled complex
  evolution approach for effective and efficient global minimization.
  *Journal of Optimization Theory and Applications*, 76(3), 501-521.

- **Vrugt, J.A., et al.** (2008). Accelerating Markov chain Monte Carlo
  simulation by differential evolution with self-adaptive randomized
  subspace sampling. *International Journal of Nonlinear Sciences and
  Numerical Simulation*, 10(3), 273-290.
  *(Original DREAM)*

- **Vrugt, J.A.** (2016). Markov chain Monte Carlo simulation using the DREAM
  software package. *Environmental Modelling & Software*, 75, 273-316.
  *(Comprehensive DREAM reference)*

- **McKay, M.D., Beckman, R.J., & Conover, W.J.** (1979). A comparison of
  three methods for selecting values of input variables in the analysis of
  output from a computer code. *Technometrics*, 21(2), 239-245.
  *(Original Latin Hypercube Sampling)*

### SUFI-2

- **Abbaspour, K.C., Johnson, C.A., & van Genuchten, M.Th.** (2004).
  Estimating uncertain flow and transport parameters using a sequential
  uncertainty fitting procedure. *Vadose Zone Journal*, 3(4), 1340-1352.
  *(Original SUFI-2 algorithm)*

- **Abbaspour, K.C., et al.** (2007). Modelling hydrology and water quality in
  the pre-alpine/alpine Thur watershed using SWAT. *Journal of Hydrology*,
  333(2-4), 413-430. *(SUFI-2 applied to SWAT)*

- **Abbaspour, K.C., Rouholahnejad, E., Vaghefi, S., Srinivasan, R., Yang, H.,
  & Kløve, B.** (2015). A continental-scale hydrology and water quality model
  for Europe. *Journal of Hydrology*, 524, 733-752.
  *(SUFI-2 at continental scale, 95PPU methodology)*

### NSGA-II & Multi-Objective Optimization

- **Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T.** (2002). A fast and
  elitist multiobjective genetic algorithm: NSGA-II. *IEEE Transactions on
  Evolutionary Computation*, 6(2), 182-197.
  *(Original NSGA-II algorithm)*

- **Bekele, E.G. & Nicklow, J.W.** (2007). Multi-objective automatic calibration
  of SWAT using NSGA-II. *Journal of Hydrology*, 341(3-4), 165-176.
  *(NSGA-II applied to SWAT calibration)*

- **Confesor, R.B. & Whittaker, G.W.** (2007). Automatic calibration of
  hydrologic models with multi-objective evolutionary algorithm and Pareto
  optimization. *Journal of the American Water Resources Association*, 43(4),
  981-989.

### Diagnostic Calibration & Hydrograph Analysis

- **Gupta, H.V., Kling, H., Yilmaz, K.K., & Martinez, G.F.** (2009).
  Decomposition of the mean squared error and NSE performance criteria:
  Implications for improving hydrological modelling. *Journal of Hydrology*,
  377(1-2), 80-91.
  *(KGE metric and decomposition into correlation, bias, variability)*

- **Kling, H., Fuchs, M., & Paulin, M.** (2012). Runoff conditions in the
  upper Danube basin under an ensemble of climate change scenarios.
  *Journal of Hydrology*, 424-425, 264-277.
  *(Modified KGE — KGE' — used in modern hydrology)*

- **Yilmaz, K.K., Gupta, H.V., & Wagener, T.** (2008). A process-based
  diagnostic approach to model evaluation: Application to the NWS distributed
  hydrologic model. *Water Resources Research*, 44(9), W09417.
  *(Flow Duration Curve decomposition: FHV, FMS, FLV segments)*

- **Pfannerstill, M., Guse, B., & Fohrer, N.** (2014). Smart low flow
  signature metrics for an improved overall performance evaluation of
  hydrological models. *Journal of Hydrology*, 510, 447-458.
  *(FDC-based signature metrics for calibration diagnostics)*

- **Westerberg, I.K. & McMillan, H.K.** (2015). Uncertainty in hydrological
  signatures. *Hydrology and Earth System Sciences*, 19(9), 3951-3968.
  *(Hydrological signature uncertainty quantification)*

- **Eckhardt, K.** (2005). How to construct recursive digital filters for
  baseflow separation. *Hydrological Processes*, 19(2), 507-515.
  *(Eckhardt two-parameter baseflow filter — used in SWAT-DG diagnostics)*

- **Boyle, D.P., Gupta, H.V., & Sorooshian, S.** (2000). Toward improved
  calibration of hydrologic models: Combining the strengths of manual and
  automatic methods. *Water Resources Research*, 36(12), 3663-3674.
  *(Multi-criteria diagnostic calibration framework)*

- **Wagener, T., McIntyre, N., Lees, M.J., Wheater, H.S., & Gupta, H.V.**
  (2003). Towards reduced uncertainty in conceptual rainfall-runoff modelling:
  Dynamic identifiability analysis. *Hydrological Processes*, 17(2), 455-476.
  *(DYNIA — Dynamic Identifiability Analysis for parameter diagnostics)*

### SWAT-Specific

- **Arnold, J.G., et al.** (2012). SWAT: Model use, calibration, and validation.
  *Transactions of the ASABE*, 55(4), 1491-1508.

- **Neitsch, S.L., Arnold, J.G., Kiniry, J.R., & Williams, J.R.** (2011).
  Soil and Water Assessment Tool Theoretical Documentation, Version 2009.
  Texas Water Resources Institute Technical Report No. 406.
  *(SWAT theoretical basis — parameter physical meaning)*

- **Arnold, J.G., Moriasi, D.N., Gassman, P.W., et al.** (2012). SWAT: Model
  use, calibration, and validation. *Transactions of the ASABE*, 55(4),
  1491-1508.

- **Moriasi, D.N., Arnold, J.G., Van Liew, M.W., Bingner, R.L., Harmel, R.D.,
  & Veith, T.L.** (2007). Model evaluation guidelines for systematic
  quantification of accuracy in watershed simulations. *Transactions of the
  ASABE*, 50(3), 885-900.
  *(NSE, PBIAS, RSR performance thresholds for SWAT)*

### Software

- **Houska, T., Kraft, P., Chamorro-Chavez, A., & Breuer, L.** (2015). SPOTting
  model parameters using a ready-made Python package. *PLoS ONE*, 10(12).
  *(SPOTPY framework used by SWAT-DG)*
