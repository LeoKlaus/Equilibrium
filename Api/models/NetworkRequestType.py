from enum import Enum


class NetworkRequestType(str, Enum):
    GET = "get"
    POST = "post"
    DELETE = "delete"
    HEAD = "head"
    PATCH = "patch"
    PUT = "put"