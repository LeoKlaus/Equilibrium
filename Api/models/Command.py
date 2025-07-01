from typing import TYPE_CHECKING, Optional, Annotated

from sqlalchemy import Column, JSON, event
from sqlmodel import SQLModel, Field, Relationship, Session

from Api import logger
from Api.models.CommandGroupType import CommandGroupType
from Api.models.CommandType import CommandType
from Api.models.Macro import CommandMacroLink
from Api.models.NetworkRequestType import NetworkRequestType
from Api.models.RemoteButton import RemoteButton
from DbManager.DbManager import engine

if TYPE_CHECKING:
    from Api.models.Device import Device
    from Api.models.Macro import Macro

class CommandBase(SQLModel):
    name: str
    button: RemoteButton
    type: CommandType
    command_group: CommandGroupType
    device_id: int | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)

class Command(CommandBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    device_id: int | None = Field(default=None, foreign_key="device.id")
    device: "Device" = Relationship(back_populates="commands")
    ir_action:  Annotated[list[int], Field(default=[], sa_column=Column(JSON), exclude=True)]
    bt_action: str | None = Field(default=None)
    bt_media_action: str | None = Field(default=None)
    host: str | None = Field(default=None)
    method: NetworkRequestType | None = Field(default=None)
    body: str | None = Field(default=None)
    macros: list["Macro"] = Relationship(back_populates="commands", link_model=CommandMacroLink)

    # Needed for Column(JSON)
    class Config:
        arbitrary_types_allowed = True

class CommandWithRelationships(CommandBase):
    id: int | None
    device: Optional["Device"] = None
    macros: list["Macro"] = []




@event.listens_for(Session, "deleted_to_detached")
def after_delete_command(emitting_session, instance):
    if type(instance) == Command:
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