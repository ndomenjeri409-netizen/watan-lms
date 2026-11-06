from apps.accounts.roles import ADMIN_ROLES, Role

UPLOAD_POLICIES = {
    "material": {
        "roles": ADMIN_ROLES | {Role.HOD, Role.TEACHER},
        "max_bytes": 25 * 1024 * 1024,
        "content_types": {
            ".pdf": {"application/pdf"},
            ".docx": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            },
            ".pptx": {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            },
            ".xlsx": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".png": {"image/png"},
            ".webp": {"image/webp"},
            ".zip": {"application/zip", "application/x-zip-compressed"},
        },
    },
    "cover_image": {
        "roles": ADMIN_ROLES | {Role.HOD},
        "max_bytes": 3 * 1024 * 1024,
        "content_types": {
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".png": {"image/png"},
            ".webp": {"image/webp"},
        },
    },
    "submission": {
        "roles": {Role.STUDENT},
        "max_bytes": 20 * 1024 * 1024,
        "content_types": {
            ".pdf": {"application/pdf"},
            ".docx": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            },
            ".doc": {"application/msword"},
            ".txt": {"text/plain"},
            ".jpg": {"image/jpeg"},
            ".jpeg": {"image/jpeg"},
            ".png": {"image/png"},
        },
    },
}
