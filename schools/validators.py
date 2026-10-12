from schools.models import School
from common.exceptions import DuplicateRecord

def validate_unique_school_code(code: str) -> str:
    """Validate that the school code is unique."""
    if School.objects.filter(code__iexact=code).exists():
        raise DuplicateRecord("A school with this code already exists.")
    return code


def validate_unique_school_email(email: str) -> str:
    """Validate that the school email is unique."""
    if School.objects.filter(email__iexact=email).exists():
        raise DuplicateRecord("A school with this email already exists.")
    return email