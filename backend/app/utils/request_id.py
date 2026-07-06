import uuid

from flask import g, request


HEADER = "X-Request-Id"


def install(app):
    @app.before_request
    def _set_request_id():
        rid = request.headers.get(HEADER) or uuid.uuid4().hex
        g.request_id = rid

    @app.after_request
    def _propagate_request_id(response):
        rid = getattr(g, "request_id", None)
        if rid:
            response.headers[HEADER] = rid
        return response
