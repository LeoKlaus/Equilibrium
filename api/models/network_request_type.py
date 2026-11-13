from enum import StrEnum


class NetworkRequestType(StrEnum):
    GET = "get"
    POST = "post"
    DELETE = "delete"
    HEAD = "head"
    PATCH = "patch"
    PUT = "put"