"""The fusion Q&A recommendation engine encodes the repo's law — pin the key branches."""

from harness.cli.fusion_qa import load_spec, recommend

SPEC = load_spec()


def _rec(**answers):
    return recommend(answers, SPEC)


def test_agentic_with_outcome_fuses_by_selection():
    r = _rec(regime="agentic", signal="ground_truth", diversity="high", priority="quality")
    assert r["id"] == "agentic-outcome-select"
    assert r["config"]["mode"] == "fuse-select"
    assert "kimi/kimi-k2.6" in r["config"]["lanes"]           # resolved to concrete models
    assert r["config"]["gate"] == 0.60
    assert "critique-revise" in r["config"]["avoid"]


def test_code_with_tests_selects():
    r = _rec(regime="code", signal="ground_truth", diversity="high")
    assert r["id"] == "code-test-select"
    assert "kimi/kimi-for-coding" in r["config"]["lanes"]


def test_open_checklist_high_diversity_synthesizes():
    r = _rec(regime="open", signal="checklist", diversity="high")
    assert r["id"] == "open-complementary-synth"
    assert r["config"]["synthesizer"] == "cx/gpt-5.5"


def test_mc_routes_does_not_fuse():
    r = _rec(regime="mc", signal="ground_truth", diversity="high")
    assert r["id"] == "mc-route"
    assert r["config"]["mode"] == "route"


def test_subjective_signal_cautions_first():
    # subjective short-circuits regardless of regime — fusion 'wins' would be judge-bias.
    r = _rec(regime="agentic", signal="subjective", diversity="high")
    assert r["id"] == "subjective-caution"


def test_low_diversity_blocks_fusion_even_when_agentic():
    # correlated lanes => no headroom => don't fuse, beats the agentic rule.
    r = _rec(regime="agentic", signal="ground_truth", diversity="low")
    assert r["id"] == "low-diversity-note"
    assert r["config"]["mode"] == "single"


def test_empty_answers_fall_back_to_single():
    assert _rec()["id"] == "fallback"


def test_cost_profile_merged_into_fuse_recommendation():
    r = _rec(regime="agentic", signal="ground_truth", diversity="high", priority="cost")
    cc = r["config"]["cost_controls"]
    assert cc["n_lanes"] == 2 and cc["workers"] == 4 and cc["budget_usd"] == 2


def test_quality_profile_uses_all_lanes_no_cap():
    r = _rec(regime="agentic", signal="ground_truth", diversity="high", priority="quality")
    cc = r["config"]["cost_controls"]
    assert cc["n_lanes"] == 0 and cc["budget_usd"] == 0   # 0 = all lanes / no cap


def test_route_and_single_modes_get_no_cost_controls():
    # cost knobs only attach to fuse modes; routing the best lane has no pool/budget to dial.
    assert "cost_controls" not in _rec(regime="mc", signal="ground_truth", priority="cost")["config"]
    assert "cost_controls" not in _rec(signal="subjective", priority="cost")["config"]


def test_every_rule_config_resolves_to_strings_or_lists():
    # no unresolved model-pool reference should leak through (all configs are concrete).
    for combo in [{"signal": "subjective"}, {"diversity": "low"}, {"regime": "agentic"},
                  {"regime": "code"}, {"regime": "open"}, {"regime": "mc"}, {}]:
        cfg = recommend(combo, SPEC)["config"]
        for v in cfg.values():
            assert isinstance(v, (str, int, float, bool, list))
