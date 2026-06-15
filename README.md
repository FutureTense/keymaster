# keymaster

Home Assistant keymaster integration for Z-Wave enabled locks. This integration
allows you to control one (or more) Z-Wave enabled locks that have been added
to your Z-Wave network.  Besides being able to control your lock with
lock/unlock commands, you can also control who may lock/unlock the device using
the lock's front facing keypad.  With the integration you may create multiple
users or slots and each slot (the number depends upon the lock model) has its
own PIN code.

Setting up a lock for the entire family can be accomplished in a matter of
seconds.  Did you just leave town and forgot to turn the stove off?  through
the Home Assistant interface you can create a new PIN instantly and give it to
a neighbor and delete it later.  Do you have house cleaners that come at
specific times?  With the advanced PIN settings you can create a slot that only
unlocks on specific date and time ranges. You may also create slots that allow
a number of entries, after which the lock won't respond to the PIN.

For more information, please see the topic for this package at the [Home
Assistant Community
Forum](https://community.home-assistant.io/t/simplified-zwave-keymaster/126765).

## Lovelace Dashboard

Keymaster includes Lovelace strategies that automatically generate dashboards
for managing your locks. You can create a complete Keymaster dashboard with a
single line of YAML, or add individual lock views to existing dashboards. See
the [Lovelace Configuration](https://github.com/FutureTense/keymaster/wiki/Lovelace-Configuration-Automatic)
wiki page for setup instructions and configuration options.

## Supported Lock Providers

Keymaster supports multiple lock integrations and communication protocols via a
provider abstraction model. Below is the support matrix of features for each
provider:

<!-- markdownlint-disable MD013 -->
| Integration / Platform | Domain | Protocol | Push Updates | Connection Status | Description / Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **[Z-Wave JS](https://www.home-assistant.io/integrations/zwave_js/)** | `zwave_js` | Z-Wave | ✅ | ✅ | Direct node-based lock control with full pin/metadata querying. |
| **[Zigbee2MQTT](https://www.zigbee2mqtt.io/)** | `mqtt` | Zigbee | ✅ | ✅ | MQTT-based control (requires `expose_pin: true` in Z2M config). |
| **[ZHA](https://www.home-assistant.io/integrations/zha/)** | `zha` | Zigbee | ✅ | ✅ | Native HA Zigbee Home Automation integration. |
| **[Schlage WiFi](https://www.home-assistant.io/integrations/schlage/)** | `schlage` | Wi-Fi | ❌ | ✅ | Virtual slot mapping by prefixing tags to code names. |
| **[Local Akuvox](https://github.com/firstof9/ha-local-akuvox)** | `local_akuvox` | LAN | ✅ | ✅ | Virtual slot mapping by tagging door controller user names. |
| **[Matter](https://www.home-assistant.io/integrations/matter/)** | `matter` | Matter | ⏳ | ⏳ | Standardized Matter Lock Cluster PIN credential management. |
| **[Nuki](https://www.home-assistant.io/integrations/nuki/)** | `nuki` | Local API | ⏳ | ⏳ | Nuki Keypad PIN management. |
| **[Tedee](https://www.home-assistant.io/integrations/tedee/)** | `tedee` | Cloud/Local | ⏳ | ⏳ | Tedee Keypad PIN management. |
<!-- markdownlint-enable MD013 -->

## Installation

Please visit this project's
[Wiki](https://github.com/FutureTense/keymaster/wiki) for the latest
installation and update procedure.

## Zigbee2MQTT Support

Keymaster supports Zigbee locks integrated via Zigbee2MQTT. Because Keymaster
needs to read and write PIN codes directly from the lock, you **must** enable
PIN code exposure in Zigbee2MQTT.

To do this, ensure `expose_pin` is set to `true` in your Zigbee2MQTT settings
for the lock. For example, in your `configuration.yaml` for Zigbee2MQTT:

```yaml
devices:
  '0x000d6f000d6f000d':
    friendly_name: front_door_lock
    expose_pin: true
```

Without this setting, Keymaster will not be able to retrieve or set user codes
on the lock.
