from rest_framework.views import exception_handler

STATUS_CODES = {
    400: "VALIDATION",
    401: "AUTHENTICATION",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    429: "THROTTLED",
}


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    fields = detail if isinstance(detail, dict) else {}
    message = detail if isinstance(detail, str) else "Request failed."
    if isinstance(detail, dict) and "detail" in detail:
        message = str(detail["detail"])
        fields = {}
    response.data = {
        "code": STATUS_CODES.get(response.status_code, "UNKNOWN"),
        "message": message,
        "fields": fields,
    }
    return response
