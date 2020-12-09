# AutoClimateApp
This provides serveral services for thermostat management.

The key goals are to enable:

* Monitoring multiple thermostats to see if on, off, or offline
* 1 button click to turn off multiple thermostats
* Automatically "turn off" thermostats if unoccupied for some amount of time. 
* ("turn off" could be setting to Away mode, setting a low permanent hold temp, or even turning off completely.)

(This is an [Appdaemon](https://appdaemon.readthedocs.io/en/latest/) application that works with [Home Assistant](https://www.home-assistant.io/) home automation.)

## Sample Use Case
I have a cabin that has a main thermostat (ecobee), one in an unheated garage shop, and a Nuheat floor heater. I want to be sure that we don't accidentally leave the heat on and either cost us a ton of money (heating an uninsulated garage in the dead of winter) or even burn up our whole tank of propane. 

With this, I press one button to turn it all off when I leave. If I forget, after a configurable amount of time it will turn things off properly. For the house, that is setting the ecobee to "Away". For the garage, it is turning it completely off. For the floor heater, which does not have an "Away" mode, it is setting a "permanent hold" to 41 degrees - the lowest it accepts.

Finally, this also enables cool dashboard monitoring (with [Lovelace](https://www.home-assistant.io/lovelace/)) that shows the temperature, if it is "offline" and a color for red (bad), yellow (warning), or green (good).

## Features

1. **Summarized State**  
(Eg: app.autoclimate_state)  
This listens for changes to watched thermostat climate entities and creates a master state. See "Exposed State" below.
2. **Polling**  
Although listening for climate enitity changes should be enough, it also polls regularly (every {poll_frequency} hours) just in case.
3. **app: auto_off**  
This will turn off climates when unoccupied for X time. "Off" could be "Away" mode, a preset temperature, or literally off.
4. **Turn Heat Off MQ Event**  
You can register an MQ event (such as `app.autoclimate_turn_off_all`)
and when it is triggered, the app will set all climates to their "off" state.
5. **Test_mode with Mocks**  
(This is for advanced users and developers.)  
When you set `test_mode: true`, it will run the automation and print to teh log, but not actually take the actions (like turning off the thermostat.) If you set mocks (see `autoclimate.yaml.sample`), it will set each entity to the given state, wait a second, and then run the next mock. 

## Configuration
See autoclimate.sample.yml

## Exposed State
    app.{name}_state:
        state: (one of)
            - "on" (running)
            - "off" (all off properly)
            - "offline" (any offline)
        attributes: { (dict of key: value)
            entity1_offline: true/false
            entity1_state: offline, on, off
            entity1_unoccupied: offline / false (present) / <float hours unoccupied>
            entity1_state_reason: string (Help text on why state is the way it is)
            entity2...
        }

## MQ Events
    listens:
        app.{name}_turn_off_all
        ("name" from autoclimate.yaml "name")
    fires:
        None

## Integrations
This has been tested with:
* Ecobee
* Nuheat
