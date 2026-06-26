"""QLoRA fine-tune a small Gemma into a pairwise verifier (distillation target: our 0.902 judge).

Loads Gemma-2-2b in 4-bit (nf4) and trains LoRA adapters on the RewardBench pairwise data
(both orderings) with completion-only loss on the single-letter verdict. Sized for an 8GB GPU.

    python distill/train_qlora.py                       # defaults: gemma-2-2b-it, 1 epoch
    python distill/train_qlora.py --max-examples 400     # quick smoke

If `google/gemma-2-2b-it` is gated for your HF token, pass an ungated mirror, e.g.
    --model unsloth/gemma-2-2b-it
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

from prompt_template import user_content

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/gemma-2-2b-it")
    ap.add_argument("--data", default=str(HERE / "data" / "train.jsonl"))
    ap.add_argument("--out", default=str(HERE / "adapter"))
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--max-seq", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-examples", type=int, default=0, help="0 = use all")
    args = ap.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA not available — install the CUDA build of torch first "
                         "(see distill/README.md). Training on CPU is infeasible.")

    tok = AutoTokenizer.from_pretrained(args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb, device_map="auto",
        torch_dtype=torch.bfloat16, attn_implementation="eager")  # gemma-2 sliding-window prefers eager
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])

    ds = load_dataset("json", data_files=args.data, split="train")
    if args.max_examples:
        ds = ds.select(range(min(args.max_examples, len(ds))))

    def to_pc(r: dict) -> dict:
        # trl >=1.x: prompt/completion columns + completion_only_loss (collator removed).
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": user_content(r["question"], r["response_A"], r["response_B"])}],
            tokenize=False, add_generation_prompt=True)
        return {"prompt": prompt, "completion": r["gold"]}

    ds = ds.map(to_pc, remove_columns=ds.column_names)

    cfg = SFTConfig(
        output_dir=args.out, num_train_epochs=args.epochs,
        per_device_train_batch_size=1, gradient_accumulation_steps=16,
        learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.03,
        max_length=args.max_seq, bf16=True, optim="paged_adamw_8bit",
        logging_steps=20, save_strategy="epoch", report_to="none",
        completion_only_loss=True, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False})

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         processing_class=tok, peft_config=lora)
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"saved adapter -> {args.out}")


if __name__ == "__main__":
    main()
