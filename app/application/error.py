from enum import Enum


class ErrorCode(str, Enum):
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"

    INVALID_GOOGLE_CODE = "INVALID_GOOGLE_CODE"
    INVALID_SERVER_STATE = "INVALID_SERVER_STATE"

    INVALID_ACCESS_TOKEN = "INVALID_ACCESS_TOKEN"
    ALREADY_VERIFIED = "ALREADY_VERIFIED"
    INVALID_VERIFICATION_CODE = "INVALID_VERIFICATION_CODE"

    INVALID_SPREADSHEET_ID = "INVALID_SPREADSHEET_ID"
    INVALID_MATCH_ID = "INVALID_MATCH_ID"
