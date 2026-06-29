#!/usr/bin/env python3
"""Small serial helper for the Arduino Mega AT28C256 programmer."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable


def token(value: str) -> str:
    """Normalize a user number token for the firmware.

    The firmware accepts decimal, 0x-prefixed hex, or bare hex containing A-F.
    Prefix all helper-script numbers with 0x to avoid ambiguity.
    """
    n = int(value, 0 if value.lower().startswith("0x") else 16)
    return f"0x{n:X}"


def open_port(args: argparse.Namespace):
    try:
        import serial
    except ImportError:  # pragma: no cover - depends on local environment
        print("pyserial is required: python -m pip install pyserial", file=sys.stderr)
        raise SystemExit(2)

    ser = serial.Serial(args.port, args.baud, timeout=args.timeout)
    time.sleep(args.reset_delay)
    ser.reset_input_buffer()
    return ser


def run_command(args: argparse.Namespace, words: Iterable[str]) -> int:
    command = " ".join(words)
    with open_port(args) as ser:
        ser.write((command + "\n").encode("ascii"))
        ser.flush()

        deadline = time.monotonic() + args.command_timeout
        saw_ok = False
        saw_err = False

        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").rstrip("\r\n")
            if line == "> ":
                continue
            if line.startswith("> "):
                line = line[2:]
            if line:
                print(line)
            if line.startswith("OK") or line == "OK":
                saw_ok = True
                break
            if line.startswith("ERR"):
                saw_err = True
                break

        if saw_ok:
            return 0
        if saw_err:
            return 1
        print("Timed out waiting for OK/ERR from programmer", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serial helper for the AT28C256 Arduino Mega programmer")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=0.2, help="Serial read timeout in seconds")
    parser.add_argument("--reset-delay", type=float, default=2.0, help="Delay after opening port; Mega resets on serial open")
    parser.add_argument("--command-timeout", type=float, default=10.0, help="Overall command timeout in seconds")

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show programmer status")
    sub.add_parser("help", help="Show firmware help")

    read = sub.add_parser("read", help="Read bytes as compact hex")
    read.add_argument("address")
    read.add_argument("length", nargs="?", default="1")

    dump = sub.add_parser("dump", help="Read bytes as a hex dump")
    dump.add_argument("address")
    dump.add_argument("length", nargs="?", default="128")

    write = sub.add_parser("write", help="Write bytes")
    write.add_argument("address")
    write.add_argument("bytes", nargs="+")

    verify = sub.add_parser("verify", help="Verify bytes")
    verify.add_argument("address")
    verify.add_argument("bytes", nargs="+")

    fill = sub.add_parser("fill", help="Fill a range with one byte")
    fill.add_argument("address")
    fill.add_argument("length")
    fill.add_argument("byte")

    raw = sub.add_parser("raw", help="Send a raw firmware command")
    raw.add_argument("words", nargs=argparse.REMAINDER)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "status":
        words = ["S"]
    elif args.cmd == "help":
        words = ["?"]
    elif args.cmd == "read":
        words = ["R", token(args.address), token(args.length)]
    elif args.cmd == "dump":
        words = ["D", token(args.address), token(args.length)]
    elif args.cmd == "write":
        words = ["W", token(args.address), *(token(b) for b in args.bytes)]
    elif args.cmd == "verify":
        words = ["V", token(args.address), *(token(b) for b in args.bytes)]
    elif args.cmd == "fill":
        words = ["F", token(args.address), token(args.length), token(args.byte)]
    elif args.cmd == "raw":
        if not args.words:
            parser.error("raw requires command words")
        words = args.words
    else:  # pragma: no cover
        parser.error(f"unknown command {args.cmd}")

    return run_command(args, words)


if __name__ == "__main__":
    raise SystemExit(main())
