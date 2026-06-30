"""benchmarkie2: does RQGM improvement continue over multiple iterations?

Three facets:
  1. Within-run scaling  - same benchmark at growing budgets; does best-belief /
     balanced-utility / best-quality keep rising?
  2. Saturation -> harder benchmark - if the default mock saturates (quality
     clamps at 1.0, reviewer lineage caps at rev_e2), build a harder mock
     (8 coder tasks, slow quality drift, 7-level reviewer lineage, eps=0.025)
     and show improvement continues longer.
  3. Iterative co-evolution cycles - re-seed each run from the previous best
     workspace; does improvement COMPOUND across cycles?

All offline/deterministic (mock providers). One process, no /tmp dependency.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path

from rqgm.archive import Archive, ArchiveNode, UtilityRecord
from rqgm.beta import best_belief
from rqgm.mock_providers import MockEvaluatorSlotProvider, MockWorkspaceProvider
from rqgm.providers import EvaluatorCandidate, RoleSpec
from rqgm.search import RQGMConfig, RQGMSearch

OUT = Path(__file__).resolve().parent.parent.parent / "runs" / "rqgm_bench2"



def _stable_rng(*parts: object) -> random.Random:
    key = ":".join(str(p) for p in parts)
    digest = hashlib.sha256(key.encode("utf-8")).digest()[:8]
    return random.Random(int.from_bytes(digest, "big"))


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- harder mock
H_NEXT = {
    "rev_e0": "rev_e1", "rev_e1": "rev_e2", "rev_e2": "rev_e3", "rev_e3": "rev_e4",
    "rev_e4": "rev_e5", "rev_e5": "rev_e6", "rev_e6": "rev_e6",
}
H_STRICT = {f"rev_e{i}": round(0.30 + 0.05 * i, 2) for i in range(7)}
H_ANCHOR = {
    "rev_e0": (6, 4), "rev_e1": (7, 3), "rev_e2": (7, 2), "rev_e3": (8, 2),
    "rev_e4": (8, 1), "rev_e5": (9, 1), "rev_e6": (10, 0),
}


class HarderMockWorkspace:
    """8 coder tasks, slow quality drift (mean +0.01/expansion), 7 reviewer levels."""

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    def roles(self) -> list[RoleSpec]:
        return [
            RoleSpec("coder", "evaluator_independent", [f"t{i}" for i in range(8)]),
            RoleSpec("reviewer", "evaluator_dependent", ["r0", "r1"], slot=0),
        ]

    def seed(self) -> dict:
        return {"quality": 0.5, "reviewer_prompt_id": "rev_e0"}

    def expand(self, parent: ArchiveNode) -> dict | None:
        rng = _stable_rng(self._seed, parent.node_id, "expand")
        if rng.random() < 0.1:
            return None
        q = _clamp(parent.workspace.get("quality", 0.5) + rng.uniform(-0.04, 0.06))
        pid = parent.workspace.get("reviewer_prompt_id", "rev_e0")
        if rng.random() < 0.4:
            pid = H_NEXT[pid]
        return {"quality": q, "reviewer_prompt_id": pid}

    def evaluate(self, node, role, task, evaluator) -> int:
        q = node.workspace.get("quality", 0.5)
        p = q
        eid = "none"
        if evaluator is not None:
            eid = evaluator.evaluator_id
            p -= evaluator.state.get("strictness", 0.0) * 0.3
        rng = _stable_rng(self._seed, node.node_id, role.name, task, eid)
        return int(rng.random() < _clamp(p))


class HarderMockSlot:
    def __init__(self, slot: int = 0) -> None:
        self.slot = slot

    def incumbent(self) -> EvaluatorCandidate:
        return EvaluatorCandidate("rev_e0", {"strictness": H_STRICT["rev_e0"]})

    def challengers(self, archive: Archive) -> list[EvaluatorCandidate]:
        found: set[str] = set()
        for n in archive.nodes.values():
            pid = n.workspace.get("reviewer_prompt_id")
            if pid and pid != "rev_e0":
                found.add(pid)
        return [EvaluatorCandidate(p, {"strictness": H_STRICT.get(p, 0.5)}) for p in sorted(found)]

    def anchor_outcomes(self, ev: EvaluatorCandidate) -> tuple[int, int]:
        return H_ANCHOR.get(ev.evaluator_id, (0, 0))


# ----------------------------------------------------------------- helpers
def _run(workspace, slots, budget, epsilon, seed, seed_ws=None):
    slots = slots if isinstance(slots, dict) else {0: slots}
    archive = Archive()
    if seed_ws is not None:
        archive.add_node(ArchiveNode("node_0000", None, workspace=dict(seed_ws)))
    cfg = RQGMConfig(budget=budget, epsilon=epsilon, seed=seed)
    search = RQGMSearch(workspace, slots, cfg, archive=archive)
    result = search.run()
    return result, search


def _role_passrate(search, node_id, role, current_epoch):
    s = f = 0
    for rec in search.archive.records:
        if rec.node_id != node_id or rec.role != role:
            continue
        if not search.archive._valid(rec, current_epoch):
            continue
        if rec.outcome == 1:
            s += 1
        else:
            f += 1
    return (s / (s + f)) if (s + f) else float("nan")


def _current_reviewer(result, incumbent_id="rev_e0"):
    """Final frozen reviewer id after all replacements (slot 0)."""
    cur = incumbent_id
    for rep in result.replacements:
        cur = rep.to_id
    return cur


def summarize(result, search, ws_roles, epsilon, baseline_util):
    best = result.best_node_id
    ce = {0: _current_reviewer(result)}
    node = search.archive.nodes[best]
    qual = node.workspace.get("quality", float("nan"))
    pid = node.workspace.get("reviewer_prompt_id")
    coder = _role_passrate(search, best, "coder", ce)
    rev = _role_passrate(search, best, "reviewer", ce)
    return {
        "budget": result.num_evaluations,
        "best_node": best,
        "best_quality": round(qual, 4),
        "reviewer_prompt": pid,
        "best_belief": round(result.best_belief, 4),
        "balanced_utility": round(result.balanced_utility, 4),
        "delta_vs_seed": round(result.balanced_utility - baseline_util, 4),
        "self_improved": result.balanced_utility > baseline_util,
        "coder_passrate": round(coder, 4) if coder == coder else None,
        "reviewer_passrate": round(rev, 4) if rev == rev else None,
        "archive_size": result.archive_size,
        "expansions": result.num_expansions,
        "replacements": len(result.replacements),
        "max_epoch": max(result.epochs.values()) if result.epochs else 0,
    }


def baseline_utility(workspace, slots, epsilon):
    """Evaluate the seed node once per (role,task) cell under epoch 1 (rev_e0)."""
    slots = slots if isinstance(slots, dict) else {0: slots}
    archive = Archive()
    archive.add_node(ArchiveNode("node_0000", None, workspace=dict(workspace.seed())))
    incumbent = slots[0].incumbent()
    ce = {0: incumbent.evaluator_id}
    for role in workspace.roles():
        for task in role.tasks:
            ev = incumbent if role.kind == "evaluator_dependent" else None
            outcome = workspace.evaluate(archive.nodes["node_0000"], role, task, ev)
            archive.add_record(UtilityRecord(
                node_id="node_0000", role=role.name, task=task, outcome=outcome,
                dep=(0,) if ev is not None else (),
                criterion_tags={0: incumbent.evaluator_id} if ev is not None else {},
                epoch_vector=(1,),
            ))
    return archive.balanced_utility("node_0000", [r.name for r in workspace.roles()], ce)


# ----------------------------------------------------------------- phases
def phase_scaling(name, ws_factory, slot_factory, budgets, epsilon, label):
    print(f"\n{'='*92}\n{label}\n{'='*92}")
    ws0, sl0 = ws_factory(), slot_factory()
    base = baseline_utility(ws0, sl0, epsilon)
    print(f"seed balanced_utility (epoch 1) = {base:.4f}   epsilon={epsilon}")
    hdr = f"{'budget':>7} {'best_q':>7} {'rev':>6} {'bestBB':>8} {'balU':>7} {'dSeed':>7} {'imp?':>5} {'code%':>6} {'rev%':>6} {'repl':>5} {'epoch':>6}"
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for b in budgets:
        ws, sl = ws_factory(), slot_factory()
        result, search = _run(ws, sl, b, epsilon, seed=0)
        # track replacements on search for _frozen
        search._last_replacements = result.replacements
        row = summarize(result, search, ws.roles(), epsilon, base)
        rows.append(row)
        imp = "Y" if row["self_improved"] else "."
        print(f"{row['budget']:>7} {row['best_quality']:>7} {row['reviewer_prompt']:>6} "
              f"{row['best_belief']:>8} {row['balanced_utility']:>7} {row['delta_vs_seed']:>+7} "
              f"{imp:>5} {(row['coder_passrate'] or 0)*100:>5.0f}% {(row['reviewer_passrate'] or 0)*100:>5.0f}% "
              f"{row['replacements']:>5} {row['max_epoch']:>6}")
    return {"baseline_utility": base, "epsilon": epsilon, "rows": rows}


def phase_cycles(name, ws_factory, slot_factory, budget, epsilon, k):
    print(f"\n{'='*92}\nITERATIVE CO-EVOLUTION CYCLES (harder mock): re-seed run k with run k-1's best workspace\n{'='*92}")
    ws0, sl0 = ws_factory(), slot_factory()
    seed_ws = ws0.seed()
    print(f"cycle seed: quality={seed_ws['quality']:.3f} reviewer={seed_ws['reviewer_prompt_id']}")
    hdr = f"{'cycle':>5} {'best_q':>7} {'rev':>6} {'bestBB':>8} {'balU':>7} {'repl':>5} {'epoch':>6} {'dQual':>7}"
    print(hdr)
    print("-" * len(hdr))
    rows = []
    prev_q = seed_ws["quality"]
    for c in range(1, k + 1):
        ws, sl = ws_factory(), slot_factory()
        result, search = _run(ws, sl, budget, epsilon, seed=c, seed_ws=seed_ws)
        best = result.best_node_id
        node = search.archive.nodes[best]
        seed_ws = dict(node.workspace)  # re-seed next cycle with best workspace
        dq = round(seed_ws["quality"] - prev_q, 4)
        prev_q = seed_ws["quality"]
        row = {
            "cycle": c, "best_node": best, "best_quality": round(seed_ws["quality"], 4),
            "reviewer_prompt": seed_ws.get("reviewer_prompt_id"),
            "best_belief": round(result.best_belief, 4),
            "balanced_utility": round(result.balanced_utility, 4),
            "replacements": len(result.replacements), "max_epoch": max(result.epochs.values()),
            "delta_quality": dq,
        }
        rows.append(row)
        print(f"{row['cycle']:>5} {row['best_quality']:>7} {row['reviewer_prompt']:>6} "
              f"{row['best_belief']:>8} {row['balanced_utility']:>7} {row['replacements']:>5} "
              f"{row['max_epoch']:>6} {row['delta_quality']:>+7}")
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    budgets = [8, 16, 32, 64, 128, 256, 512, 1024, 2048]

    # Phase 1: DEFAULT mock (epsilon 0.05) - is it saturated?
    default = phase_scaling(
        "default_mock", lambda: MockWorkspaceProvider(0), lambda: MockEvaluatorSlotProvider(0),
        budgets, epsilon=0.05,
        label="PHASE 1 - DEFAULT MOCK (2 coder tasks beyond t0..t3 actually 4; 3-level reviewer rev_e0/e1/e2; eps=0.05)",
    )

    # Phase 2: HARDER mock - more tasks, slow drift, 7-level reviewer, tighter eps
    harder = phase_scaling(
        "harder_mock", lambda: HarderMockWorkspace(0), lambda: HarderMockSlot(0),
        budgets, epsilon=0.025,
        label="PHASE 2 - HARDER MOCK (8 coder tasks; slow drift mean+0.01; 7-level reviewer; eps=0.025)",
    )

    # Phase 3: iterative co-evolution cycles on harder mock
    cycles = phase_cycles(
        "cycles_harder", lambda: HarderMockWorkspace(0), lambda: HarderMockSlot(0),
        budget=64, epsilon=0.025, k=8,
    )

    report = {
        "elapsed_sec": round(time.time() - t0, 2),
        "default_mock": default,
        "harder_mock": harder,
        "iterative_cycles_harder": cycles,
    }
    (OUT / "iterations_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[report written] {OUT / 'iterations_report.json'}  ({report['elapsed_sec']}s)")


if __name__ == "__main__":
    main()
