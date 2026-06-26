from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["route", "orchestrate"]
Topology = Literal["single", "tree", "debate", "build_debug", "specialist"]


class ScaffoldNode(BaseModel):
    model: str
    role: str
    instruction: str
    children: list["ScaffoldNode"] = Field(default_factory=list)


class ScaffoldPlan(BaseModel):
    mode: Mode
    topology: Topology
    nodes: list[ScaffoldNode]
    aggregator: str | None = None
    rounds: int = 1
    rationale: str

    @model_validator(mode="after")
    def validate_shape(self) -> "ScaffoldPlan":
        if self.rounds < 1:
            raise ValueError("rounds must be positive")
        if self.mode == "route" and self.topology != "single":
            raise ValueError("route mode requires single topology")
        if self.topology == "single":
            if len(self.nodes) != 1:
                raise ValueError("single topology requires exactly one node")
            if self.aggregator is not None:
                raise ValueError("single topology must not set aggregator")
        if self.topology == "tree":
            if len(self.nodes) < 2:
                raise ValueError("tree topology requires at least two leaves")
            if self.aggregator is None:
                raise ValueError("tree topology requires an aggregator")
        if self.topology == "debate":
            if len(self.nodes) < 2:
                raise ValueError("debate topology requires at least two nodes")
            if self.aggregator is None:
                raise ValueError("debate topology requires an aggregator")
        if self.topology == "build_debug":
            self._require_ordered_roles(("builder", "debugger"))
        if self.topology == "specialist":
            self._require_ordered_roles(("builder", "debugger", "specialist"))
        return self

    def validate_pool(self, model_ids: set[str]) -> "ScaffoldPlan":
        missing = {node.model for node in self.nodes if node.model not in model_ids}
        if self.aggregator is not None and self.aggregator not in model_ids:
            missing.add(self.aggregator)
        if missing:
            joined = ", ".join(sorted(missing))
            raise ValueError(f"scaffold references unknown model(s): {joined}")
        return self

    def _require_ordered_roles(self, roles: tuple[str, ...]) -> None:
        actual = tuple(node.role for node in self.nodes[: len(roles)])
        if actual != roles:
            expected = ", ".join(roles)
            raise ValueError(
                f"{self.topology} topology requires ordered roles: {expected}"
            )
        if self.aggregator is None:
            raise ValueError(f"{self.topology} topology requires an aggregator")
