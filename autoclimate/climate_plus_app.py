"""
This provides services for climate entitities.

It usses support functions in the climate_plus package.

It can be used by an app like AutoClimateApp.

### Services
1. turn_off_entity()
2. turn_off_all()
3. publish_state()
4. create_temp_sensors()
5. publish_unoccupied_for()
"""

import json  # noqa

import adplus
import climate_plus

adplus.importlib.reload(adplus)
adplus.importlib.reload(climate_plus)


class ClimatePlus(adplus.Hass):
    OFF_SCHEMA = {
        "type": "dict",
        "schema": {
            "off_state": {
                "type": "string",
                "required": True,
                "allowed": ["away", "off", "perm_hold"],
            },
            "off_temp": {"type": "number", "required": False},
            "perm_hold_string": {"type": "string", "required": False},
        },
    }

    def initialize(self):
        self.log("Initialize")
        self.namespace = self.args.get("namespace", "autoclimate")
        self.test_mode = self.args.get("test_mode", False)

        # self.listen_event(self.cb_turn_off_entity, event=self.EVENT_TRIGGER, sub_event = self.EVENT_TURN_OFF_ENTITY)
        # self.listen_event(self.cb_turn_off_all, event=self.EVENT_TRIGGER, sub_event = self.EVENT_TURN_OFF_ALL)
        self.listen_event(
            self.test_event, event=self.EVENT_TRIGGER, sub_event=self.EVENT_TURN_OFF_ALL
        )

    def test_event(self, event_name, data, kwargs):
        self.log(f"## test_event triggered: {event_name} -- {data} -- {kwargs}")

   