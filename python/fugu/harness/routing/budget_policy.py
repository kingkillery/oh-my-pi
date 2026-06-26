def enforce_total_budget(candidate_count: int, candidate_budget: float, total_budget: float) -> None:
    if candidate_count * candidate_budget > total_budget:
        raise ValueError("candidate budgets exceed total budget")
