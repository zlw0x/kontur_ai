from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str


class CadIrValidationError(ValueError):
    """Every issue found, and a summary that says what they were.

    The summary used to be `CODE@$.path` and nothing else, which is a sentence for
    somebody holding the document and useless to everybody who is not. Two readers
    are, and both were served badly by it.

    A **customer** sees this text on the page when a build is refused.
    `PARAMETER_DRIVES_NOTHING@$.parameters[1]` tells them nothing at all — not which
    dimension, not what to do — where "a length parameter no feature references:
    body_outer_diameter" tells them their drawing was read and one of its dimensions
    was not used.

    The **repair loop** is handed the same string and has to write a better document
    from it. A path into an array it can no longer see is the least it could be given;
    every issue already carries a message written for exactly this, and dropping it on
    the way out was the whole of the problem.

    Still capped at five, because a document with forty issues has one mistake made
    forty times and a wall of text helps nobody.
    """

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = tuple(issues)
        summary = "; ".join(
            f"{issue.code}@{issue.path}: {issue.message}" if issue.message
            else f"{issue.code}@{issue.path}"
            for issue in issues[:5]
        )
        if len(issues) > 5:
            summary += f" (and {len(issues) - 5} more)"
        super().__init__(summary or "CAD-IR validation failed")
