import re


def validate_email(email: str) -> bool:
    return bool(re.search(r"\d+sunrin\d+", email))
