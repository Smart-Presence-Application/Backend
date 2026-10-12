"""Pagination classes."""
from rest_framework.pagination import PageNumberPagination
from decouple import config
from common.responses import paginated_response


class StandardResultsPagination(PageNumberPagination):
    page_size = config("DEFAULT_PAGE_SIZE", default=20, cast=int)
    page_size_query_param = "page_size"
    max_page_size = config("MAX_PAGE_SIZE", default=100, cast=int)

    def get_paginated_response(self, data):
        return paginated_response(
            "Fetched successfully.",
            results=data,
            count=self.page.paginator.count,
            next_url=self.get_next_link(),
            previous_url=self.get_previous_link(),
        )
