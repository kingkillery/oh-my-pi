"""Headless Colab GPU job: distil a small pairwise verifier (run via the `colab` CLI).

Self-contained — pulls RewardBench (train) + JudgeBench (eval) from the HF Hub, QLoRA-trains
gemma-2-2b, evaluates tuned + baseline on JudgeBench with the swap-and-aggregate protocol, saves the
adapter to /content, and prints the result JSON. No Drive mount, no notebook magics.

Driven from WSL:
    colab new -s vd --gpu T4
    colab install -s vd transformers peft trl bitsandbytes datasets accelerate
    # smoke (sets kernel env, then runs):
    printf "import os;os.environ['VD_MAX_TRAIN']='300';os.environ['VD_EVAL_LIMIT']='50'" | colab exec -s vd
    colab exec -s vd -f distill/colab_job.py
    # full: set both to '0' then exec again
    colab download -s vd /content/distill_adapter ./distill/adapter
    colab stop -s vd

Tunables via kernel env (default 0 = all/full): VD_MAX_TRAIN, VD_EVAL_LIMIT, VD_MODEL.
"""

import json
import os
import re

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # cut fragmentation OOM

import torch
from datasets import Dataset, load_dataset
from peft import LoraConfig, PeftModel, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

MODEL = os.environ.get("VD_MODEL", "unsloth/gemma-2-2b-it")
MAX_TRAIN = int(os.environ.get("VD_MAX_TRAIN", "0"))    # 0 = all (~5970)
EVAL_LIMIT = int(os.environ.get("VD_EVAL_LIMIT", "0"))  # 0 = all 350
EPOCHS, MAX_SEQ = 1, 1024   # seq 1024 keeps gemma-2's 256k-vocab CE loss within T4 memory
Q_CAP, R_CAP = 2500, 3000

JUDGE = ("You are a strict, impartial judge. Read the question and the two candidate responses, then "
         "decide which response is more correct and complete.\n\n"
         "Question:\n{q}\n\n[Response A]\n{a}\n\n[Response B]\n{b}\n\n"
         "Reply with ONLY a single letter — A or B — for the better response.")

STATUS_FILE = "/content/job_status.json"


def _status(**kw):
    try:
        json.dump(kw, open(STATUS_FILE, "w"))
    except Exception:
        pass


def _uc(q, a, b):
    return JUDGE.format(q=q, a=a, b=b)


def _cap(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + " …[truncated]"


def _letter(t):
    m = re.search(r"\b([AB])\b", (t or "").strip().upper())
    return m.group(1) if m else None


def build_data():
    rb = load_dataset("allenai/reward-bench", split="filtered")
    train = []
    for r in rb:
        q, ch, rj = _cap(r["prompt"], Q_CAP), _cap(r["chosen"], R_CAP), _cap(r["rejected"], R_CAP)
        train.append({"q": q, "a": ch, "b": rj, "gold": "A"})
        train.append({"q": q, "a": rj, "b": ch, "gold": "B"})
    if MAX_TRAIN:
        train = train[:MAX_TRAIN]
    jb = load_dataset("ScalerLab/JudgeBench", split="gpt")
    ev = [{"q": _cap(r["question"], Q_CAP), "a": _cap(r["response_A"], R_CAP),
           "b": _cap(r["response_B"], R_CAP), "gold": "A" if r["label"] == "A>B" else "B",
           "source": r.get("source", "")} for r in jb]
    if EVAL_LIMIT:
        ev = ev[:EVAL_LIMIT]
    print(f"[data] train {len(train)} (both orderings) | eval {len(ev)} JudgeBench pairs", flush=True)
    return train, ev


def load_model(adapter=None):
    bf16 = torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16
    tok = AutoTokenizer.from_pretrained(adapter or MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
    m = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb, device_map="auto",
                                             torch_dtype=dtype, attn_implementation="eager")
    if adapter:
        m = PeftModel.from_pretrained(m, adapter)
    return m, tok, bf16


def train(train_rows, tok, bf16):
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=(torch.bfloat16 if bf16 else torch.float16),
                             bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=bnb, device_map="auto",
                                                 torch_dtype=(torch.bfloat16 if bf16 else torch.float16),
                                                 attn_implementation="eager")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    # trl >=1.x: prompt/completion columns + completion_only_loss (DataCollatorForCompletionOnlyLM removed).
    ds = Dataset.from_list([{
        "prompt": tok.apply_chat_template([{"role": "user", "content": _uc(r["q"], r["a"], r["b"])}],
                                          tokenize=False, add_generation_prompt=True),
        "completion": r["gold"]} for r in train_rows])
    cfg = SFTConfig(output_dir="/content/distill_adapter", num_train_epochs=EPOCHS,
                    per_device_train_batch_size=1, gradient_accumulation_steps=16,
                    learning_rate=2e-4, lr_scheduler_type="cosine", warmup_ratio=0.03,
                    max_length=MAX_SEQ, bf16=bf16, fp16=not bf16, optim="paged_adamw_8bit",
                    logging_steps=20, save_strategy="epoch", report_to="none",
                    completion_only_loss=True, gradient_checkpointing=True,
                    gradient_checkpointing_kwargs={"use_reentrant": False})
    tr = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok, peft_config=lora)
    tr.train()
    tr.save_model("/content/distill_adapter")
    tok.save_pretrained("/content/distill_adapter")
    return model


@torch.no_grad()
def _judge(m, tok, q, a, b):
    p = tok.apply_chat_template([{"role": "user", "content": _uc(q, a, b)}], tokenize=False, add_generation_prompt=True)
    ids = tok(p, return_tensors="pt", truncation=True, max_length=4096).to(m.device)
    out = m.generate(**ids, max_new_tokens=4, do_sample=False, pad_token_id=tok.pad_token_id)
    return _letter(tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))


def evaluate(m, tok, rows):
    n = cr = cons = cons_c = agg = 0
    by = {}
    for r in rows:
        g = r["gold"]
        p1 = _judge(m, tok, r["q"], r["a"], r["b"])
        w2 = {"A": "B", "B": "A"}.get(_judge(m, tok, r["q"], r["b"], r["a"]))
        n += 1
        cr += int(p1 == g) + int(w2 == g)
        agree = p1 is not None and p1 == w2
        cons += int(agree)
        cons_c += int(agree and p1 == g)
        agg += int(agree and p1 == g)
        s = r.get("source", "?").split("-")[0]
        by.setdefault(s, [0, 0])
        by[s][0] += 1
        by[s][1] += int(agree and p1 == g)
    return {"n": n, "raw_call_accuracy": round(cr / (2 * n), 4),
            "position_bias_flip_rate": round(1 - cons / n, 4),
            "consistent_accuracy": round(cons_c / cons, 4) if cons else 0.0,
            "aggregate_accuracy": round(agg / n, 4),
            "by_source": {k: round(v[1] / v[0], 4) for k, v in sorted(by.items())}}


def run():
    print(f"[cfg] model={MODEL} max_train={MAX_TRAIN or 'all'} eval_limit={EVAL_LIMIT or 'all'} "
          f"gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}", flush=True)
    _status(status="running", stage="build_data")
    train_rows, eval_rows = build_data()
    _status(status="running", stage="base_eval", n_train=len(train_rows), n_eval=len(eval_rows))
    base, tok, bf16 = load_model()
    base.eval()
    base_res = evaluate(base, tok, eval_rows)
    print("[eval] BASE  :", json.dumps(base_res), flush=True)
    _status(status="running", stage="training", base=base_res)
    del base
    torch.cuda.empty_cache()
    model = train(train_rows, tok, bf16)
    _status(status="running", stage="tuned_eval", base=base_res)
    model.eval()
    tuned_res = evaluate(model, tok, eval_rows)
    print("[eval] TUNED :", json.dumps(tuned_res), flush=True)
    out = {"model": MODEL, "max_train": MAX_TRAIN or len(train_rows), "base": base_res, "tuned": tuned_res,
           "frontier_reference": 0.902, "mock_floor": 0.588}
    with open("/content/eval_result.json", "w") as f:
        json.dump(out, f, indent=2)
    print("[done] RESULT_JSON " + json.dumps(out), flush=True)


# Detach onto the kernel so a dropped `colab exec` stream can't lose the run; poll job_status.json.
import threading
import traceback


def _launch():
    try:
        run()
        _status(status="done")
    except Exception as exc:
        _status(status="error", error=repr(exc)[:400], tb=traceback.format_exc()[-1500:])
        print("[error]", repr(exc), flush=True)


_status(status="starting")
threading.Thread(target=_launch, daemon=True).start()
print("LAUNCHED background job", flush=True)
