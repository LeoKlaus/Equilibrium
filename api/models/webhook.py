from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel
from sqlmodel.main import SQLModelConfig

from api.models.network_request_type import NetworkRequestType
from api.models.webhook_body_format import WebhookBodyFormat
from hub.scene_events import SceneEvent


class WebhookBase(SQLModel):
    name: str
    url: str
    method: NetworkRequestType = Field(default=NetworkRequestType.POST)
    headers: dict[str, str] | None = Field(default=None)
    body_template: str | None = Field(default=None)
    body_format: WebhookBodyFormat = Field(default=WebhookBodyFormat.JSON)
    events: list[SceneEvent] = Field(default_factory=list)
    scene_ids: list[int] = Field(default_factory=list)
    enabled: bool = Field(default=True)


class Webhook(WebhookBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    headers: dict[str, str] | None = Field(default=None, sa_column=Column(JSON))
    events: list[SceneEvent] = Field(default_factory=list, sa_column=Column(JSON))
    scene_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))

    model_config = SQLModelConfig(arbitrary_types_allowed=True)


class WebhookRead(WebhookBase):
    id: int


class WebhookUpdate(SQLModel):
    """Whatever of a webhook should change. Only headers and body_template can
    be set to null (to remove them)."""

    name: str | None = None
    url: str | None = None
    method: NetworkRequestType | None = None
    headers: dict[str, str] | None = None
    body_template: str | None = None
    body_format: WebhookBodyFormat | None = None
    events: list[SceneEvent] | None = None
    scene_ids: list[int] | None = None
    enabled: bool | None = None
