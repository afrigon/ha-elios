# ha-elios

Home Assistant climate integration for Elios air conditioners controlled over
infrared.

The Elios remote protocol is stateful: every keypress transmits the complete
state (power, mode, temperature, fan speed, sleep). `elios.py` synthesizes
these frames from individual controls — a Python port of
[acproto](https://github.com/afrigon/acproto), kept faithful by that project's
golden bit patterns in the test suite.

Frames are transmitted through any `remote` entity that accepts base64
Broadlink packets (`b64:...`), such as
[ha-broadlink6](https://github.com/afrigon/ha-broadlink6) or the core
Broadlink integration. The config flow takes the remote entity plus optional
temperature/humidity sensor entities, shown on the thermostat card as the
current room conditions.

The AC is transmit-only, so entity state is optimistic: it reflects the last
state sent and is restored across restarts. Input is debounced — adjustments
are applied to the card immediately, and one frame is transmitted once the
state has been left untouched for two seconds.

Install by copying `custom_components/elios_ac/` into the Home Assistant
configuration directory, or as a HACS custom repository.
