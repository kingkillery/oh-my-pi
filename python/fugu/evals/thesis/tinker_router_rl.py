from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from tinker_cookbook import checkpoint_utils, cli_utils, renderers
from tinker_cookbook.rl.problem_env import ProblemEnv, ProblemGroupBuilder
from tinker_cookbook.rl.train import Config, main
from tinker_cookbook.rl.types import EnvGroupBuilder, RLDataset, RLDatasetBuilder
from tinker_cookbook.tokenizer_utils import get_tokenizer

_LETTER_RE = re.compile(r"\\boxed\{?\s*([A-J])", re.IGNORECASE)
_THESIS_PATH = Path(__file__).resolve().parent / "fusion_vs_frontier.py"


def _load_thesis_module():
    spec = importlib.util.spec_from_file_location("fusion_vs_frontier_rl", _THESIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_THESIS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_letter(text: str) -> str | None:
    boxed = _LETTER_RE.search(text)
    if boxed:
        return boxed.group(1).upper()
    plain = re.search(r"\b([A-J])\b", text.upper())
    return plain.group(1) if plain else None


@dataclass(frozen=True)
class RouterExample:
    question: str
    gold: str
    category: str
    lanes: dict[str, str | None]

    def prompt(self) -> str:
        lane_lines = [
            f"- {model}: {letter or 'NO_ANSWER'}"
            for model, letter in self.lanes.items()
        ]
        return (
            "You are Fugu's AGENT router. Your whole job is to choose the final "
            "answer from independent agent/model lane outputs. Output the answer first. "
            "Do not explain. Do not solve from scratch unless the lanes disagree; route "
            "by agent reliability, agreement pattern, and task domain.\n\n"
            f"Category: {self.category}\n"
            f"Question:\n{self.question}\n\n"
            "Lane outputs:\n"
            + "\n".join(lane_lines)
            + "\n\nFirst and only output: \\boxed{LETTER}"
        )


class FuguRouterEnv(ProblemEnv):
    def __init__(self, example: RouterExample, renderer: renderers.Renderer):
        super().__init__(
            renderer, format_coef=0.05, require_stop_sequence_for_format=False
        )
        self.example = example

    def get_question(self) -> str:
        return self.example.prompt()

    def check_format(self, sample_str: str) -> bool:
        return _extract_letter(sample_str) is not None

    def check_answer(self, sample_str: str) -> bool:
        return _extract_letter(sample_str) == self.example.gold

    def get_reference_answer(self) -> str:
        return self.example.gold


class FuguRouterDataset(RLDataset):
    def __init__(
        self,
        examples: list[RouterExample],
        batch_size: int,
        group_size: int,
        renderer: renderers.Renderer,
    ) -> None:
        self.examples = examples
        self.batch_size = batch_size
        self.group_size = group_size
        self.renderer = renderer

    def get_batch(self, index: int) -> Sequence[EnvGroupBuilder]:
        start = index * self.batch_size
        end = min((index + 1) * self.batch_size, len(self.examples))
        if start >= end:
            return []
        return [
            ProblemGroupBuilder(
                env_thunk=partial(FuguRouterEnv, example, self.renderer),
                num_envs=self.group_size,
                dataset_name="fugu-router",
            )
            for example in self.examples[start:end]
        ]

    def __len__(self) -> int:
        return math.ceil(len(self.examples) / self.batch_size)


@dataclass(frozen=True)
class FuguRouterDatasetBuilder(RLDatasetBuilder):
    train_artifact: str
    eval_artifact: str
    batch_size: int
    group_size: int
    model_name_for_tokenizer: str
    renderer_name: str

    async def __call__(self) -> tuple[FuguRouterDataset, FuguRouterDataset]:
        tokenizer = get_tokenizer(self.model_name_for_tokenizer)
        renderer = renderers.get_renderer(self.renderer_name, tokenizer=tokenizer)
        return (
            FuguRouterDataset(
                _examples_from_artifact(Path(self.train_artifact)),
                self.batch_size,
                self.group_size,
                renderer,
            ),
            FuguRouterDataset(
                _examples_from_artifact(Path(self.eval_artifact)),
                self.batch_size,
                1,
                renderer,
            ),
        )


def _examples_from_artifact(path: Path) -> list[RouterExample]:
    report = json.loads(path.read_text(encoding="utf-8"))
    config = report.get("config") or {}
    dataset = config.get("dataset")
    rows = report.get("rows") or []
    if dataset not in {"mmlu-pro", "gpqa"}:
        raise ValueError(f"{path} is missing supported config.dataset")
    source_rows = _load_thesis_module()._load_rows(dataset, len(rows))
    examples: list[RouterExample] = []
    for source, result in zip(source_rows, rows, strict=False):
        examples.append(
            RouterExample(
                question=source["question_text"],
                gold=result["gold"],
                category=str(
                    result.get("category") or source.get("category") or "unknown"
                ),
                lanes=dict(result["lanes"]),
            )
        )
    return examples


def _build_config(args: argparse.Namespace, renderer_name: str) -> Config:
    return Config(
        learning_rate=args.learning_rate,
        dataset_builder=FuguRouterDatasetBuilder(
            train_artifact=args.train_artifact,
            eval_artifact=args.eval_artifact,
            batch_size=args.groups_per_batch,
            group_size=args.group_size,
            model_name_for_tokenizer=args.model_name,
            renderer_name=renderer_name,
        ),
        model_name=args.model_name,
        recipe_name="fugu_router_grpo",
        renderer_name=renderer_name,
        lora_rank=args.lora_rank,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        log_path=args.log_path,
        base_url=args.base_url,
        eval_every=args.eval_every,
        save_every=args.save_every,
        max_steps=args.max_steps,
    )


async def _amain(args: argparse.Namespace) -> None:
    renderer_name = (
        await checkpoint_utils.resolve_renderer_name_from_checkpoint_or_default_async(
            model_name=args.model_name,
            explicit_renderer_name=args.renderer_name,
            load_checkpoint_path=None,
            base_url=args.base_url,
        )
    )
    cli_utils.check_log_dir(args.log_path, behavior_if_exists=args.if_log_exists)
    await main(_build_config(args, renderer_name))


def main_cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Train Fugu's AGENT router with Tinker GRPO."
    )
    parser.add_argument("--train-artifact", default="evals/thesis/vg_mmlu.json")
    parser.add_argument("--eval-artifact", default="evals/thesis/vg_gpqa.json")
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--renderer-name", default="qwen3_disable_thinking")
    parser.add_argument("--log-path", default="runs/tinker-router-rl")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--group-size", type=int, default=4)
    parser.add_argument("--groups-per-batch", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--eval-every", type=int, default=1)
    parser.add_argument("--save-every", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument(
        "--if-log-exists",
        choices=("delete", "resume", "ask", "raise"),
        default="delete",
    )
    args = parser.parse_args(argv)
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main_cli()
