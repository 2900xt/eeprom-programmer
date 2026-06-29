# Arduino Mega AT28C256 EEPROM Programmer

Simple PlatformIO firmware for using an Arduino Mega 2560 as a breadboard programmer for a 28C256 parallel EEPROM, specifically the Microchip/Atmel **AT28C256-15PU** / Mouser **556-AT28C25615PU**:

- 256 Kbit EEPROM, organized as 32K x 8
- 5 V operation: 4.5 V to 5.5 V
- 150 ns read access
- DIP-28 package

The firmware exposes a plain 115200 baud serial command prompt. You can use the Arduino/PlatformIO serial monitor directly, or the included helper script.

## Important notes

- This is a **5 V-only breadboard programmer** for the AT28C256-15PU and compatible 28C256 EEPROMs.
- The chip must be powered from the Arduino Mega 5 V and GND rails, with a decoupling capacitor.
- Do not hot-plug the EEPROM while powered.
- Use short breadboard wires. Parallel buses are noisy when wires get long.
- This project performs simple byte writes. The AT28C256 internally handles the erase/write cycle.

## Parts

- Arduino Mega 2560
- AT28C256-15PU EEPROM, DIP-28
- Breadboard
- Jumper wires
- 0.1 uF ceramic capacitor between EEPROM VCC and GND, close to the chip
- Optional: 10 kΩ pull-up resistors from `/CE`, `/OE`, and `/WE` to 5 V while wiring/debugging

## Wiring

Place the AT28C256 across the breadboard center gap with pin 1 at the top-left notch/dot side.

### Power

- EEPROM pin 28 `VCC` -> Arduino `5V`
- EEPROM pin 14 `GND` -> Arduino `GND`
- 0.1 uF capacitor between EEPROM pins 28 and 14

### Address bus

- EEPROM pin 10 `A0`  -> Mega D30
- EEPROM pin 9  `A1`  -> Mega D31
- EEPROM pin 8  `A2`  -> Mega D32
- EEPROM pin 7  `A3`  -> Mega D33
- EEPROM pin 6  `A4`  -> Mega D34
- EEPROM pin 5  `A5`  -> Mega D35
- EEPROM pin 4  `A6`  -> Mega D36
- EEPROM pin 3  `A7`  -> Mega D37
- EEPROM pin 25 `A8`  -> Mega D38
- EEPROM pin 24 `A9`  -> Mega D39
- EEPROM pin 21 `A10` -> Mega D40
- EEPROM pin 23 `A11` -> Mega D41
- EEPROM pin 2  `A12` -> Mega D42
- EEPROM pin 26 `A13` -> Mega D43
- EEPROM pin 1  `A14` -> Mega D44

### Data bus

- EEPROM pin 11 `I/O0` -> Mega D22
- EEPROM pin 12 `I/O1` -> Mega D23
- EEPROM pin 13 `I/O2` -> Mega D24
- EEPROM pin 15 `I/O3` -> Mega D25
- EEPROM pin 16 `I/O4` -> Mega D26
- EEPROM pin 17 `I/O5` -> Mega D27
- EEPROM pin 18 `I/O6` -> Mega D28
- EEPROM pin 19 `I/O7` -> Mega D29

### Control pins

- EEPROM pin 20 `/CE` -> Mega D45
- EEPROM pin 22 `/OE` -> Mega D46
- EEPROM pin 27 `/WE` -> Mega D47

The firmware drives `/CE`, `/OE`, and `/WE` high during setup so the chip is idle by default.

## Build and upload

```bash
cd /home/taha/eeprom-programmer
pio run
pio run -t upload
pio device monitor -b 115200
```

If the serial monitor prints `AT28C256 programmer ready`, press Enter and type `?` for help.

## Serial commands

Numbers may be decimal, `0x` prefixed, or bare hex with A-F characters. Addresses are 0 through `0x7FFF`.

- `?` or `HELP` — show command help
- `S` — show status and pin mapping
- `R <addr> [len]` — read bytes, compact output
- `D <addr> [len]` — read bytes as a hex dump
- `W <addr> <byte> [byte ...]` — write one or more bytes
- `V <addr> <byte> [byte ...]` — verify bytes against EEPROM contents
- `F <addr> <len> <byte>` — fill a range with one repeated byte

Examples:

```text
W 0x0000 0x48 0x65 0x6C 0x6C 0x6F
R 0x0000 5
D 0x0000 32
V 0x0000 0x48 0x65 0x6C 0x6C 0x6F
F 0x0100 16 0xFF
```

## Helper script

The helper uses pyserial and sends the same text commands to the firmware.

Install pyserial in a venv if needed:

```bash
cd /home/taha/eeprom-programmer
python3 -m venv .venv
. .venv/bin/activate
python -m pip install pyserial
```

Examples:

```bash
python scripts/eeprom_tool.py --port /dev/ttyACM0 status
python scripts/eeprom_tool.py --port /dev/ttyACM0 write 0x0000 48 65 6c 6c 6f
python scripts/eeprom_tool.py --port /dev/ttyACM0 read 0x0000 5
python scripts/eeprom_tool.py --port /dev/ttyACM0 dump 0x0000 32
python scripts/eeprom_tool.py --port /dev/ttyACM0 verify 0x0000 48 65 6c 6c 6f
python scripts/eeprom_tool.py --port /dev/ttyACM0 fill 0x0100 16 ff
```

If you do not know the port, try:

```bash
pio device list
```

## Write behavior

For each byte write, the firmware:

1. Disables output with `/OE` high.
2. Drives the address and data buses.
3. Selects the chip with `/CE` low.
4. Pulses `/WE` low.
5. Releases the data bus.
6. Polls reads until the byte matches or a timeout occurs.

This is intentionally simple rather than fast. It is good for breadboard use and easy debugging.
