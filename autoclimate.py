import json  # noqa

import adplus

adplus.importlib.reload(adplus)
import _autoclimate
import _autoclimate.mocks
import _autoclimate.occupancy
import _autoclimate.state
import _autoclimate.turn_off


adplus.importlib.reload(_autoclimate)
adplus.importlib.reload(_autoclimate.state)
adplus.importlib.reload(_autoclimate.mocks)
adplus.importlib.reload(_autoclimate.occupancy)
adplus.importlib.reload(_autoclimate.turn_off)

from _autoclimate.mocks import Mocks
from _autoclimate.occupancy import Occupancy
from _autoclimate.state import State
from _autoclimate.turn_off import TurnOff
from _autoclimate.schema import SCHEMA


class AutoClimate(adplus.Hass):
    """
    # AutoClimateApp
    This provides serveral services for thermostat management.

    See README.md for documentation.
    See autoclimate.yaml.sample for sample configuration.

    ## Events
    Events have TWO names:
    event = "autoclimate" for ALL events
    sub_event = app.{appname}_event - this is the event you actually care about

    Why? To trigger an event in Lovelace, you need to trigger a script, where you
    have to hardcode the event name, but can send template data in the body. So
    rather than have to write different scripts for each event, here you create
    *one* script to trigger the event and put the event you care about in a
    sub_event kwarg.
    """

    EVENT_TRIGGER = "autoclimate"

    def initialize(self):
        self.log("Initialize")

        self.argsn = adplus.normalized_args(self, SCHEMA, self.args, debug=False)
        self.entity_rules = self.argsn["entity_rules"]
        self.extra_validation(self.argsn)
        self.test_mode = self.argsn.get("test_mode")
        self.appname = self.argsn["name"]
        self.poll_frequency = self.argsn["poll_frequency"]

        self.TRIGGER_HEAT_OFF = f"app.{self.appname}_turn_off_all"

        self.climates = list(self.entity_rules.keys())
        self.log(f"Climates controlled: {self.climates}")

        #
        # Initialize sub-classes
        #
        self.state_module = State(
            hass=self,
            config=self.entity_rules,
            poll_frequency=self.argsn["poll_frequency"],
            appname=self.appname,
            climates=self.climates,
            create_temp_sensors=self.argsn["create_temp_sensors"],
            test_mode=self.test_mode,
        )
        self.climate_state = self.state_module.state

        self.occupancy_module = Occupancy(
            hass=self,
            config=self.entity_rules,
            appname=self.appname,
            climates=self.climates,
            test_mode=self.test_mode,
        )

        self.turn_off_module = TurnOff(
            hass=self,
            config=self.entity_rules,
            poll_frequency=self.argsn["poll_frequency"],
            appname=self.appname,
            climates=self.climates,
            test_mode=self.test_mode,
            climate_state = self.climate_state
        )        

        self.mock_module = Mocks(
            hass=self,
            mock_config=self.argsn["mocks"],
            run_mocks=self.argsn["run_mocks"],
            mock_callbacks=[self.turn_off_module.autooff_scheduled_cb],
            init_delay=1,
            mock_delay=1,
        )

    def extra_validation(self, args):
        # Validation that Cerberus doesn't do well
        for climate, rule in self.entity_rules.items():
            offrule = rule.get("off_state", {})
            if offrule.get("state", "") == "perm_hold":
                if "temp" not in offrule:
                    self.error(f'Invalid offrule. Perm_hold needs an "temp": {offrule}')
                if "perm_hold_string" not in offrule:
                    self.error(
                        f'Invalid offrule. Perm_hold needs an "perm_hold_string": {offrule}'
                    )

            state = self.get_state(climate, attribute="all")
            if state == None:
                self.error(
                    f"Probable misconfiguration (bad entity): could not get state for entity: {climate}"
                )

    def trigger_sub_events(self):
        pass

