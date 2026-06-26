# Verifier distillation — small pairwise judge

Distil the frontier **swap-and-aggregate verifier** (0.902 on JudgeBench) into a cheap `gemma-2-2b`
via QLoRA, so pairwise judging can run without a frontier API call.

- **Train:** RewardBench (`allenai/reward-bench`, filtered) — high-quality (chosen, rejected) pairs,
  emitted in **both orderings** so the student learns order-invariance. ~5,970 examples.
- **Eval:** the **JudgeBench** 350-pair held-out set (`ScalerLab/JudgeBench`, `gpt` split — no leakage
  with RewardBench). Judged in both orderings; we report raw per-call accuracy, **position-bias flip
  rate**, and the swap-consistent **aggregate accuracy** — directly comparable to the frontier 0.902.

## Path A — Colab (recommended: less compute-constrained)

Colab's T4 (16 GB) is 2× the typical local 8 GB, so bigger batch/seq — and an L4/A100 fits
`gemma-2-9b`. The notebook is **self-contained** (pulls both datasets from the HF Hub, no repo files):

**→ [Open `distill/colab_finetune.ipynb` in Colab](https://colab.research.google.com/github/kingkillery/pi-llm-as-verifier/blob/main/distill/colab_finetune.ipynb)** — set Runtime → GPU, then Run all.

It installs deps, builds the both-orderings data, QLoRA-trains, evaluates on JudgeBench (tuned **and**
untuned baseline), and saves the adapter + `eval_result.json` to Google Drive. Regenerate the notebook
after editing the cell sources with `python distill/make_colab_notebook.py`.

*(CLI option: `pip install colab-cli` can push/open the notebook from a terminal, but it needs Google
Drive API OAuth credentials; the GitHub→Colab link above is the zero-setup path.)*

## Path B — Local GPU (fallback)

```bash
python distill/build_data.py                                   # 1) build data (CPU)
# 2) the CPU torch build cannot train — install a CUDA wheel matching `nvidia-smi` (cu121/cu124/cu128).
#    NOTE: pip treats plain `torch` as already-satisfied, so FORCE the swap:
pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu128 torch
python distill/eval_verifier.py --out distill/eval_base.json   # 3) baseline floor
python distill/train_qlora.py                                  # 4) QLoRA (~15-20 min on 8GB)
python distill/eval_verifier.py --adapter distill/adapter --out distill/eval_tuned.json   # 5) eval
```

If `google/gemma-2-2b-it` is gated for your HF token, pass an ungated mirror to both train/eval:
`--model unsloth/gemma-2-2b-it` (the Colab notebook already defaults to it).

## Path C — Colab CLI (headless)

`colab_job.py` + `_run_full.sh` + `_poll.py` drive the whole thing on a Colab GPU **headlessly** via the
`colab` CLI (provision → install → launch **detached on the kernel** → poll `job_status.json` → fetch the
adapter → stop):

```bash
bash distill/_run_full.sh          # from WSL/Linux with the `colab` CLI installed + authenticated
```

The job detaches training onto the kernel and writes `/content/job_status.json`, so a dropped `colab exec`
stream can't lose the run. **Validated end-to-end** at smoke scale (base eval + training loop, no OOM at
batch 1 / seq 1024).

**Keep-alive caveat (the one to watch):** the CLI's keep-alive daemon calls `colab.pa.googleapis.com`,
which needs ADC auth carrying the `cloud-platform` **and** `colaboratory` scopes **and**
`roles/serviceusage.serviceUsageConsumer` on the ADC quota project. If `colab log` shows
`KEEP: stopped reason=consecutive_4xx_errors` (a 403 naming a quota project), the VM is reclaimed mid-run.
Fix the ADC quota project / IAM (`gcloud auth application-default login --scopes=…` *and*
`gcloud auth application-default set-quota-project <a-project-you-own>`), or just use **Path A** — the
in-browser notebook is kept alive by the browser tab and needs none of this.

## Metrics (`eval_verifier.py`)

- **raw_call_accuracy** — fraction of single judgements (over both orderings) that match gold.
- **position_bias_flip_rate** — fraction of pairs where the two orderings disagree on the winner (lower is better).
- **consistent_accuracy** — accuracy on order-consistent pairs.
- **aggregate_accuracy** — swap-and-aggregate verdict (decisive only on agreement); the headline number.

## Go / no-go

A 2-billion-parameter judge is worth shipping if it clears a useful bar on JudgeBench — target
**aggregate_accuracy ≥ 0.82** and **flip_rate ≤ 0.10**, with hard cases escalated to the frontier
verifier. The frontier reference is 0.902 (mock floor 0.588). Results are written to
`distill/eval_*.json` (gitignored); the curve/verdict is distilled into the OKF knowledge bundle.

> Adapters, datasets, and `eval_*.json` are gitignored — reproducible from the scripts here.
