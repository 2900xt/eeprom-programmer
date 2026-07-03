#!/usr/bin/env python3
"""Generate a small Intel HEX file for exercising eeprom_hex_tool.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eeprom_hex_tool as hextool  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a test Intel HEX file")
    parser.add_argument("output", help="Path to write the .hex file")
    parser.add_argument("--address", type=lambda s: int(s, 0), default=0, help="Start address (default 0)")
    parser.add_argument("--length", type=lambda s: int(s, 0), default=None, help="Number of bytes (default: 256 for counter/fill, exact text length for text)")
    parser.add_argument(
        "--pattern", choices=["counter", "fill", "text"], default="counter",
        help="counter: repeating 0x00-0xFF (default), fill: repeated --fill-byte, text: ASCII bytes from --text",
    )
    parser.add_argument("--fill-byte", type=lambda s: int(s, 0), default=0xFF, help="Byte value for --pattern fill")
    parser.add_argument("--text", default="Hello, EEPROM!", help="String for --pattern text")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.pattern == "text":
        text_bytes = args.text.encode("ascii")
        length = max(len(text_bytes), args.length) if args.length is not None else len(text_bytes)
        data = text_bytes
    else:
        length = args.length if args.length is not None else 256
        if args.pattern == "fill":
            data = bytes([args.fill_byte & 0xFF]) * length
        else:
            data = bytes(i & 0xFF for i in range(length))

    if length <= 0:
        parser.error("--length must be positive")
    if args.address + length > hextool.EEPROM_SIZE:
        parser.error(f"address + length exceeds EEPROM size (0x{hextool.EEPROM_SIZE:04X})")

    image = {args.address + i: b for i, b in enumerate(data)}
    hextool.write_intel_hex(args.output, image, start=args.address, length=length)
    print(f"Wrote {length} bytes ({args.pattern}) to {args.output} starting at 0x{args.address:04X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
