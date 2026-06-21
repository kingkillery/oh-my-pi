# Criteria recipes

Use these templates as starting points. Edit them to match the task.

## Code patch selection

### Correctness
Check whether the patch fixes the requested behavior rather than only changing symptoms or nearby code. Reward patches whose edited code path directly explains the bug and the fix.

### Requirements adherence
Check whether the patch respects exact task constraints: file targets, interfaces, formats, scope boundaries, and explicit non-goals. Penalize solutions that solve a related but different problem.

### Empirical verification
Check whether the evidence shows the fix was actually exercised. Reward candidates backed by passing tests, reproductions, or observed output. Penalize unsupported claims of success.

### Maintainability
Check whether the patch fits surrounding conventions, preserves contracts, and avoids obvious regressions or brittle special-cases.

## Implementation plan selection

### Feasibility
Check whether the plan can actually be executed with the available codebase, tools, and constraints.

### Dependency handling
Check whether the plan orders work correctly, identifies blockers, and avoids impossible sequencing.

### Risk coverage
Check whether the plan anticipates failure modes, validation steps, rollback points, or ambiguous assumptions.

### User alignment
Check whether the plan optimizes for the user's actual goal, not just an internally convenient milestone.

## Written answer selection

### Factual grounding
Check whether claims are supported by provided context, files, logs, or evidence.

### Completeness
Check whether the answer covers all material parts of the request without skipping important constraints.

### Clarity
Check whether the answer is easy to follow, well-structured, and specific rather than generic.

### Actionability
Check whether the answer gives concrete next steps, decisions, or recommendations that can be used immediately.

## Design or spec draft selection

### Problem fit
Check whether the draft solves the actual user problem and target workflow.

### Scope control
Check whether the draft stays inside the requested scope and avoids unnecessary expansion.

### Implementation readiness
Check whether engineers could execute the draft with minimal hidden assumptions.

### Verification readiness
Check whether acceptance criteria, measurements, or observable success conditions are explicit.

## Criteria design checklist

Before running the verifier, confirm that each criterion is:

- narrow
- observable
- non-overlapping
- tied to evidence
- phrased as an inspection task, not a vibe

## Anti-patterns

Avoid criteria like:

- Overall quality
- Better solution
- Which feels stronger
- General goodness

Those are too fuzzy and collapse multiple dimensions into one unstable judgment.

## Good criterion shape

Use this form:

- **Name**: short noun phrase
- **Description**: what to inspect, what counts as success, what counts as failure

Example:

```json
{
  "name": "Empirical verification",
  "description": "Check whether the candidate is supported by observed test or runtime evidence. Reward candidates whose final state is validated by concrete output. Penalize candidates that only claim success."
}
```

Use fewer, sharper criteria instead of many overlapping ones.