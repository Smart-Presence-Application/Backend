"""
Natural ordering for roll numbers.

Roll numbers are stored as text (they may carry letters), so a plain
``ORDER BY roll_number`` sorts them as 1, 10, 11, 2, 20... Left-padding
them with zeros to a fixed width before comparing gives 1, 2, ... 10,
11 for numeric rolls and still a stable order for anything else.
ROLL_WIDTH matches Student.roll_number's max_length, so no roll is
truncated.
"""

from django.db.models import Value
from django.db.models.functions import LPad
from rest_framework.filters import OrderingFilter

ROLL_WIDTH = 20


def roll_order(field: str = "roll_number", *, descending: bool = False):
    expression = LPad(field, ROLL_WIDTH, Value("0"))

    return expression.desc() if descending else expression.asc()


def natural(term):
    """
    Turn an ordering term into a natural one when it names a roll
    number (``roll_number``, ``-student__roll_number``...). Anything
    else, expressions included, is returned unchanged.
    """

    if not isinstance(term, str):
        return term

    field = term.lstrip("-")

    if field.split("__")[-1] != "roll_number":
        return term

    return roll_order(field, descending=term.startswith("-"))


class NaturalOrderingFilter(OrderingFilter):
    """
    OrderingFilter that sorts roll numbers numerically, both for the
    view's default ordering and for ``?ordering=roll_number``.
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)

        if ordering:
            return queryset.order_by(*(natural(term) for term in ordering))

        return queryset
