import asyncio
import logging

from homeassistant_api import Client, Domain

from Api.models.Command import Command
from Api.models.IntegrationAction import IntegrationAction
from hub.event_bus import Directive
from hub.interfaces import ActionExecutor


class HaManager(ActionExecutor):

    name = "integration"

    logger = logging.getLogger(__package__)

    light_domain: Domain|None = None
    last_light_id: str|None = None

    def __init__(self, url, token):
        self.client = Client(url, token)

    async def execute(self, directive: Directive, command: Command) -> None:
        if command.integration_action is None:
            self.logger.error(f"Command {command.name} doesn't include a Home Assistant action")
            return

        loop = asyncio.get_running_loop()
        match command.integration_action:
            case IntegrationAction.TOGGLE_LIGHT:
                assert command.integration_entity is not None  # enforced at command creation
                await loop.run_in_executor(None, self.toggle_light, command.integration_entity)
            case IntegrationAction.BRIGHTNESS_UP:
                await loop.run_in_executor(None, self.increase_brightness)
            case IntegrationAction.BRIGHTNESS_DOWN:
                await loop.run_in_executor(None, self.decrease_brightness)

    def get_lights(self):
        entities = self.client.get_entities()
        group = entities.get("light")
        return group.entities

    def toggle_light(self, entity_id: str):
        if self.light_domain is None:
            self.light_domain = self.client.get_domain("light")
        self.light_domain.toggle(entity_id=entity_id)
        self.last_light_id = entity_id

    def _turn_on(self, **kwargs):
        if self.last_light_id is None:
            self.logger.warning("Tried to change brightness without setting light first")
            return
        if self.light_domain is None:
            self.light_domain = self.client.get_domain("light")
        # Refer to https://www.home-assistant.io/integrations/light/#action-lightturn_on
        self.light_domain.turn_on(entity_id=self.last_light_id, **kwargs)

    def increase_brightness(self):
        self._turn_on(brightness_step_pct=10)

    def decrease_brightness(self):
        self._turn_on(brightness_step_pct=-10)