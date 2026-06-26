# Thesis experiments: non-saturated benchmark + fusion vs frontier

Two experiments testing the repo's central thesis — *multiple lanes, synthesized into one
answer, can and should beat any single model* — on **non-saturated** ground (where frontier
models are not already at ceiling), with honest results.

## 1. A non-saturated benchmark: JudgeBench

Our authored verifier suites saturate (every strong model ~100% accuracy). **JudgeBench**
([2410.12784](https://arxiv.org/abs/2410.12784)) is an adversarial pairwise judge benchmark
(response A vs B, pick the correct one) over hard MMLU-Pro / LiveBench / LiveCodeBench pairs —
it maps directly onto `fmh evaluate-verifier`.

Fetch + convert a slice, then grade:

```bash
# raw_judgebench_gpt4o.jsonl + judgebench_slice.jsonl are produced by a fetch+convert step
fmh evaluate-verifier --suite evals/verifier/external/judgebench_slice.jsonl --model cx/gpt-5.5
```

| | accuracy | position_bias_rate |
|---|---|---|
| mock (floor) | **0.588** | 0.000 |
| our verifier (cx/gpt-5.5, swap-and-aggregate) | **0.902** | **0.843** |

The mock floor 0.588 confirms it is genuinely non-saturated. The headline is
`position_bias_rate = 0.843`: the raw judge flips its verdict with candidate order **84%**
of the time, yet swap-and-aggregate still lands **0.902** — the hardening doing heavy lifting
on a real, externally-authored benchmark. (Caveats: n=51 slice, mostly MMLU-Pro; cx/gpt-5.5 is
stronger than JudgeBench's published GPT-4o baseline ~0.60, so part of the gap is model strength.)

## 2. Fusion vs frontier on MMLU-Pro (`fusion_vs_frontier.py` + `climb.py`)

Generate an answer from N lanes, fuse them with a single synthesizer (our adopted
`DEFAULT_SYNTHESIS_INSTRUCTION`), and compare accuracy against the best single lane and the
frontier model alone, on hard MMLU-Pro MC questions (ground truth, frontier ~83–90% on this
slice).

```bash
python evals/thesis/fusion_vs_frontier.py --n 154 --synth-model cx/gpt-5.5 --rederive
python evals/thesis/climb.py   # escalating rungs until fusion beats the best lane
```

**Baseline (n=154):**

| | accuracy |
|---|---|
| best single lane (cx/gpt-5.5) | 0.896 |
| **fusion (all 4 lanes)** | 0.896 (tie) |
| frontier alone | 0.896 |
| **on the 31% disagreement subset** | frontier 0.75 → **fusion 0.771** (oracle 0.833) |

**The climb (6 rungs, n=70):** re-derive-from-evidence → strong synthesizer → synthesis
self-consistency → per-lane self-consistency → a diverse 6-lane pool (+qwen, +deepseek).
**No rung beat the best single lane** — best result was a tie; per-lane self-consistency and
the diverse pool slightly *hurt* (−0.029).

### Honest finding

On a benchmark of **individually-strong, highly-correlated** models (they fully agree on ~70–80%
of questions), aggregate fusion **cannot beat the best single lane by tuning the synthesizer** —
on agreement questions fusion equals the consensus by construction, and the synthesizer can't
manufacture a correct answer none of the lanes hold. But **where lanes disagree, fusion already
beats frontier and majority-vote** (0.771 vs 0.75), recovering most of the available headroom.

The binding constraint is **lane diversity/complementarity, not synthesis quality** — exactly
what the synthesizer benchmark (authored *complementary* partial answers → **+0.5 lift**) and the
literature predict (Mixture-of-Agents / More-Agents gains scale with diversity and task
difficulty). The thesis holds in the complementary/disagreement regime; it does not hold in
aggregate when the lanes are strong and correlated.

### Harder regime: GPQA-diamond (`--dataset gpqa`)

We re-ran the full 6-rung climb on GPQA-diamond (`hendrydong/gpqa_diamond_mc`, 198 Q, graduate-level,
frontier-hard) on the hypothesis that strong models would disagree more there, opening headroom. The
result was the **same tie pattern**: on the clean rungs (strong cx synthesizer, all lanes 0.84–0.89)
fusion **exactly tied** the best lane (0.886 = 0.886); **no rung beat it** (best margin 0.0). These
2026 models are strong even on GPQA-diamond and stay fairly tight, so the lanes still rarely supply a
correct answer the best lane missed.

Two honesty caveats on this run: the experiment carries **call-failure noise** — under concurrent
9router load some lane calls fail and count as wrong (e.g. gemini showed 0.39–0.40 on two rungs vs
0.86–0.89 on clean rungs), and the "diverse 6-lane" rung was **invalid** because two added lanes
(`qwen3.7-plus`, `deepseek-v4-flash`) returned 0.0 — entirely unavailable — so it was never a fair
decorrelation test. A clean diversity test needs lanes that are both available **and** genuinely
complementary.

**Bottom line across both benchmarks:** synthesis-side fusion of strong, similar-capability lanes
ties the best single lane in aggregate but does not beat it; the aggregate win needs lanes with
genuinely complementary correct answers (which the authored synthesizer benchmark provides → +0.5
lift), not just a harder benchmark.

### Oracle-capture: three fusion methods, measured honestly

The right metric is not aggregate accuracy but **oracle-capture** = how much of the recoverable
complementary signal a fusion recovers, where the **oracle** = "any lane is correct" (the ceiling of
perfect selection/fusion). On both MC benchmarks the oracle exceeds the best single lane by only
**+2–4%** — the signal exists but the headroom is tiny.

`fusion_vs_frontier.py` measures three weavers (each runs only on disagreement questions; consensus is
passed through):
- **synthesis** — one synthesizer re-derives from the lanes' reasoning (`DEFAULT_SYNTHESIS_INSTRUCTION`).
- **verifier-guided** — our swap-and-aggregate pairwise verifier adjudicates the DISTINCT answers,
  labeled only by option letter (reputation-blind), so a weak lane's idiosyncratically-correct answer can win.
- **judge-then-synthesize** — OpenRouter-Fusion-style: a judge emits a structured analysis (consensus,
  contradictions, unique insights, blind spots) WITHOUT merging, then the synthesizer writes the final
  answer grounded in it.

Reference results at rigorous N (synth/verifier/judge model = `cx/gpt-5.5`, lanes = cx/kimi/minimax/gemini):

| Benchmark | best lane | synthesis | verifier | judge | oracle |
|---|---|---|---|---|---|
| MMLU-Pro (n=196) | **0.883** | 0.878 (below) | 0.878 (below) | 0.872 (below) | 0.924 |
| GPQA-diamond (n=198) | **0.924** | 0.909 (below) | 0.924 (ties) | 0.924 (ties) | 0.944 |

**Honest verdict: at proper N, no method beats the best single lane on single-answer MC — a tie is the
best case** (verifier/judge on GPQA). Apparent wins at small N (n≈112–120) were within noise (2–4 question
headroom). What is robust:

1. **Re-derivation can hurt** (synthesis −74% capture on GPQA, −12% MMLU): re-deriving sometimes overrides
   a correct lane. **Selection-based methods (verifier/judge) are strictly safer** — they tie, never
   damage. If you must fuse atomic MC answers, *select, don't re-derive*.
2. **The signal exists but is uncapturable here**: on disagreements the methods recover ~0.66 (MMLU) /
   0.82 (GPQA) of an oracle ~0.86 / 0.94 — real partial recovery, just not enough to clear a near-ceiling
   best lane.
3. **The thesis's clear win is the *complementary* regime, not MC.** Where lanes hold separable correct
   *pieces* — the authored free-form synthesizer benchmark — fusion captured ~90–100% and beat best-lane
   by **+0.5**. On single-answer MC from strong correlated lanes, the best lane is already near the oracle
   ceiling and there is almost nothing to weave.

### Statistical rigor: bootstrap CIs + McNemar (`bootstrap_ci.py`)

"Ties" is not a single-run artifact — paired bootstrap (20k resamples) + exact McNemar on the per-question
outcomes confirm it. For each weaver vs the best single lane (`gpt-5.5`):

| MMLU-Pro (n=196) | acc | Δ vs best | Δ 95% CI | McNemar |
|---|---|---|---|---|
| oracle | 0.923 | **+0.041** | [+0.015, +0.071] | b=0 c=8 **p=0.008** |
| synthesis | 0.878 | −0.005 | [−0.026, +0.015] | p=1.00 |
| verifier | 0.878 | −0.005 | [−0.026, +0.015] | p=1.00 |
| judge | 0.872 | −0.010 | [−0.036, +0.015] | p=0.69 |

| GPQA-diamond (n=198) | acc | Δ vs best | Δ 95% CI | McNemar |
|---|---|---|---|---|
| oracle | 0.944 | **+0.020** | [+0.005, +0.040] | b=0 c=4 p=0.13 |
| synthesis | 0.909 | −0.015 | [−0.040, +0.005] | p=0.38 |
| verifier | 0.924 | +0.000 | [−0.020, +0.020] | p=1.00 |
| judge | 0.924 | +0.000 | [−0.020, +0.020] | p=1.00 |

**No weaver's Δ CI excludes 0** and no McNemar is significant → fusion is statistically indistinguishable
from the best lane. **The oracle Δ CI *does* exclude 0** (MMLU p=0.008) → the complementary signal is real
and significant; the weavers just don't capture it. Signal present, uncapturable here.

### The formal law (why frontier lanes can't be woven)

An adversarial external audit derived the law behind all of this. With best-lane accuracy `a*`, oracle `O`,
headroom `G = O − a*`, weaver oracle-capture `c`, and re-derivation harm `h` on best-correct disagreement
mass `B`:

> **`A_fuse = a* + c·G − h·B`**, so fusion beats the best lane **iff `c·G > h·B`**, i.e. `c > h·B / (O − a*)`.

As `a* → 1` or error-correlation `ρ → 1`, `G → 0` and the achievable lift → `−h·B ≤ 0`. Plugging in our
numbers: to win by +1pp with *zero* harm, MMLU needs capture `c ≥ 0.245`, **GPQA needs `c ≥ 0.495`**; with
any realistic harm (`B≈0.10`) GPQA is essentially unwinnable (`h < 0.041`). This is the math behind
"strong correlated frontier lanes leave nothing to weave" — and it predicts the [sweep](#the-lift-curve-fusion-lift-is-a-function-of-lane-incompleteness-lane_strength_sweepy)
exactly.

**Scope caveat (the honest limit):** this verdict is rigorously established for **single-answer MC and
comprehensively-prompted componential tasks**. It is *not* tested on **long-horizon verifiable tasks**
(SWE-bench-style repair, agentic coding) where models fail at *different stages* and oracle headroom could
be 10–20pp — the one regime where `decompose → route → recompose` / critique-revise fusion might still beat
the best lane. External audit confidence in the verdict *as a broad frontier-fusion law*: **~68%**; in the
narrow tested-regime claim: ~85–90%.

### Correction: the +0.5 was an authoring artifact (`complementary_lanes.py`)

The "+0.5 in the complementary regime" above came from the synthesizer benchmark's *authored* partial
candidates (each hand-crafted to cover only ~40–60% of the checklist). To test whether that lift is real,
`complementary_lanes.py` reuses the same componential questions + checklists but feeds **live generations
from real lanes** (kimi/minimax/gemini/cx) instead of the authored partials.

Result (n=15 componential questions): **best single lane covers 0.978 of the checklist; fusion 0.973;
lift −0.005 (≈ zero).** When real strong models are asked to answer comprehensively, **each lane is already
near-complete on its own** — there is no partiality to weave. The +0.5 lift does **not** reproduce with real
lanes; it was an artifact of artificially-partial candidates.

**Revised, unified conclusion:** with strong modern lanes, fusion **ties** the best single lane in *every*
regime we tested — atomic MC *and* componential open-ended — because the lanes are individually near-complete
and near-correct. Fusion's win requires genuinely partial inputs: weaker/smaller/specialized lanes, terse
generations, or tasks hard enough that even strong models are individually incomplete. (Open question being
checked against the literature: the published "fusion beats frontier" results largely use weaker/open-source
constituents, where this partiality is real.)

**Practical takeaway:** with frontier-class lanes, prefer **selecting** the right lane (cheap, ties fusion,
never hurts) over multi-call fusion; reserve fusion for genuinely heterogeneous/weaker lane pools or
hard-enough tasks. OpenRouter's Fusion is the same architecture (panel → structured judge → synthesizer;
Mixture-of-Agents, arXiv 2406.04692) and reports gains on open-ended tasks with a *diverse* panel — the
diversity/weakness condition this whole investigation points to.

### The lift curve: fusion-lift is a function of lane *incompleteness* (`lane_strength_sweep.py`)

This is the whole investigation in one curve. We take real comprehensive lane answers and apply a
**completeness dial** `p`: each lane keeps a random `p`-fraction of its sentences (a different subset
per lane → complementary partials). At `p=1.0` lanes are complete; as `p` drops they partial-ize.
Measured (componential questions, coverage vs checklist):

| dial `p` | best-lane | fusion | oracle | **lift** | headroom | capture | beats best-lane |
|---|---|---|---|---|---|---|---|
| **1.00** | 0.987 | 0.957 | 0.987 | **−0.030** | 0.000 | — | **No (the zero-crossing)** |
| 0.75 | 0.930 | 0.962 | 0.987 | +0.032 | 0.056 | 0.56 | Yes |
| 0.50 | 0.832 | 0.921 | 0.930 | +0.089 | 0.099 | 0.91 | Yes |
| 0.35 | 0.757 | 0.907 | 0.879 | +0.150 | 0.122 | 1.22 | Yes |
| 0.20 | 0.612 | 0.839 | 0.761 | +0.227 | 0.149 | 1.52 | Yes |

**Fusion-lift is monotonic in lane incompleteness.** At full completeness (`p=1`, best-lane 0.987 — the
frontier regime) lift is **≈0, even slightly negative** (re-derivation shaves a few points): the
zero-crossing sits exactly where real strong lanes live. As lanes partial-ize, best-lane falls, oracle
headroom opens, and lift climbs to **+0.23** at `p=0.2`. The entire pro-fusion literature operates to the
*right* of that curve's rise — in the partial-lane regime — which is why their lift is large and ours is
zero. (Note `capture > 1` at low `p`: fusion coverage exceeds the literal union — the synthesizer recovers
points no truncated lane stated, i.e. it re-derives from partial cues, so at very low `p` it is adding its
own knowledge, not only weaving. The headline shape is unaffected.)

### Validated against the literature (arXiv critical review)

A critical review of the core fusion/ensemble papers confirms our result is what the careful literature
*predicts* — every published "fusion beats the best model" demonstration lives in a weak-and-diverse-lane
regime and/or leans on a judge-bias metric:

- **Mixture-of-Agents** (2406.04692): the 65.1% "beats GPT-4o" headline uses only *open-source, sub-frontier*
  proposers (43–51% individual win-rate) and the **AlpacaEval LLM-judge win-rate** metric; its aggregator is
  also its strongest proposer (best-in-mix confound), and its FLASK results show its outputs are *more verbose*
  — the direction that inflates judge win-rate. The one ground-truth (MATH) result is buried and ~flat.
- **LLM-Blender** (2306.02561): 2023-era 6B–16B open-source lanes, ChatGPT-as-judge / reference-overlap — the
  textbook weak-lane regime, no ground-truth-accuracy benchmark.
- **More Agents Is All You Need** (2402.05120): single-model resampling (self-consistency), ground-truth
  accuracy; a weak model's ensemble *reaches* a stronger single model but **never beats the strongest baseline**,
  and gains shrink as the base model strengthens.
- **Self-MoA** (2502.00674, ICML 2025) — the decisive one: MoA quality is governed by proposer **quality, not
  diversity**; mixing diverse weaker models drags the ensemble toward its weakest member; self-aggregating the
  single best model beats all 13 mixed-model configs when one model dominates; honest cross-task mixing lift <~0.4%.

**Verdict: "fusion beats frontier" is not a general claim.** It holds only when lanes are genuinely weak/partial
with large oracle headroom, and is amplified by LLM-judge metrics (where gains run ~an order of magnitude larger
than on ground truth). Both conditions vanish with strong, individually-complete frontier lanes on ground-truth
tasks — exactly our regime, where fusion ties the best lane. Our MMLU/GPQA runs supply the frontier-vs-frontier
datapoint **no reviewed paper provides**, and the +0.5 we saw with authored partials is us reproducing the
literature's favorable (weak-lane) condition artificially. Field evidence quality: *mixed* (judge-bias,
best-in-mix confound, and open-source-only settings pervade the pro-fusion results).

> `*.json`, `*.jsonl`, and `evals/verifier/external/` are gitignored — reproducible run outputs.

**Distilled knowledge:** the highest-signal findings here are auto-exported to an
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog) bundle at
[`knowledge/`](../../knowledge/index.md) — run `python knowledge/build_okf.py` after an experiment to
refresh the live metrics (it reads these `evals/thesis/*.json` outputs and stamps fresh values).
