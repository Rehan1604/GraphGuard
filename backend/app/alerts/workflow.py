"""The alert life-cycle as a tiny state machine.
Analysts may only make the moves listed here. Everything else is rejected."""

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "new": {"in_review", "dismissed"},
    "in_review": {"escalated", "dismissed"},
    "escalated": {"in_review", "dismissed"},
    "dismissed": {"in_review"},  # reopening
}

# Moves that are conclusions, so the analyst must say why.
COMMENT_REQUIRED = {"escalated", "dismissed"}


class InvalidTransitionError(Exception):
    pass


class CommentRequiredError(Exception):
    pass


def check_transition(current: str, new: str, comment: str | None) -> None:
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransitionError(f"Cannot move an alert from '{current}' to '{new}'")
    if new in COMMENT_REQUIRED and not (comment and comment.strip()):
        raise CommentRequiredError(f"A comment is required when moving an alert to '{new}'")