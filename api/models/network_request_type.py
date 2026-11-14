from enum import StrEnum


class NetworkRequestType(StrEnum):
    GET = "get"
    POST = "post"
    DELETE = "delete"
    HEAD = "head"
    PATCH = "patch"
    PUT = "put"

    @property
    def has_body(self) -> bool:
        """Whether a request of this type sends a body."""
        return self in (NetworkRequestType.POST, NetworkRequestType.PATCH, NetworkRequestType.PUT)
