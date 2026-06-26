"""Verifier selection strategies for agentic fusion (real 9router calls).

A small toolkit of reputation-blind ways to RANK lane trajectories best-first, plus two scoring
primitives the rankers lean on. All strategies label candidates by letter (A/B/C) so the verifier
never sees model identities, and reuse the transcript/db_diff semantics from tau_fusion.

  * genrm_score  — generative-RM style: sample a YES/NO completion k times, return the YES fraction.
  * aspect_scores — one structured JSON call returning per-aspect [0,1] scores from the DB diff.
  * rank_candidates — order lanes best-first under a chosen strategy (transcript|env_aware|
                      diff_primary|aspect|genrm).

Library only (no CLI); import these from a driver (e.g. tau_fusion) to swap selection logic.
"""

from __future__ import annotations

import json
import os
import re

_KEY = os.environ.get("NINEROUTER_API_KEY") or os.environ.get("9ROUTER_API_KEY") or "local-9router"
os.environ.setdefault("OPENAI_API_KEY", _KEY)
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:20128/v1")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:20128/v1")
# Reads transcript/db_diff straight from the cache records — no tau_fusion import (avoids a cycle).

# --------------------------------------------------------------------------------------------------
# Scoring primitives
# --------------------------------------------------------------------------------------------------

_YES = re.compile(r"\byes\b", re.IGNORECASE)
_NO = re.compile(r"\bno\b", re.IGNORECASE)


def _parse_yes_no(txt: str) -> float | None:
    """Robustly map a free-text verdict to 1.0 (yes) / 0.0 (no) / None (undecidable)."""
    if not txt:
        return None
    head = txt.strip()[:200]
    y, n = _YES.search(head), _NO.search(head)
    if y and not n:
        return 1.0
    if n and not y:
        return 0.0
    if y and n:  # both present — trust whichever appears first
        return 1.0 if y.start() < n.start() else 0.0
    return None


def genrm_score(client, model: str, system: str, user: str, k: int = 4) -> float:
    """Generative-RM score: sample the verifier k times on a YES/NO question, return the YES fraction.

    Sampling at temperature>0 turns a single binary judge into a calibrated [0,1] confidence — the
    fraction of completions that answer YES. Undecidable completions are dropped from the denominator;
    if every sample is undecidable the score is 0.0.
    """
    yes = 0.0
    counted = 0
    for _ in range(max(1, k)):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.7, max_tokens=200)
            v = _parse_yes_no(r.choices[0].message.content or "")
        except Exception:
            v = None
        if v is not None:
            yes += v
            counted += 1
    return round(yes / counted, 4) if counted else 0.0


_ASPECT_SYS = (
    "You are a strict, reputation-blind auditor of a customer-service AI agent's effect on the database. "
    "Given the company POLICY, the user's GOAL, and the agent's RESULTING DATABASE CHANGES, score three "
    "aspects, each a float in [0,1] (1 = fully satisfied, 0 = clearly violated):\n"
    "  write_set_ok  — the changes match what completing the GOAL requires (right records, right fields).\n"
    "  no_destructive — no unnecessary or unrequested destructive edits (wrong removals/overwrites).\n"
    "  policy_ok     — the changes are consistent with the POLICY.\n"
    'Reply ONLY with JSON: {"write_set_ok": <f>, "no_destructive": <f>, "policy_ok": <f>}.')

_ASPECTS = ("write_set_ok", "no_destructive", "policy_ok")


def _clip01(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def aspect_scores(client, model: str, wiki: str, goal: str, db_diff: str) -> dict[str, float]:
    """One structured JSON call scoring the agent's DB changes on three aspects, each in [0,1].

    Returns {"write_set_ok", "no_destructive", "policy_ok"}; missing/parse failures default to 0.0.
    """
    user = (f"POLICY:\n{wiki[:4000]}\n\nGOAL:\n{goal}\n\nRESULTING DATABASE CHANGES:\n{db_diff}\n\n"
            f"Score write_set_ok, no_destructive, policy_ok in [0,1] as JSON.")
    out = {a: 0.0 for a in _ASPECTS}
    try:
        r = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": _ASPECT_SYS},
                                    {"role": "user", "content": user}],
            temperature=0.0, max_tokens=200)
        txt = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        for a in _ASPECTS:
            if a in data:
                out[a] = _clip01(data[a])
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------------------------------
# Ranking strategies
# --------------------------------------------------------------------------------------------------

_RANK_SYS = (
    "You are a strict, reputation-blind verifier of customer-service AI agents. You are given the company "
    "POLICY, the user's GOAL, and several agents' attempts (labeled by letter). Rank the agents from best "
    "to worst by how correctly and completely they fulfilled the GOAL while following the POLICY — judge "
    "the actions taken and their effect, not style or verbosity. Reply ONLY with JSON: "
    '{"ranking": ["<letter>", ...], "reason": "<one line>"}, best first, every letter listed once.')

_GENRM_SYS = (
    "You are a strict, reputation-blind verifier of a customer-service AI agent. Given the company POLICY, "
    "the user's GOAL, and ONE agent's attempt, decide whether the agent correctly and completely fulfilled "
    "the GOAL while following the POLICY. Answer ONLY 'YES' or 'NO'.")


def _candidate_view(recs: dict, mode: str) -> dict[str, str]:
    """Per-lane text block shown to the verifier under `mode` (transcript and/or db_diff)."""
    view: dict[str, str] = {}
    for lane, r in recs.items():
        tx = r.get("transcript", "(no actions)")
        diff = r.get("db_diff", "(n/a)")
        if mode == "transcript":
            view[lane] = tx
        elif mode == "diff_primary":
            view[lane] = (f"RESULTING DATABASE CHANGES:\n{diff}\n\nACTIONS (secondary):\n{tx}")
        else:  # env_aware (default holistic view)
            view[lane] = (f"{tx}\n\nRESULTING DATABASE CHANGES (this agent's net effect):\n{diff}")
    return view


def _holistic_ranking(client, model: str, wiki: str, goal: str, view: dict[str, str]) -> list[str]:
    """Ask the verifier for a best-first ranking of lettered candidates; return lanes best-first."""
    lanes = list(view.keys())
    letters = [chr(ord("A") + i) for i in range(len(lanes))]
    l2lane = {letters[i]: lanes[i] for i in range(len(lanes))}
    blocks = "\n\n".join(f"[Agent {letters[i]}]\n{view[lanes[i]]}" for i in range(len(lanes)))
    user = (f"POLICY:\n{wiki[:4000]}\n\nGOAL:\n{goal}\n\nAGENT ATTEMPTS:\n{blocks}\n\n"
            f"Rank {', '.join(letters)} best to worst.")
    ranked_letters: list[str] = []
    try:
        r = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": _RANK_SYS},
                                    {"role": "user", "content": user}],
            temperature=0.0, max_tokens=300)
        txt = r.choices[0].message.content or ""
        m = re.search(r'"ranking"\s*:\s*\[([^\]]*)\]', txt)
        seq = re.findall(r"[A-Z]", m.group(1)) if m else re.findall(r"\b([A-Z])\b", txt)
        for lt in seq:
            if lt in l2lane and lt not in ranked_letters:
                ranked_letters.append(lt)
    except Exception:
        pass
    ranked = [l2lane[lt] for lt in ranked_letters]
    ranked += [m for m in lanes if m not in ranked]  # append any omitted lanes in base order
    return ranked


def rank_candidates(client, model: str, wiki: str, goal: str, recs: dict, mode: str = "env_aware") -> list[str]:
    """Rank lanes best-first under `mode`, reputation-blind (candidates labeled A/B/C internally).

    Modes:
      transcript   — holistic ranking from action transcripts only.
      env_aware    — holistic ranking from transcript + resulting DB changes (default).
      diff_primary — per-aspect scores on the DB diff are primary; holistic env_aware breaks ties.
      aspect       — rank purely by mean per-aspect score on the DB diff.
      genrm        — rank by sampled YES fraction (generative-RM) over each lane's env-aware attempt.
    """
    lanes = list(recs.keys())
    if not lanes:
        return []

    if mode in ("transcript", "env_aware"):
        return _holistic_ranking(client, model, wiki, goal, _candidate_view(recs, mode))

    if mode == "aspect":
        scored = {m: _mean_aspect(aspect_scores(client, model, wiki, goal, recs[m].get("db_diff", "(n/a)")))
                  for m in lanes}
        return sorted(lanes, key=lambda m: (-scored[m], lanes.index(m)))

    if mode == "diff_primary":
        scored = {m: _mean_aspect(aspect_scores(client, model, wiki, goal, recs[m].get("db_diff", "(n/a)")))
                  for m in lanes}
        holistic = _holistic_ranking(client, model, wiki, goal, _candidate_view(recs, "env_aware"))
        rank_of = {m: i for i, m in enumerate(holistic)}  # holistic order = tie-breaker
        return sorted(lanes, key=lambda m: (-scored[m], rank_of.get(m, len(lanes))))

    if mode == "genrm":
        view = _candidate_view(recs, "env_aware")
        scored = {}
        for m in lanes:
            user = (f"POLICY:\n{wiki[:4000]}\n\nGOAL:\n{goal}\n\nAGENT ATTEMPT:\n{view[m]}\n\n"
                    f"Did this agent correctly and completely fulfill the goal per policy? Answer YES or NO.")
            scored[m] = genrm_score(client, model, _GENRM_SYS, user, k=4)
        return sorted(lanes, key=lambda m: (-scored[m], lanes.index(m)))

    raise ValueError(f"unknown mode: {mode!r}")


def _mean_aspect(scores: dict[str, float]) -> float:
    return round(sum(scores.get(a, 0.0) for a in _ASPECTS) / len(_ASPECTS), 4)
