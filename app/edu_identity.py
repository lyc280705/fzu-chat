"""Education providers and their local account identities."""

EDU_STUDENT_TYPES = frozenset({"undergraduate", "graduate"})
GRADUATE_USER_PREFIX = "graduate:"


def education_user_id(student_id: str, student_type: str) -> str:
    # Keep existing undergraduate storage paths; isolate graduate histories,
    # passkeys and shared credentials even when the two systems reuse an ID.
    return f"{GRADUATE_USER_PREFIX}{student_id}" if student_type == "graduate" else student_id


def education_student_id(user_id: str, student_type: str) -> str:
    if student_type == "graduate":
        return user_id.removeprefix(GRADUATE_USER_PREFIX)
    return user_id
