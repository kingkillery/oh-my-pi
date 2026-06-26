# Pro-model prompts

Ten self-contained, high-rigor prompts for a top-tier reasoning model (e.g. **GPT-5.5 Pro**), each
targeting an open question from the fusion/verifier investigation. Paste one into the model and let it
work.

## Desktop Commander file-reader

Each prompt has a **"Files to read (Desktop Commander)"** section listing **absolute Windows paths** into
this repo (root: `C:\dev\Desktop-Projects\pi-llm-as-verifier`). Run the pro model with the
[Desktop Commander](https://github.com/wonderwhy-er/DesktopCommanderMCP) MCP server enabled so it can
`read_file` those paths and reason from the real source/results rather than the embedded summary. The
result JSONs (`evals/thesis/*.json`) are gitignored run outputs that exist locally; regenerate them with
the scripts in `evals/thesis/` if missing.

## Index

| # | File | Focus |
|---|---|---|
| 1 | `prompt-for-pro1.md` | Adversarial audit of the fusion verdict |
| 2 | `prompt-for-pro2.md` | Judge-bias gap experiment design |
| 3 | `prompt-for-pro3.md` | Formal model of when fusion beats the best lane |
| 4 | `prompt-for-pro4.md` | Gemma verifier distillation (QLoRA) spec |
| 5 | `prompt-for-pro5.md` | Routing vs fusion at matched compute |
| 6 | `prompt-for-pro6.md` | Push the swap-and-aggregate verifier past 0.902 |
| 7 | `prompt-for-pro7.md` | Steelman the pro-fusion case (red-team) |
| 8 | `prompt-for-pro8.md` | Optimize the synthesizer system prompt |
| 9 | `prompt-for-pro9.md` | Predict & interpret the lane-strength sweep |
| 10 | `prompt-for-pro10.md` | Highest-value next contribution |
