"""Generate an Open Knowledge Format (OKF v0.1) bundle of this project's highest-signal findings.

OKF is a vendor-neutral knowledge format: plain markdown + YAML frontmatter, git-versionable,
human- and agent-readable. Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf

This script is the *automatic save* path: it reads the canonical experiment artifacts
(``evals/thesis/*.json``, which are gitignored run outputs) plus a curated registry of distilled
findings, and emits a conformant bundle under ``knowledge/`` — concept files with frontmatter
(``type``/``title``/``description``/``resource``/``tags``/``timestamp``), an ``index.md`` for
progressive disclosure, and a date-grouped ``log.md``. Re-run after any experiment to refresh the
live metrics; the distilled ``.md`` are committed so the knowledge survives even though the source
JSONs are not.

    python knowledge/build_okf.py
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent            # knowledge/  == OKF bundle root
REPO = ROOT.parent
THESIS = REPO / "evals" / "thesis"


def _load(name: str) -> dict | None:
    try:
        return json.loads((THESIS / name).read_text(encoding="utf-8"))
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _today() -> str:
    return datetime.date.today().isoformat()


def _scalar(v: str) -> str:
    """Emit a YAML-safe double-quoted scalar."""
    return json.dumps(str(v), ensure_ascii=False)


def _frontmatter(type_: str, title: str, description: str, resource: str, tags: list[str]) -> str:
    lines = ["---", f"type: {_scalar(type_)}", f"title: {_scalar(title)}",
             f"description: {_scalar(description)}"]
    if resource:
        lines.append(f"resource: {_scalar(resource)}")
    lines.append("tags:")
    lines += [f"  - {_scalar(t)}" for t in tags]
    lines.append(f"timestamp: {_now_iso()}")
    lines.append("---")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Concept bodies — curated high-signal prose with live metrics injected from result JSONs.
# --------------------------------------------------------------------------------------

def _body_verdict() -> str:
    mm, gp, comp = _load("three_mmlu.json"), _load("three_gpqa.json"), _load("complementary.json")

    def row(d, label):
        if not d:
            return f"| {label} | _(pending — run fusion_vs_frontier.py)_ |  |  |  |  |"
        return (f"| {label} (n={d['n']}) | {d['best_lane_accuracy']} | {d['fusion_all_accuracy']} | "
                f"{d['fusion_verifier_accuracy']} | {d['fusion_judge_accuracy']} | {d['oracle_accuracy']} |")

    comp_line = ("_(pending — run complementary_lanes.py)_" if not comp else
                 f"best single lane **{comp['mean_best_lane_coverage']}**, fusion "
                 f"{comp['mean_fusion_coverage']}, lift **{comp['mean_lift']:+}** (≈ 0)")
    return f"""
With strong, frontier-class lanes, multi-lane fusion **ties** the best single lane in every regime
tested — it does not beat it. This is the project's central empirical result.

# Schema

Lanes (one distinct model per lane) → ranked → a single synthesizer / verifier-guided weaver.
Models via 9router: `cx/gpt-5.5`, `kimi/kimi-k2.6`, `minimax/MiniMax-M3`, `ag/gemini-3.5-flash-low`.
Three weavers compared: single-pass **synthesis**, **verifier-guided** selection
([swap-and-aggregate](/swap-and-aggregate-verifier.md)), and OpenRouter-style **judge-then-synthesize**.

# Examples

Single-answer MC, rigorous N (accuracy):

| Benchmark | best lane | synthesis | verifier | judge | oracle |
|---|---|---|---|---|---|
{row(mm, "MMLU-Pro")}
{row(gp, "GPQA-diamond")}

No weaver beats the best lane; the best case is a *tie* (verifier/judge on GPQA). The oracle
(any-lane-correct) sits only ~2–4% above best-lane, and re-derivation can actively **hurt**
(synthesis below best-lane on GPQA). Selection-based weavers are strictly safer than re-derivation.

Componential / open-ended with **real** lane generations: {comp_line}. The large `+0.5` lift seen
on the synthesizer benchmark was an **artifact of authored ~40–60%-partial candidates** — real strong
models are each near-complete, so there is nothing to weave. The exact partiality→lift relationship is
quantified in [the lane-strength sweep](/lane-strength-sweep.md), and the result is corroborated by
[the fusion literature](/fusion-literature-review.md).

# Citations

- `evals/thesis/README.md` — full tables, disagreement-subset breakdowns, and caveats.
"""


def _body_sweep() -> str:
    s = _load("sweep.json")
    if not s or not s.get("curve"):
        table = "_(pending — run `python evals/thesis/lane_strength_sweep.py`)_"
    else:
        head = "| dial p | best-lane | fusion | oracle | **lift** | headroom | capture | beats? |\n|---|---|---|---|---|---|---|---|"
        rows = "\n".join(
            f"| {c['dial_p']:.2f} | {c['best_lane_coverage']:.3f} | {c['fusion_coverage']:.3f} | "
            f"{c['oracle_coverage']:.3f} | **{c['fusion_lift']:+.3f}** | {c['oracle_headroom']:.3f} | "
            f"{c['oracle_capture']:+.2f} | {c['fusion_beats_best_lane']} |"
            for c in s["curve"])
        table = head + "\n" + rows
    return f"""
A controlled completeness dial that locates where fusion-lift crosses zero. Each lane keeps a random
`p`-fraction of its sentences (a different subset per lane → complementary partials); at `p=1.0` lanes
are complete, and as `p` shrinks they become partial.

# Schema

Generate one real comprehensive answer per lane, then sweep `p ∈ {{1.0, 0.75, 0.5, 0.35, 0.2}}`,
grading best-lane, fusion, and union(oracle) coverage against each question's checklist.
Source: `evals/thesis/lane_strength_sweep.py`.

# Examples

{table}

The prediction this tests: **lift ≈ 0 when best-lane ≈ 1** (the frontier/complete regime — our
[verdict](/fusion-verdict.md)), rising as completeness drops (the weak/partial regime where the entire
pro-fusion [literature](/fusion-literature-review.md) operates). The zero-crossing marks the boundary
between "fuse" and "just pick the best lane".
"""


def _body_verifier() -> str:
    return """
Swap-and-aggregate is the reputation-blind pairwise verifier the harness uses to adjudicate competing
candidate answers — the component that scores **0.902 on JudgeBench** (vs a 0.588 mock floor).

# Schema

Every pairwise comparison is run in BOTH orderings (A→B and B→A); a `vote_margin < 0.7` forces a
`tie` (position-bias guard). Candidates are labeled neutrally (e.g. by option letter only), so a weak
lane's idiosyncratically-correct answer can win on merit rather than reputation. Verifier prompts are
evidence-first (observations before any score), and candidate text is scanned for judge-manipulation
patterns. Source: `.agents/skills/llm-as-verifier/scripts/lav_runner.py` (`run_compare`).

# Examples

Used as the `verifier-guided` weaver in [the fusion verdict](/fusion-verdict.md): on disagreement
questions it adjudicates the distinct answers and ties the best lane (never hurting it), whereas
re-derivation can. JudgeBench: accuracy 0.902, position-bias rate 0.843 → mitigated by the swap guard.

# Citations

- arXiv 2410.12784 (JudgeBench) — the non-saturated pairwise-judge benchmark.
"""


def _body_pipeline() -> str:
    return """
The fusion meta-harness: fan out diverse lanes, rank them, fuse/adjudicate into one answer, gate on a
reliability verifier. Synthesizer and verifier are forced to be different model families (fails closed).

# Schema

`explore` lanes (one distinct model per lane, over 9router) → rubric-scored & ranked best-first →
single **synthesizer** (fuses, no top-K truncation) → **verifier** reliability gate. Drivable via the
`fmh` CLI and an MCP server. Key levers: synthesizer model + prompt (`DEFAULT_SYNTHESIS_INSTRUCTION`),
verifier model/family, lane pool.

# Examples

- `fmh run-task <task.json> --profile explore --explore-models "kimi/kimi-k2.6,minimax/MiniMax-M3,ag/gemini-3.5-flash-low,cx/gpt-5.5"`
- The [verdict](/fusion-verdict.md) is that this pipeline's *value* is regime-dependent: it wins with
  weak/partial lanes and ties with strong lanes (prefer selection there). The
  [swap-and-aggregate verifier](/swap-and-aggregate-verifier.md) is the most robust single component.
"""


def _body_literature() -> str:
    return """
A critical review of the core multi-LLM fusion papers: every published "fusion beats the best model"
result lives in a weak-and-diverse-lane regime and/or leans on an LLM-judge win-rate metric — so it
*predicts* our finding that strong frontier lanes tie.

# Schema

Each paper assessed on three axes: model strength (weak/open-source vs frontier), metric (LLM-judge
win-rate vs ground-truth accuracy), and whether it beats the **best single** constituent (not the average).

# Examples

- **Mixture-of-Agents** (2406.04692): open-source sub-frontier proposers (43–51% indiv.), AlpacaEval
  LLM-judge metric, aggregator = strongest proposer (best-in-mix confound); ground-truth MATH ~flat.
- **LLM-Blender** (2306.02561): 2023-era 6B–16B open-source lanes, ChatGPT-as-judge.
- **More Agents Is All You Need** (2402.05120): single-model self-consistency, ground-truth accuracy;
  reaches but never beats the strongest baseline; gains shrink as the base model strengthens.
- **Self-MoA** (2502.00674, ICML 2025) — decisive: MoA quality is governed by proposer *quality, not
  diversity*; mixing weaker models drags toward the weakest; honest cross-task mixing lift <~0.4%.

**Verdict:** "fusion beats frontier" is not a general claim — it requires partial lanes + large oracle
headroom, both of which vanish at frontier strength on ground-truth tasks. Supports [our verdict](/fusion-verdict.md).

# Citations

- arXiv: 2406.04692, 2306.02561, 2402.05120, 2502.00674.
"""


def _body_benchmarks() -> str:
    return """
The harness ships two graded benchmarks (each with an easy + hard suite), run on real models via 9router.

# Schema

- **Verifier (selection):** `evals/verifier/labeled/` + JudgeBench. Metrics: accuracy,
  decisive_accuracy, tie_rate, `position_bias_rate`, flag_recall. `fmh evaluate-verifier --model <id>`.
- **Synthesizer (fusion lift):** `evals/synthesizer/`. Headline = `lift = synthesis_coverage −
  best_lane_coverage` on authored partial candidates. `fmh evaluate-synthesizer --model <id>`.
- **Thesis (frontier-vs-frontier):** `evals/thesis/` — `fusion_vs_frontier.py` (MMLU-Pro/GPQA, three
  weavers + oracle-capture), `complementary_lanes.py` (real-lane coverage), `lane_strength_sweep.py`.

# Examples

The synthesizer benchmark shows large lift (+0.5 on the hard suite) — but only because its candidates
are *authored* to be partial; see [the verdict](/fusion-verdict.md) and
[sweep](/lane-strength-sweep.md) for why this does not reproduce with real strong lanes.

# Citations

- `evals/verifier/README.md`, `evals/synthesizer/README.md`, `evals/thesis/README.md`.
"""


def _body_distill() -> str:
    try:
        d = json.loads((REPO / "distill" / "eval_result.json").read_text(encoding="utf-8"))
    except Exception:
        d = None
    if not d:
        block = "_(pending — run `bash distill/_run_full.sh` or the Colab notebook `distill/colab_finetune.ipynb`)_"
    else:
        b, t = d["base"], d["tuned"]
        agg, flip = t["aggregate_accuracy"], t["position_bias_flip_rate"]
        passed = agg >= 0.82 and flip <= 0.10
        block = (
            f"Student `{d['model']}`, QLoRA on {d.get('max_train', '?')} RewardBench examples "
            f"(both orderings), evaluated on {t['n']} held-out JudgeBench pairs:\n\n"
            "| | aggregate acc | raw-call acc | position-bias flip | consistent acc |\n"
            "|---|---|---|---|---|\n"
            f"| base (untuned) | {b['aggregate_accuracy']} | {b['raw_call_accuracy']} | {b['position_bias_flip_rate']} | {b['consistent_accuracy']} |\n"
            f"| **tuned** | **{agg}** | {t['raw_call_accuracy']} | **{flip}** | {t['consistent_accuracy']} |\n\n"
            f"Frontier reference {d.get('frontier_reference', 0.902)}, mock floor {d.get('mock_floor', 0.588)}. "
            f"Tuned {'**clears**' if passed else 'falls below'} the ≥0.82 aggregate / ≤0.10 flip go/no-go bar."
        )
    return f"""
Distil the [swap-and-aggregate verifier](/swap-and-aggregate-verifier.md) (0.902 on JudgeBench) into a
cheap local pairwise judge via QLoRA, so judging can run without a frontier API call.

# Schema

Train on RewardBench (both orderings → order-invariance), eval on the held-out JudgeBench `gpt` split
with the same swap-and-aggregate protocol (raw acc, position-bias flip rate, aggregate acc). Pipeline +
Colab notebook in `distill/`; runs headless on a Colab T4 via the `colab` CLI.

# Examples

{block}

# Citations

- `distill/README.md`; JudgeBench arXiv 2410.12784.
"""


def _body_law() -> str:
    try:
        ci = json.loads((THESIS / "bootstrap_ci.json").read_text(encoding="utf-8"))
    except Exception:
        ci = None
    if not ci:
        evidence = "_(run `python evals/thesis/bootstrap_ci.py`)_"
    else:
        rows = []
        for r in ci:
            m = r["methods"]
            o, v = m.get("oracle", {}), m.get("verifier", {})
            rows.append(
                f"- **{r['dataset']}** (n={r['n']}): oracle Δ{o.get('delta_vs_best'):+} CI {o.get('delta_ci')} "
                f"(McNemar p={o.get('mcnemar', {}).get('p')}) — **significant**; "
                f"verifier Δ{v.get('delta_vs_best'):+} CI {v.get('delta_ci')} — includes 0.")
        evidence = "\n".join(rows)
    return f"""
The law behind the verdict. With best-lane accuracy `a*`, oracle `O`, headroom `G = O − a*`, weaver
oracle-capture `c`, and re-derivation harm `h` on best-correct disagreement mass `B`:

> **`A_fuse = a* + c·G − h·B`** → fusion beats the best lane **iff `c·G > h·B`** (`c > h·B/(O−a*)`).

As `a* → 1` or error-correlation `ρ → 1`, `G → 0` and achievable lift → `−h·B ≤ 0`.

# Schema

Paired bootstrap (20k resamples) + exact McNemar over the per-question outcomes in `three_mmlu.json` /
`three_gpqa.json` (`bootstrap_ci.py`, no new API calls).

# Examples

{evidence}

**No weaver's Δ-CI excludes 0** → statistically indistinguishable from the best lane. **The oracle Δ-CI
does** → the complementary signal is real but uncaptured. To win +1pp at zero harm GPQA needs capture
`c ≥ 0.495`; with realistic harm it is essentially unwinnable. Established for MC/componential; **untested
on long-horizon verifiable tasks** (SWE-bench-style) where headroom could be 10–20pp. External-audit
confidence in the broad law ~68%, in the narrow tested-regime claim ~85–90%.

# Citations

- `evals/thesis/README.md`; external pro-model adversarial audit; cf. [verdict](/fusion-verdict.md), [sweep](/lane-strength-sweep.md).
"""


def _body_agentic() -> str:
    try:
        d = json.loads((REPO / "evals" / "agentic" / "tau_fusion.json").read_text(encoding="utf-8"))
    except Exception:
        d = None
    if not d:
        block = "_(run `python evals/agentic/tau_fusion.py --domain airline`)_"
    else:
        block = (
            f"tau-bench airline, n={d['n']}, lanes {', '.join(x.split('/')[-1] for x in d['lanes'])}:\n\n"
            f"- best_lane **{d['best_lane']}**, oracle **{d['oracle']}** → headroom **+{d['headroom']}** (large, unlike MC's 2–4pp)\n"
            f"- fusion_verifier **{d['fusion_verifier']}** (random {d['random_select']}) → "
            f"**oracle-capture {int(d['oracle_capture'] * 100)}%**, "
            f"{'beats' if d['fusion_beats_best_lane'] else 'ties'} the best lane\n\n"
            "The verifier judges trajectories to ~best-lane quality (beats random) but can't identify the "
            "oracle-unique solves — judging a DB-mutating trajectory from its transcript is too hard.")
    return f"""
The long-horizon verifiable regime the MC verdict did not cover. On tau-bench (objective final-state
reward — no LLM judge), strong lanes do NOT saturate, so real oracle headroom appears — but
verifier-selection still cannot capture it.

# Schema

Each lane plays the tool-calling agent (`tau_headroom.py`); a reputation-blind verifier then reads the
policy + goal + each lane's action transcript and picks the best trajectory (`tau_fusion.py`). Reward is
objective (final DB state). Routed via 9router.

# Examples

{block}

**The lever that wins is OUTCOME-AWARE selection.** On the *same* trajectories, a verifier shown each
lane's resulting DB changes (`--env-aware`) scores fusion **0.75 / +50% capture and BEATS the best lane
(0.708)**, while a transcript-only verifier scores **0.667 / −49% (hurts)**. Swap-and-aggregate
(position-bias fix) does nothing — *what the verifier sees* (outcome vs intent) is the lever, not how many
orderings. **Critique-revise HURTS**: a reviser shown the prior attempts scored **0.583 — below its own
solo 0.708**, 0 new successes beyond oracle — re-derivation harm, agentic edition (cf. Self-MoA).

**Final law:** fusion beats the best lane **iff (a) headroom exists AND (b) an OUTCOME-AWARE verifier
SELECTS it.** MC/componential fail (a); agentic meets both only via outcome-aware selection.
Re-derivation/critique-revise hurts in every regime. Winning recipe everywhere: a strong outcome-aware
verifier that **selects, never re-derives** — this repo's core competency.

# Citations

- `evals/agentic/README.md`; tau-bench (sierra-research); cf. [verdict](/fusion-verdict.md), [formal law](/fusion-formal-law.md).
"""


def _body_roadmap() -> str:
    return """
arXiv-grounded next steps to push outcome-aware agentic fusion past 0.75 (full table:
`evals/agentic/ROADMAP.md`). The literature independently validates our `--env-aware` DB-diff verifier
(ProRe 2509.21823, R2E-Gym 2504.07164, AgentRM 2502.18407, ToolRM 2510.26167) — the lever is verifier
quality, not more lanes or revision.

# Examples

Cheapest-highest-EV (all rollout-free via the trajectory cache):
1. **Verifier-accuracy gate** — require ≥60% pairwise discrimination before fusion overrules the best lane;
   below ~60% the verifier HURTS via self-enhancement bias (2512.02304) — exactly our −49%.
2. **Strip-the-transcript ablation** — diff-only vs diff+transcript; the transcript may be a style-biased
   distractor (R2E-Gym 2504.07164).
3. **DB-diff as PRIMARY ranking, LLM verifier as tie-breaker only** — largest near-term lift (2504.07164).

Then: GenRM YES/NO scoring (2408.15240), aspect-verifiers over the diff (2502.20379), pass^k reporting
(2506.07982), a state-PROBING verifier with read-only getters (2509.21823), and a trained small outcome
ORM on the free tau reward labels (2510.26167, 2412.21139).

Avoid: critique-revise (re-derivation harm 2310.01798), debate/MoA blending (2509.05396), position-bias
fixes (zero agentic effect), and letting a <60% verifier overrule the best lane.

**Status — steps 1–6 implemented** in `evals/agentic/` (`verifier_accuracy.py`, `verifier_strategies.py`,
`adaptive.py`, `passk.py`; tau_fusion flags `--strategy/--adaptive/--reserve-lanes/--gate/--trials`). The
env-aware verifier measures **0.923 pairwise discrimination (≥0.60 gate PASS)** — the mechanistic proof of
the agentic win. Remaining (heavy): state-probing verifier, trained outcome ORM, headroom-widening.

# Citations

- `evals/agentic/ROADMAP.md`; the arxiv-agentic-verifier-roadmap workflow; cf. [agentic finding](/agentic-headroom.md).
"""


CONCEPTS = [
    {"file": "fusion-verdict.md", "type": "Finding",
     "title": "Fusion vs Frontier — verdict",
     "description": "With strong frontier lanes, multi-lane fusion ties (never beats) the best single lane; the +0.5 lift was an authoring artifact.",
     "resource": "repo://pi-llm-as-verifier/evals/thesis/README.md",
     "tags": ["fusion", "verdict", "oracle-capture", "mmlu-pro", "gpqa", "negative-result"],
     "body": _body_verdict},
    {"file": "lane-strength-sweep.md", "type": "Finding",
     "title": "Lane-strength dial sweep",
     "description": "Controlled completeness dial locating where fusion-lift crosses zero as lanes approach individual completeness.",
     "resource": "repo://pi-llm-as-verifier/evals/thesis/lane_strength_sweep.py",
     "tags": ["fusion", "ablation", "lift-curve", "completeness", "oracle-headroom"],
     "body": _body_sweep},
    {"file": "swap-and-aggregate-verifier.md", "type": "Method",
     "title": "Swap-and-aggregate verifier",
     "description": "Reputation-blind pairwise verifier with position-bias guard; scores 0.902 on JudgeBench.",
     "resource": "repo://pi-llm-as-verifier/.agents/skills/llm-as-verifier/scripts/lav_runner.py",
     "tags": ["verifier", "pairwise", "position-bias", "judgebench", "llm-as-judge"],
     "body": _body_verifier},
    {"file": "fusion-pipeline.md", "type": "Architecture",
     "title": "Fusion meta-harness pipeline",
     "description": "Explore lanes → rank → synthesize → verifier gate, with enforced model-family independence.",
     "resource": "repo://pi-llm-as-verifier/harness",
     "tags": ["architecture", "pipeline", "explore", "synthesizer", "9router"],
     "body": _body_pipeline},
    {"file": "fusion-literature-review.md", "type": "Literature Review",
     "title": "Multi-LLM fusion literature — critical review",
     "description": "The pro-fusion literature's wins all live in weak-lane / judge-bias regimes; predicts our frontier-lane tie.",
     "resource": "https://arxiv.org/abs/2502.00674",
     "tags": ["literature", "mixture-of-agents", "self-moa", "llm-blender", "judge-bias"],
     "body": _body_literature},
    {"file": "benchmarks.md", "type": "Benchmark",
     "title": "Verifier, synthesizer & thesis benchmarks",
     "description": "Two graded benchmarks (verifier selection, synthesizer lift) plus the frontier-vs-frontier thesis suite.",
     "resource": "repo://pi-llm-as-verifier/evals",
     "tags": ["benchmark", "evaluation", "verifier", "synthesizer", "9router"],
     "body": _body_benchmarks},
    {"file": "distilled-verifier.md", "type": "Finding",
     "title": "Distilled small verifier (QLoRA)",
     "description": "QLoRA-distil the 0.902 swap-and-aggregate judge into a cheap local gemma-2-2b; base-vs-tuned on JudgeBench.",
     "resource": "repo://pi-llm-as-verifier/distill/README.md",
     "tags": ["distillation", "verifier", "qlora", "gemma", "judgebench", "colab"],
     "body": _body_distill},
    {"file": "fusion-formal-law.md", "type": "Finding",
     "title": "Formal fusion law + statistical rigor",
     "description": "A_fuse = a*+cG−hB; fusion wins iff cG>hB. Bootstrap+McNemar confirm no weaver beats best lane; the oracle gap is significant but uncaptured.",
     "resource": "repo://pi-llm-as-verifier/evals/thesis/bootstrap_ci.py",
     "tags": ["formal-model", "bootstrap", "mcnemar", "oracle-capture", "verdict", "scope"],
     "body": _body_law},
    {"file": "agentic-headroom.md", "type": "Finding",
     "title": "Agentic long-horizon: outcome-aware selection wins",
     "description": "tau-bench airline has real headroom (+12-21pp); an OUTCOME-AWARE verifier (sees each lane's DB changes) captures +50% and beats best lane — the first robust fusion win; transcript-only selection and critique-revise both hurt.",
     "resource": "repo://pi-llm-as-verifier/evals/agentic/tau_fusion.py",
     "tags": ["agentic", "tau-bench", "long-horizon", "oracle-capture", "verifier", "trajectory"],
     "body": _body_agentic},
    {"file": "agentic-roadmap.md", "type": "Reference",
     "title": "Roadmap: pushing outcome-aware agentic fusion past 0.75",
     "description": "arXiv-grounded prioritized next steps — verifier-accuracy gate, diff-primary ranking, GenRM, aspect-verifiers, state-probing, trained ORM; avoid revision/debate/swap.",
     "resource": "repo://pi-llm-as-verifier/evals/agentic/ROADMAP.md",
     "tags": ["roadmap", "agentic", "verifier", "best-of-n", "next-steps", "arxiv"],
     "body": _body_roadmap},
]


def write_concepts() -> list[dict]:
    for c in CONCEPTS:
        text = _frontmatter(c["type"], c["title"], c["description"], c["resource"], c["tags"])
        text += "\n\n" + c["body"]().strip() + "\n"
        (ROOT / c["file"]).write_text(text, encoding="utf-8")
    return CONCEPTS


def write_index(concepts: list[dict]) -> None:
    lines = [
        "# pi-llm-as-verifier — Knowledge Bundle",
        "",
        "Highest-signal findings from the fusion meta-harness, in "
        "[Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog) (OKF v0.1). "
        "Auto-generated by `build_okf.py` — re-run after experiments to refresh live metrics.",
        "",
    ]
    by_type: dict[str, list[dict]] = {}
    for c in concepts:
        by_type.setdefault(c["type"], []).append(c)
    for type_ in ["Finding", "Method", "Architecture", "Benchmark", "Literature Review"]:
        for c in by_type.get(type_, []):
            lines.append(f"- **[{c['title']}](/{c['file']})** — _{c['type']}_ — {c['description']}")
    lines.append("")
    (ROOT / "index.md").write_text("\n".join(lines), encoding="utf-8")


def write_log() -> None:
    """Date-grouped change history, newest first (OKF reserved file)."""
    milestones = {
        _today(): ["**Update** — regenerated bundle; refreshed live metrics from `evals/thesis/*.json`. "
                   "Added the lane-strength sweep finding."],
        "2026-06-19": ["**Update** — recorded the fusion verdict (strong lanes tie; +0.5 was an authoring "
                       "artifact) and the critical literature review (Self-MoA et al.)."],
        "2026-06-18": ["**Creation** — initial knowledge bundle: pipeline, swap-and-aggregate verifier, "
                       "and the verifier/synthesizer benchmarks."],
    }
    lines = ["# Log", ""]
    for day in sorted(milestones, reverse=True):
        lines.append(f"## {day}")
        lines += [f"- {e}" for e in milestones[day]]
        lines.append("")
    (ROOT / "log.md").write_text("\n".join(lines), encoding="utf-8")


def check_conformance() -> None:
    """OKF conformance: every non-reserved .md has parseable frontmatter with non-empty `type`."""
    reserved = {"index.md", "log.md"}
    fm = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
    bad = []
    for md in ROOT.glob("*.md"):
        if md.name in reserved:
            continue
        m = fm.match(md.read_text(encoding="utf-8"))
        if not m or not re.search(r'^type:\s*\S', m.group(1), re.MULTILINE):
            bad.append(md.name)
    if bad:
        raise SystemExit(f"NON-CONFORMANT (missing/empty type): {bad}")
    print(f"OKF v0.1 conformant: {len(list(ROOT.glob('*.md'))) - len(reserved)} concepts + index.md + log.md")


def main() -> None:
    concepts = write_concepts()
    write_index(concepts)
    write_log()
    check_conformance()
    print(f"Bundle written to {ROOT}")


if __name__ == "__main__":
    main()
