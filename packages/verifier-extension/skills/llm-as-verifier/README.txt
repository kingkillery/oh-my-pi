Files in this packet:
- SKILL.md: packet-style operating instructions for llm-as-verifier workflows
- scripts/lav_runner.py: deterministic Python verifier runner
- examples/code-patch-selection.json: bundled Python-runner smoke example
- examples/weighted-ensemble-selection.json: bundled weighted ensemble smoke example
- references/criteria-recipes.md: reusable criteria-writing patterns
- references/research-notes.md: paper-to-implementation notes

Quick start:
1. Install/use the package in Pi.
2. Prefer compare mode over audit mode.
3. Gather tests, logs, diffs, and spec evidence first.
4. Run `/lav-smoke` for the Python path.
5. Run `/lav-ensemble-smoke` for the ensemble path.

If a decision is low-confidence, tighten the criteria and add better evidence before trusting the winner.
