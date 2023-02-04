import datetime as dt

import pytz
from adplus import Hass


def climate_name(entity):
    # climate.my_thermostat ==> my_thermostat
    return entity.split(".")[1]


def in_inactive_period(hass: Hass, inactive_period) -> bool:
    if inactive_period is None:
        return False

    try:
        now = hass.get_now()  # type: dt.datetime
        tzinfo = pytz.timezone(str(hass.get_timezone()))
        year = now.year
        ip = inactive_period
        start = dt.datetime(year, ip[0][0], ip[0][1], tzinfo=tzinfo)
        end = dt.datetime(year, ip[1][0], ip[1][1], tzinfo=tzinfo)
        return start <= now < end
    except Exception as err:
        hass.log(f"Error testing inactive period. err: {err}, ip: {ip}")
        return False
