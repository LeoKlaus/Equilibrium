from sqlmodel import SQLModel, Field


class DeviceState(SQLModel):
    powered: bool = False
    input: int|None = None

class DeviceStates(SQLModel):
    states: dict[int, DeviceState] = Field(default = {})

    def state(self, for_device_id: int) -> DeviceState:
        return self.states.get(for_device_id, DeviceState())

    def set_state(self, device_id: int, new_power_state: bool | None = None, new_input: int | None = None, toggle_power: bool | None = None):
        current_state = self.state(for_device_id=device_id)

        if toggle_power:
            current_state.powered = not current_state.powered

        if new_power_state is not None:
            current_state.powered = new_power_state

        if new_input is not None:
            current_state.input = new_input

        # Resets current input if device is turned off
        if not current_state.powered:
            current_state.input = None

        self.states[device_id] = current_state