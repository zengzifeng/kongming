from __future__ import annotations

from pydantic import ValidationError

from .response import fail


class AppError(Exception):
    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str, details: dict | None = None, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code
        if status:
            self.status = status


class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    status = 400


class NotFound(AppError):
    code = "RESOURCE_NOT_FOUND"
    status = 404


class StateConflict(AppError):
    code = "STATE_CONFLICT"
    status = 409


class IntegrationError(AppError):
    code = "INTEGRATION_FAILED"
    status = 502


class AlgorithmError(AppError):
    code = "ALGORITHM_FAILED"
    status = 500


def register_handlers(app):
    @app.errorhandler(AppError)
    def _handle_app_error(err: AppError):
        return fail(err.message, code=err.code, details=err.details, status=err.status)

    @app.errorhandler(ValidationError)
    def _handle_pydantic(err: ValidationError):
        return fail(
            "请求参数校验失败",
            code="VALIDATION_ERROR",
            details={"errors": err.errors()},
            status=400,
        )

    @app.errorhandler(404)
    def _handle_404(_):
        return fail("资源不存在", code="RESOURCE_NOT_FOUND", status=404)

    @app.errorhandler(405)
    def _handle_405(_):
        return fail("方法不允许", code="METHOD_NOT_ALLOWED", status=405)

    @app.errorhandler(Exception)
    def _handle_other(err: Exception):
        app.logger.exception("unhandled error: %s", err)
        return fail(str(err) or "服务器内部错误", code="INTERNAL_ERROR", status=500)
