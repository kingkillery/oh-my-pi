ALLOWED_PATHS = [
    "harness/routing/",
    "harness/fusion/",
    "harness/rubric/",
    "harness/experience/search_cli.py",
    "harness/agents/",
    "prompts/",
    "configs/router.yaml",
    "configs/rubric.yaml",
    "configs/models.yaml",
    "tests/unit/",
]

FORBIDDEN_PATHS = [
    "evals/holdout/",
    "evals/validation/answers/",
    "harness/evals/scoring.py",
    "harness/security/secret_policy.py",
    "harness/security/permissions.py",
    "configs/permissions.yaml",
    ".env",
    "secrets/",
    "deployment/",
    ".github/workflows/deploy",
]
