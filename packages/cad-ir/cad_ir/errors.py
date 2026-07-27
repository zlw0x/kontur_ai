from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str


class CadIrValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = tuple(issues)
        summary = "; ".join(f"{issue.code}@{issue.path}" for issue in issues[:5])
        super().__init__(summary or "CAD-IR validation failed")
