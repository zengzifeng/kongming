from flask import g, jsonify


def _envelope(data, message="ok", errors=None, status=200):
    body = {
        "data": data,
        "message": message,
        "request_id": getattr(g, "request_id", None),
        "errors": errors,
    }
    response = jsonify(body)
    response.status_code = status
    return response


def success(data=None, message="ok", status=200):
    return _envelope(data, message=message, status=status)


def fail(message, code="INTERNAL_ERROR", details=None, status=500):
    return _envelope(
        None,
        message=message,
        errors={"code": code, "details": details or {}},
        status=status,
    )


def paginated(items, page, page_size, total):
    return success(
        {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )
