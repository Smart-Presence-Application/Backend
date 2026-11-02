"""
Shared pieces for bulk-delete endpoints.

Each item is deleted inside its own savepoint, so one record that is
still referenced elsewhere (a protected foreign key) is reported as
failed without rolling back the others. Ids outside the actor's scope
are reported exactly like ids that do not exist, so a bulk request
cannot be used to probe for records the actor may not see.
"""

from collections.abc import Callable, Iterable

from django.db import IntegrityError, transaction
from django.db.models import Model, QuerySet
from rest_framework import serializers

MAX_BULK_IDS = 500

REFERENCED_REASON = "It is referenced by other records."


class BulkIdsSerializer(serializers.Serializer):
    """``{"ids": [1, 2, 3]}``: 1-500 positive ids, duplicates dropped."""

    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=MAX_BULK_IDS,
        error_messages={
            "min_length": "Select at least one item.",
            "max_length": (
                f"No more than {MAX_BULK_IDS} items can be deleted at once."
            ),
        },
    )

    def validate_ids(self, value):
        return list(dict.fromkeys(value))


def bulk_delete(
    *,
    queryset: QuerySet,
    ids: list[int],
    delete: Callable[[Model], str | None],
    outcomes: Iterable[str] = ("deleted",),
    failed_reason: str = REFERENCED_REASON,
) -> dict:
    """
    Run ``delete`` on every object in ``queryset`` whose id is in ``ids``.

    ``delete`` may return the outcome key the id belongs under (one of
    ``outcomes``, e.g. "unlinked"); returning None means "deleted".
    The result keeps the request's id order:
    ``{<outcome>: [ids], "not_found": [ids], "failed": [{id, reason}]}``.
    """

    result = {key: [] for key in outcomes}
    result["not_found"] = []
    result["failed"] = []

    found = {obj.pk: obj for obj in queryset.filter(pk__in=ids)}

    for pk in ids:
        obj = found.get(pk)

        if obj is None:
            result["not_found"].append(pk)
            continue

        try:
            with transaction.atomic():
                outcome = delete(obj) or "deleted"
        except IntegrityError:
            result["failed"].append({"id": pk, "reason": failed_reason})
            continue

        result[outcome].append(pk)

    return result


def bulk_delete_message(result: dict, noun: str, plural: str | None = None) -> str:
    """E.g. "3 students deleted. 1 not found. 1 could not be deleted." """

    plural = plural or f"{noun}s"

    def count(n: int) -> str:
        return f"{n} {noun if n == 1 else plural}"

    parts = [f"{count(len(result['deleted']))} deleted."]

    if result.get("unlinked"):
        parts.append(
            f"{count(len(result['unlinked']))} unlinked from your students "
            "(they have children outside your scope)."
        )

    if result["not_found"]:
        parts.append(f"{len(result['not_found'])} not found.")

    if result["failed"]:
        parts.append(f"{len(result['failed'])} could not be deleted.")

    return " ".join(parts)
