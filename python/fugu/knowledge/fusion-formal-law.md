---
type: "Finding"
title: "Formal fusion law + statistical rigor"
description: "A_fuse = a*+cG−hB; fusion wins iff cG>hB. Bootstrap+McNemar confirm no weaver beats best lane; the oracle gap is significant but uncaptured."
resource: "repo://pi-llm-as-verifier/evals/thesis/bootstrap_ci.py"
tags:
  - "formal-model"
  - "bootstrap"
  - "mcnemar"
  - "oracle-capture"
  - "verdict"
  - "scope"
timestamp: 2026-06-20T21:07:48-06:00
---

The law behind the verdict. With best-lane accuracy `a*`, oracle `O`, headroom `G = O − a*`, weaver
oracle-capture `c`, and re-derivation harm `h` on best-correct disagreement mass `B`:

> **`A_fuse = a* + c·G − h·B`** → fusion beats the best lane **iff `c·G > h·B`** (`c > h·B/(O−a*)`).

As `a* → 1` or error-correlation `ρ → 1`, `G → 0` and achievable lift → `−h·B ≤ 0`.

# Schema

Paired bootstrap (20k resamples) + exact McNemar over the per-question outcomes in `three_mmlu.json` /
`three_gpqa.json` (`bootstrap_ci.py`, no new API calls).

# Examples

- **MMLU-Pro** (n=196): oracle Δ+0.0408 CI [0.0153, 0.0714] (McNemar p=0.0078) — **significant**; verifier Δ-0.0051 CI [-0.0255, 0.0153] — includes 0.
- **GPQA-diamond** (n=198): oracle Δ+0.0202 CI [0.0051, 0.0404] (McNemar p=0.125) — **significant**; verifier Δ+0.0 CI [-0.0202, 0.0202] — includes 0.

**No weaver's Δ-CI excludes 0** → statistically indistinguishable from the best lane. **The oracle Δ-CI
does** → the complementary signal is real but uncaptured. To win +1pp at zero harm GPQA needs capture
`c ≥ 0.495`; with realistic harm it is essentially unwinnable. Established for MC/componential; **untested
on long-horizon verifiable tasks** (SWE-bench-style) where headroom could be 10–20pp. External-audit
confidence in the broad law ~68%, in the narrow tested-regime claim ~85–90%.

# Citations

- `evals/thesis/README.md`; external pro-model adversarial audit; cf. [verdict](/fusion-verdict.md), [sweep](/lane-strength-sweep.md).
