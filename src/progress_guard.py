import hashlib
import json

from .schemas import ArchitecturePlan, ArchitectureReview, ReviewResolution


def _target_text(plan: ArchitecturePlan, target_field: str, resource_name: str | None) -> str:
    scope, field_name = target_field.split(".", 1)
    if scope == "resource":
        resource = next((item for item in plan.resources if item.name == resource_name), None)
        if resource is None:
            return ""
        value = getattr(resource, field_name)
    else:
        value = getattr(plan, field_name)
    return "\n".join(value).casefold() if isinstance(value, list) else str(value).casefold()


class ProgressGuard:
    """Detect repeated validated plans and reviewer demands without model judgment."""

    def __init__(self) -> None:
        self._plan_hashes: set[str] = set()
        self._review_hashes: set[str] = set()

    def observe_plan(self, plan: ArchitecturePlan) -> bool:
        payload = plan.model_dump(mode="json", exclude={"revision"})
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        is_new = digest not in self._plan_hashes
        self._plan_hashes.add(digest)
        return is_new

    def observe_review(self, review: ArchitectureReview) -> bool:
        payload = [item.model_dump(mode="json") for item in review.required_changes]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        is_new = digest not in self._review_hashes
        self._review_hashes.add(digest)
        return is_new


def resolve_review_changes(review: ArchitectureReview, plan: ArchitecturePlan) -> list[ReviewResolution]:
    resolutions: list[ReviewResolution] = []
    for index, change in enumerate(review.required_changes):
        target_text = _target_text(plan, change.target_field, change.resource_name)
        implemented = all(term.casefold() in target_text for term in change.required_terms)
        resolutions.append(
            ReviewResolution(
                required_change_index=index,
                description=change.description,
                status="implemented" if implemented else "unresolved",
                evidence_field=change.target_field,
            )
        )
    return resolutions
