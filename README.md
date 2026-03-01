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

## Installation

Please visit this project's
[Wiki](https://github.com/FutureTense/keymaster/wiki) for the latest
installation and update procedure.

## Development


### Local Setup

2. Clone the repository and navigate to the project directory.
3. Create a virtual environment and install dependencies:

   ```bash
   pip install -e ".[dev]"
   ```

4. Install pre-commit hooks:

   ```bash
   pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

### Running Tests

Run the full test suite with coverage:

```bash
pytest tests --cov=custom_components/keymaster --cov-report=term-missing
```

### Linting and Formatting

Run all quality checks via pre-commit:

```bash
pre-commit run --all-files
```
