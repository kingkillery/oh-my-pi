"""Generate a self-contained Colab notebook for the verifier distillation.

The notebook needs NO repo files: it pulls RewardBench (train) and JudgeBench (eval) from the HF
Hub, inlines the prompt template + train + eval, runs QLoRA on Colab's GPU (T4 16GB is 2x the local
8GB — bigger batch/seq, or swap in gemma-2-9b), and saves the adapter + results to Drive.

    python distill/make_colab_notebook.py   ->  distill/colab_finetune.ipynb
"""

from __future__ import annotations

import json
from pathlib import Path

MD = "markdown"
CODE = "code"

CELLS: list[tuple[str, str]] = [
    (MD, """# Verifier distillation on Colab — small local pairwise judge

Distil the frontier **swap-and-aggregate verifier** (0.902 on JudgeBench) into a cheap `gemma-2-2b`
via QLoRA. Self-contained: pulls **RewardBench** (train, both orderings) and **JudgeBench** (eval,
held-out) from the HF Hub — no repo files needed.

**Runtime → Change runtime type → GPU (T4 is enough).** Then *Runtime → Run all*.

Go/no-go: a 2B judge is worth shipping at **aggregate_accuracy ≥ 0.82** and **flip_rate ≤ 0.10**
(frontier reference 0.902, mock floor 0.588)."""),

    (CODE, """!nvidia-smi -L
!pip install -q -U "transformers>=4.45" "trl>=0.12" peft bitsandbytes datasets accelerate"""),

    (CODE, """# Config. Default model is an UNGATED gemma-2-2b mirror so this runs with no HF login.
# For the gated original use MODEL = "google/gemma-2-2b-it" and run huggingface_hub.login().
# On an L4/A100 you can swap MODEL = "unsloth/gemma-2-9b-it" for a stronger judge.
MODEL = "unsloth/gemma-2-2b-it"
MAX_TRAIN = 0          # 0 = all ~5970; set e.g. 1500 for a quick run
EPOCHS = 1
MAX_SEQ = 1024         # gemma-2's 256k-vocab CE loss OOMs a T4 at 2048; 1024 fits comfortably"""),

    (CODE, '''# --- Shared pairwise-judge prompt (identical for train + eval) ---
import re

JUDGE_INSTRUCTION = (
    "You are a strict, impartial judge. Read the question and the two candidate responses, then "
    "decide which response is more correct and complete.\\n\\n"
    "Question:\\n{q}\\n\\n[Response A]\\n{a}\\n\\n[Response B]\\n{b}\\n\\n"
    "Reply with ONLY a single letter \\u2014 A or B \\u2014 for the better response."
)
def user_content(q, a, b): return JUDGE_INSTRUCTION.format(q=q, a=a, b=b)
def train_messages(q, a, b, gold):
    return [{"role": "user", "content": user_content(q, a, b)},
            {"role": "assistant", "content": gold}]
def eval_messages(q, a, b): return [{"role": "user", "content": user_content(q, a, b)}]
def parse_letter(t):
    m = re.search(r"\\b([AB])\\b", (t or "").strip().upper()); return m.group(1) if m else None
RESPONSE_TEMPLATE = "<start_of_turn>model\\n"
Q_CAP, R_CAP = 2500, 3000
def cap(s, n): s = (s or "").strip(); return s if len(s) <= n else s[:n] + " \\u2026[truncated]"'''),

    (CODE, '''# --- Build data from the HF Hub (no local files) ---
from datasets import load_dataset

rb = load_dataset("allenai/reward-bench", split="filtered")
train_rows = []
for r in rb:
    q, ch, rj = cap(r["prompt"], Q_CAP), cap(r["chosen"], R_CAP), cap(r["rejected"], R_CAP)
    train_rows.append({"question": q, "response_A": ch, "response_B": rj, "gold": "A"})
    train_rows.append({"question": q, "response_A": rj, "response_B": ch, "gold": "B"})  # both orderings
if MAX_TRAIN:
    train_rows = train_rows[:MAX_TRAIN]

jb = load_dataset("ScalerLab/JudgeBench", split="gpt")
eval_rows = [{"question": cap(r["question"], Q_CAP),
              "response_A": cap(r["response_A"], R_CAP), "response_B": cap(r["response_B"], R_CAP),
              "gold": "A" if r["label"] == "A>B" else "B", "source": r.get("source", "")} for r in jb]
print(f"train {len(train_rows)} (both orderings) | eval {len(eval_rows)} JudgeBench pairs")'''),

    (CODE, '''# --- QLoRA fine-tune ---
import os
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # cut fragmentation OOM
import torch
from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, prepare_model_for_kbit_training
from trl import SFTConfig, SFTTrainer

bf16 = torch.cuda.is_bf16_supported()
dtype = torch.bfloat16 if bf16 else torch.float16   # T4 -> fp16, L4/A100 -> bf16

tok = AutoTokenizer.from_pretrained(MODEL)
if tok.pad_token is None: tok.pad_token = tok.eos_token
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb, device_map="auto",
                                             torch_dtype=dtype, attn_implementation="eager")
model.config.use_cache = False
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                  target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"])

train_ds = Dataset.from_list([{
    "prompt": tok.apply_chat_template([{"role": "user", "content": user_content(r["question"], r["response_A"], r["response_B"])}],
                                      tokenize=False, add_generation_prompt=True),
    "completion": r["gold"]} for r in train_rows])  # trl >=1.x prompt/completion + completion_only_loss
cfg = SFTConfig(output_dir="adapter", num_train_epochs=EPOCHS,
                per_device_train_batch_size=1, gradient_accumulation_steps=16,
                learning_rate=2e-4, lr_scheduler_type="cosine", warmup_ratio=0.03,
                max_length=MAX_SEQ, bf16=bf16, fp16=not bf16, optim="paged_adamw_8bit",
                logging_steps=20, save_strategy="epoch", report_to="none",
                completion_only_loss=True, gradient_checkpointing=True,
                gradient_checkpointing_kwargs={"use_reentrant": False})
trainer = SFTTrainer(model=model, args=cfg, train_dataset=train_ds, processing_class=tok,
                     peft_config=lora)
trainer.train(); trainer.save_model("adapter"); tok.save_pretrained("adapter")
print("adapter saved -> ./adapter")'''),

    (CODE, '''# --- Evaluate on JudgeBench: swap-and-aggregate (both orderings) ---
@torch.no_grad()
def judge(m, q, a, b):
    prompt = tok.apply_chat_template(eval_messages(q, a, b), tokenize=False, add_generation_prompt=True)
    ids = tok(prompt, return_tensors="pt", truncation=True, max_length=4096).to(m.device)
    out = m.generate(**ids, max_new_tokens=4, do_sample=False, pad_token_id=tok.pad_token_id)
    return parse_letter(tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))

def evaluate(m, rows):
    n = cr = cons = cons_c = agg = 0
    by = {}
    for r in rows:
        q, ra, rb, g = r["question"], r["response_A"], r["response_B"], r["gold"]
        p1 = judge(m, q, ra, rb)                       # winner in original A/B space
        w2 = {"A": "B", "B": "A"}.get(judge(m, q, rb, ra))  # swapped back
        n += 1; cr += int(p1 == g) + int(w2 == g)
        agree = p1 is not None and p1 == w2
        if agree: cons += 1; cons_c += int(p1 == g)
        agg += int(agree and p1 == g)
        s = r.get("source", "?").split("-")[0]; by.setdefault(s, [0, 0]); by[s][0]+=1; by[s][1]+=int(agree and p1==g)
    return {"raw_call_accuracy": round(cr/(2*n), 4), "position_bias_flip_rate": round(1-cons/n, 4),
            "consistent_accuracy": round(cons_c/cons, 4) if cons else 0.0,
            "aggregate_accuracy": round(agg/n, 4),
            "by_source": {k: round(v[1]/v[0], 4) for k, v in sorted(by.items())}}

res_tuned = evaluate(model, eval_rows)
print("TUNED gemma verifier:", res_tuned)
print("frontier reference: aggregate 0.902 | mock floor 0.588")'''),

    (CODE, '''# --- (optional) Baseline: the untuned base model, to measure the lift from fine-tuning ---
base = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb, device_map="auto",
                                            torch_dtype=dtype, attn_implementation="eager").eval()
print("BASE (untuned):", evaluate(base, eval_rows))
del base; torch.cuda.empty_cache()'''),

    (CODE, '''# --- Save adapter + results to Google Drive ---
import json, shutil
from google.colab import drive
drive.mount("/content/drive")
dst = "/content/drive/MyDrive/pi-llm-verifier-distill"
import os; os.makedirs(dst, exist_ok=True)
shutil.make_archive(f"{dst}/gemma2-2b-judge-adapter", "zip", "adapter")
json.dump({"model": MODEL, "tuned": res_tuned}, open(f"{dst}/eval_result.json", "w"), indent=2)
print("saved adapter zip + eval_result.json ->", dst)'''),

    (MD, """## Interpreting results

- **aggregate_accuracy** is the headline (swap-and-aggregate, decisive only when both orderings agree) —
  compare to the frontier verifier's **0.902** and the **0.588** mock floor.
- **position_bias_flip_rate** is the order-robustness; lower is better. Watch the BASE vs TUNED gap —
  fine-tuning on both orderings should cut it sharply.
- **by_source** breaks accuracy out by JudgeBench source (mmlu / livebench / livecodebench).

If the tuned 2B clears **≥0.82 aggregate / ≤0.10 flip**, it is shippable as a cheap first-pass judge with
hard cases escalated to the frontier verifier. If not, the honest read is that pairwise judging at this
difficulty needs a larger student (try `unsloth/gemma-2-9b-it` on an L4/A100) — itself a useful result."""),
]


def main() -> None:
    cells = []
    for ctype, src in CELLS:
        cell = {"cell_type": ctype, "metadata": {}, "source": src.splitlines(keepends=True)}
        if ctype == CODE:
            cell["outputs"] = []
            cell["execution_count"] = None
        cells.append(cell)
    nb = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4, "nbformat_minor": 0,
    }
    out = Path(__file__).resolve().parent / "colab_finetune.ipynb"
    out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
