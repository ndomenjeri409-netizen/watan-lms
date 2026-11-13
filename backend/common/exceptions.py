from rest_framework.views import exception_handler

STATUS_CODES = {
    400: "VALIDATION",
    401: "AUTHENTICATION",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    429: "THROTTLED",
    503: "SERVICE_UNAVAILABLE",
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
    elif isinstance(detail, dict):
        message = _first_field_message(detail) or message
    response.data = {
        "code": STATUS_CODES.get(response.status_code, "UNKNOWN"),
        "message": message,
        "fields": fields,
    }
    return response


def _first_field_message(fields):
    for value in fields.values():
        if isinstance(value, dict):
            message = _first_field_message(value)
            if message:
                return message
        elif isinstance(value, (list, tuple)) and value:
            return str(value[0])
        elif value:
            return str(value)
    return None
