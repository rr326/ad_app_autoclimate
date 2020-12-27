from appdaemon.adapi import ADAPI


def turn_off_entity(
    adapi: ADAPI,
    entity: str,
    stateobj: dict,
    config: dict,
    test_mode: bool = False,
) -> None:

    attributes = stateobj["attributes"]

    if "temperature" not in attributes:
        adapi.log(f"{entity} - Offline. Can not turn off.")
        return

    if not config:
        adapi.error(f"No off_rule for entity: {entity}. Can not turn off.")
        return

    # Set to "off"
    if config["off_state"] == "off":
        retval = adapi.call_service("climate/turn_off", entity_id=entity)
        adapi.lb_log(f"{entity} - Turn off")

    # Set to "away"
    elif config["off_state"] == "away":
        retval = adapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Away",
        )
        adapi.lb_log(f"{entity} -  Set away mode")

    # Set to "perm_hold"
    elif config["off_state"] == "perm_hold":
        retval1 = adapi.call_service(
            "climate/set_temperature",
            entity_id=entity,
            temperature=config["off_temp"],
        )

        retval2 = adapi.call_service(
            "climate/set_preset_mode",
            entity_id=entity,
            preset_mode="Permanent Hold",
        )
        adapi.log(
            f"{entity} - Set Perm Hold to {config['off_temp']}. retval1: {retval1} -- retval2: {retval2}"
        )

    # Invalid config
    else:
        adapi.error(f"Programming error. Unexpected off_rule: {config}")
