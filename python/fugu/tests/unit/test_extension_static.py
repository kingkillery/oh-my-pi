from pathlib import Path

SOURCE = Path(".pi/extensions/llm-as-verifier/index.ts").read_text(encoding="utf-8")


def test_extension_compare_prompt_requires_evidence_tags_before_scores():
    assert "Before assigning any score, list exactly 3 evidence observations" in SOURCE
    assert SOURCE.index("<evidence_A>1. ... 2. ... 3. ...</evidence_A>") < SOURCE.index("<score_A>LETTER_A_TO_T</score_A>")
    assert SOURCE.index("<evidence_B>1. ... 2. ... 3. ...</evidence_B>") < SOURCE.index("<score_B>LETTER_A_TO_T</score_B>")


def test_extension_audit_prompt_requires_evidence_tag_before_score():
    assert SOURCE.index("<evidence>1. ... 2. ... 3. ...</evidence>") < SOURCE.index("<score>LETTER_A_TO_T</score>")


def test_extension_swap_and_vote_margin_contract_present():
    assert 'order: "original" | "swapped"' in SOURCE
    assert "canonical_score_a" in SOURCE
    assert "canonical_score_b" in SOURCE
    assert "swap_consistency" in SOURCE
    assert "vote_margin" in SOURCE
    assert "Math.max(5, resolvedModels.length)" in SOURCE
    assert 'backend === "pi-model-ensemble" ? Math.max(5, resolvedModels.length) : 5' in SOURCE
    assert "Swap consistency:" in SOURCE
