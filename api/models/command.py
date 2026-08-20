from typing import TYPE_CHECKING, Annotated, Optional

from sqlalchemy import JSON, Column, event
from sqlmodel import Field, Relationship, Session, SQLModel
from sqlmodel.main import SQLModelConfig

from api import logger
from api.models.command_group_type import CommandGroupType
from api.models.command_type import CommandType
from api.models.integration_action import IntegrationAction
from api.models.macro import CommandMacroLink
from api.models.network_request_type import NetworkRequestType
from api.models.remote_button import RemoteButton
from db_manager.db_manager import engine

if TYPE_CHECKING:
    from api.models.device import Device
    from api.models.macro import Macro

class CommandBase(SQLModel):
    name: str
    button: RemoteButton
    type: CommandType
    command_group: CommandGroupType
    device_id: int | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    headers: dict[str, str] | None = Field(default=None)
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)
    integration_action: IntegrationAction | None = Field(default=None)
    integration_entity: str | None = Field(default=None)
    script_path: str | None = Field(default=None)

class Command(CommandBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: int | None = Field(default=None, foreign_key="device.id")
    device: Optional["Device"] = Relationship(back_populates="commands")
    ir_action: Annotated[list[int], Field(default_factory=list, sa_column=Column(JSON), exclude=True)]
    headers: dict[str, str] | None = Field(default=None, sa_column=Column(JSON))
    macros: list["Macro"] = Relationship(back_populates="commands", link_model=CommandMacroLink)

    # Needed for Column(JSON)
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

class CommandWithRelationships(CommandBase):
    id: int | None
    device: "Device | None" = None
    macros: list["Macro"] = []

@event.listens_for(Session, "deleted_to_detached")
def after_delete_command(emitting_session, instance):
    if type(instance) is Command:
        command: Command = instance
        for macro in command.macros:
            with Session(engine) as session:
                local_macro = session.merge(macro)

                new_command_ids = []
                new_delays = []

                for index, command_id in enumerate(local_macro.command_ids):
                    if command_id != command.id:
                        new_command_ids.append(command_id)
                        if len(local_macro.delays) > index:
                            new_delays.append(local_macro.delays[index])

                # Remove all delays if only one or zero commands are left
                if len(new_command_ids) <= 1:
                    new_delays = []

                # Delete trailing delay if carried over
                if len(new_command_ids) == len(new_delays) > 0:
                    del new_delays[-1]

                logger.debug(f"Command {command.id} was deleted. "
                             f"Changing macro {local_macro.name} command ids from {local_macro.command_ids} to "
                             f"{new_command_ids} and delays from {local_macro.delays} to {new_delays}.")

                local_macro.command_ids = new_command_ids
                local_macro.delays = new_delays

                if len(new_command_ids) == 0:
                    logger.debug(f"Macro {local_macro.name} has no more commands left and will be deleted.")
                    session.delete(local_macro)
                else:
                    session.add(local_macro)
                session.commit()