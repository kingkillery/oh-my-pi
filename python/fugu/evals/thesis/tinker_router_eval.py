from __future__ import annotations

import argparse
import json
from pathlib import Path

import tinker
from tinker import types
from tinker_cookbook import checkpoint_utils, renderers
from tinker_cookbook.tokenizer_utils import get_tokenizer

from evals.thesis.tinker_router_rl import _examples_from_artifact, _extract_letter


def _checkpoint_from_args(args: argparse.Namespace) -> str:
    if args.checkpoint:
        return args.checkpoint
    checkpoint = checkpoint_utils.get_last_checkpoint(
        args.log_path, required_key="sampler_path"
    )
    if checkpoint is None or checkpoint.sampler_path is None:
        raise RuntimeError(f"no sampler checkpoint found in {args.log_path}")
    return checkpoint.sampler_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a Tinker-trained Fugu AGENT router."
    )
    parser.add_argument("--artifact", default="evals/thesis/vg_gpqa.json")
    parser.add_argument("--log-path", default="runs/tinker-router-rl")
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--renderer-name", default="qwen3_disable_thinking")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--out", default="evals/thesis/tinker_router_eval.json")
    args = parser.parse_args()

    examples = _examples_from_artifact(Path(args.artifact))
    checkpoint = _checkpoint_from_args(args)
    tokenizer = get_tokenizer(args.model_name)
    renderer = renderers.get_renderer(args.renderer_name, tokenizer=tokenizer)
    sampling_client = tinker.ServiceClient(
        base_url=args.base_url
    ).create_sampling_client(model_path=checkpoint)
    sampling_params = types.SamplingParams(
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    futures = [
        sampling_client.sample(
            prompt=renderer.build_generation_prompt(
                [{"role": "user", "content": example.prompt()}]
            ),
            num_samples=1,
            sampling_params=sampling_params,
        )
        for example in examples
    ]

    rows = []
    for example, future in zip(examples, futures, strict=True):
        response = future.result()
        tokens = response.sequences[0].tokens
        message, _termination = renderer.parse_response(tokens)
        text = renderers.get_text_content(message)
        answer = _extract_letter(text)
        rows.append(
            {
                "gold": example.gold,
                "answer": answer,
                "correct": answer == example.gold,
                "text": text,
                "lanes": example.lanes,
            }
        )

    accuracy = round(sum(1 for row in rows if row["correct"]) / len(rows), 4)
    report = {
        "artifact": args.artifact,
        "checkpoint": checkpoint,
        "n": len(rows),
        "accuracy": accuracy,
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "rows"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
