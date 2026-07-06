from __future__ import annotations

from flask import request

from .errors import ValidationFailed


def parse_pagination(default_page: int = 1, default_size: int = 20, max_size: int = 200) -> tuple[int, int]:
    try:
        page = int(request.args.get("page", default_page))
        page_size = int(request.args.get("page_size", default_size))
    except ValueError as exc:
        raise ValidationFailed("分页参数必须是整数") from exc
    if page < 1 or page_size < 1 or page_size > max_size:
        raise ValidationFailed(
            "分页参数非法",
            details={"page": page, "page_size": page_size, "max_size": max_size},
        )
    return page, page_size
