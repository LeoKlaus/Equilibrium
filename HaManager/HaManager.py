import asyncio

from homeassistant_api import Client, Domain
import logging

class HaManager:

    logger = logging.getLogger(__package__)

    light_domain: Domain|None = None
    last_light_id: str|None = None

    def __init__(self, url, token):
        self.client = Client(url, token)

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