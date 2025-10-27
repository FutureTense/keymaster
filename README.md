# keymaster

Home Assistant keymaster integration for Z-Wave enabled locks. This integration allows you to control one (or more) Z-Wave enabled locks that have been added to your Z-Wave network.  Besides being able to control your lock with lock/unlock commands, you can also control who may lock/unlock the device using the lock's front facing keypad.  With the integration you may create multiple users or slots and each slot (the number depends upon the lock model) has its own PIN code.

Setting up a lock for the entire family can be accomplished in a matter of seconds.  Did you just leave town and forgot to turn the stove off?  through the Home Assistant interface you can create a new PIN instantly and give it to a neighbor and delete it later.  Do you have house cleaners that come at specifc times?  With the advanced PIN settings you can create a slot that only unlocks on specific date and time ranges. You may also create slots that allow a number of entries, after which the lock won't respond to the PIN.

For more information, please see the topic for this package at the [Home Assistant Community Forum](https://community.home-assistant.io/t/simplified-zwave-keymaster/126765).

## Installation

### Install keymaster via HACS

This integration can be added to your installation manually, but the *supported* method requires you to use The [Home Assistant Community Store](https://community.home-assistant.io/t/custom-component-hacs/121727).  If you dont't already have HACS, it is [simple to install](https://hacs.xyz/docs/setup/prerequisites/).

Open HACS and select the Integrations tab.  Click the + icon at the bottom right and search for `keymaster`.  You will then get a message that the integration requires Home Assistant to be restarted.  Please do so.

You need to create an integration for each lock you want to control.  Select Configuration | Integrations.  Click the + icon at the bottom right and search for **keymaster** and select it.

If the integration **_does not_** show up when searching, press `F5` from the integration screen to refresh the list of integrations.

The integration UI will prompt you for several values.  Below we are using the default entity names that are created for a Schlage BE469 lock.

**Note:** Renaming your entities is _**not required**_, but it's _recommended_ to amend the door name to the end of your entities for your sanity, example: `sensor.be469zp_connect_smart_deadbolt_user_code_backdoor`

***
### What you'll see

***IMAGE PENDING UPDATE***

<img src="https://github.com/FutureTense/keymaster/raw/main/docs/integration_screen_wiki.png" alt="Integration Screen" />

#### 1.  **Parent lock**

Use this to make this lock a `child` of the specified `parent` lock.  This will copy all of the names/PIN/settings from the parent to this lock.  Any changes made to the parent lock will happen on this lock allowing you to manage multiple locks from one location.

#### 2.  **Z-wave lock**

Use the dropdown and select your Z-Wave lock.  The default for Schlage looks like `lock.be469zp_connect_smart_deadbolt_locked`, this drop down will only show available lock devices.

#### 3.  **Code slots**

The number of code slots or PINS you want to manage.  The maxinum number is depedant upon your lock.  Don't create more slots than you will actually need, because too many can slow your lovelace UI down.

#### 4. **Start from code slot #**

Unless you are using an `ID Brand` lock or a lock where the user codes do not start at slot 1, leave this as the default `1`, otherwise `ID Brand` locks start at around user code 50 due to RFID/Bluetooth/etc codes.

#### 5.  **Lock Name**

Give your lock a name that will be used in notifications, e.g. *frontdoor*

#### 6.  **Door Sensor**

If your lock has a sensor that determines if the door is opened/closed, select it here.  The Schlage doesn't have one but you can use a third party sensor or specify any sensor here.

#### 7.  **User Code Sensor**

This sensor returns the slot number for a user that just entered their lock PIN.  Schlage value: `sensor.be469zp_connect_smart_deadbolt_user_code`

#### 8.  **Access Control Sensor**

This sensor returns the command number just executed by the lock.  Schlage value: `sensor.be469zp_connect_smart_deadbolt_access_control`

#### 9.  **Path to packages directory**

The default `packages/keymaster` should suffice.

## Adding UI to Home Assistant

If all goes well, you will also see a new directory (by default `<your config directory/custom_components/keymaster/lovelace/>`) for each lock with `yaml` and a lovelace files. So if you add two integrations, one with FrontDoor and the other with BackDoor, you should see two directories with those names. Inside of each of those directories will be a file called `<lockname>.yaml`. Open that file in a text editor and select the entire contents and copy to the clipboard.

> (Open file) Ctrl-A (select all) Ctrl-C (copy)

Open Home Assistant and open the LoveLace editor by clicking the ellipses on the top right of the screen, and then select "Configure UI" or "Edit Dashboard". Click the ellipses again and click "Raw config editor". Scroll down to the bottom of the screen and then paste your clipboard. This will paste a new View for your lock. Click the Save button then click the X to exit.

In order for the lovelace ui to work properly you will need to install the following modules.
1. [lovelace-auto-entities](https://github.com/thomasloven/lovelace-auto-entities)
2. [lovelace-card-tools](https://github.com/thomasloven/lovelace-card-tools)
3. [lovelace-fold-entity-row](https://github.com/thomasloven/lovelace-fold-entity-row)
4. [numberbox-card](https://github.com/htmltiger/numberbox-card)

The easiest way to install these modules is via [Home Assistant Community Store(HACS)](https://hacs.xyz/docs/categories/plugins).

## Troubleshooting

### Missing Sensors
If you are not seeing your `User Code`, `Access Control`, `Alarm Type`, or `Alarm Level`, please note in `ozw` and `zwave_js` they are disabled by default as the preferred method is to use the `Home Security` sensor. Enabling these sensors does not break anything and allows the automations to accurately process the lock information. If you can't find these sensors (enabled or disabled) and you are using the `zwave_js` integration, your lock notifications may be coming in as events and you can use `sensor.fake` when setting these sensor values during set up.

### Code Slots
The code slots are updated every 5 seconds internally in Home Assistant, this method does not poll the lock and wake it up resulting in battery drain.

### Unable to set codes
This usually occurs due to the ZWave network not being detected. This can happen at startup but it should resolve itself, if it does not, please [enable debugging](https://github.com/FutureTense/keymaster/wiki/Troubleshooting#enable-debugging) and create a bug report.

### Entity not available messages
This usually occurs when you haven't added the `packages` configuration to your `configuration.yaml` file. Please [**see the pre-install instructions**](https://github.com/FutureTense/keymaster/wiki/Pre-Installation-Steps-(IMPORTANT)) on how to do that.

### Enable Debugging
This will be needed from time to time to get more data to find out what's going on. Navigate to `Dev-tools` -> `Services` tab in Home Assistant.
Select the service `logger.set_level` in data enter `custom_components.keymaster: debug` and press `Call Service`.
Your log will now start showing debug data in the Home Assistant log.

If you are missing the service `logger.set_level` this usually because `logger` wasn't added to your `configuration.yaml` add the following to enable this super useful service.

```yaml
logger:
  default: warning
```
