import datetime as dt
from typing import List, Optional, Tuple

from adplus import Hass


def get_unoccupied_time_for(
    entity: str, config: dict, hassapi: Hass
) -> Tuple[Optional[str], Optional[float], Optional[dt.datetime]]:
    try:
        oc_sensor = config["occupancy_sensor"]
    except KeyError:
        hassapi.error(f"Unable to get occupancy_sensor for {entity}")
        return None, None, None

    state, duration_off, last_on_date = occupancy_length(oc_sensor, hassapi)
    return state, duration_off, last_on_date


def occupancy_length(entity_id: str, hassapi: Hass, days: int = 10):
    """
    returns: state (on/off), duration_off (hours float / None), last_on_date (datetime, None)
    {
        "entity_id": "binary_sensor.seattle_occupancy",
        "state": "off",
        "attributes": {
            "friendly_name": "Seattle Occupancy",
            "device_class": "occupancy"
        },
        "last_changed": "2020-10-28T13:10:47.384057+00:00",
        "last_updated": "2020-10-28T13:10:47.384057+00:00"
    }
    """
    data: List = hassapi.get_history(entity_id=entity_id, days=days)  # type: ignore

    if not data or len(data) == 0:
        hassapi.warn(f"get_history returned no data for entity: {entity_id}. Exiting")
        return "error", None, None
    edata = data[0]

    # the get_history() fn doesn't say it guarantees sort (though it appears to be)
    edata = list(reversed(sorted(edata, key=lambda rec: rec["last_updated"])))

    current_state = edata[0]["state"]
    if current_state == "on":
        return "on", None, None

    last_on_date = None
    now: dt.datetime = hassapi.get_now()  # type: ignore
    for rec in edata:
        if rec.get("state") == "on":
            last_on_date = dt.datetime.fromisoformat(rec["last_updated"])
            duration_off_hours = round(
                (now - last_on_date).total_seconds() / (60 * 60), 2
            )
            return "off", duration_off_hours, last_on_date

    # Can not find a last on time. Give the total time shown.
    min_time_off = round(
        (now - dt.datetime.fromisoformat(edata[-1]["last_updated"])).seconds
        / (60 * 60),
        2,
    )
    return "off", min_time_off, None
