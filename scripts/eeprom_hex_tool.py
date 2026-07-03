#!/usr/bin/env python3
"""Write, read, and verify Intel HEX files on the AT28C256 programmer.

Builds on eeprom_tool.py's serial connection handling and sends the same
W/R firmware commands, but keeps a single open connection and chunks large
transfers instead of spawning one connection per byte range.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eeprom_tool  # noqa: E402  (reuse open_port)

EEPROM_SIZE = 32768


class HexFormatError(ValueError):
    pass


def parse_intel_hex(path: str) -> dict[int, int]:
    """Parse an Intel HEX file into a sparse {address: byte} map."""
    image: dict[int, int] = {}
    base = 0
    with open(path, "r") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            if not line.startswith(":"):
                raise HexFormatError(f"{path}:{lineno}: line does not start with ':'")
            try:
                data = bytes.fromhex(line[1:])
            except ValueError as exc:
                raise HexFormatError(f"{path}:{lineno}: invalid hex characters") from exc
            if len(data) < 5:
                raise HexFormatError(f"{path}:{lineno}: record too short")

            count, addr_hi, addr_lo, rectype = data[0], data[1], data[2], data[3]
            if len(data) != count + 5:
                raise HexFormatError(f"{path}:{lineno}: truncated record")
            payload = data[4:4 + count]
            checksum = data[4 + count]
            calc = (-sum(data[:4 + count])) & 0xFF
            if calc != checksum:
                raise HexFormatError(f"{path}:{lineno}: checksum mismatch")

            addr = (addr_hi << 8) | addr_lo

            if rectype == 0x00:  # data
                for i, byte in enumerate(payload):
                    image[base + addr + i] = byte
            elif rectype == 0x01:  # end of file
                break
            elif rectype == 0x02:  # extended segment address
                base = ((payload[0] << 8) | payload[1]) << 4
            elif rectype == 0x04:  # extended linear address
                base = ((payload[0] << 8) | payload[1]) << 16
            elif rectype in (0x03, 0x05):  # start segment/linear address
                continue
            else:
                raise HexFormatError(f"{path}:{lineno}: unsupported record type {rectype:02X}")
    return image


def write_intel_hex(path: str, image: dict[int, int], start: int, length: int, fill: int = 0xFF) -> None:
    with open(path, "w") as f:
        addr = start
        end = start + length
        while addr < end:
            row_len = min(16, end - addr)
            payload = bytes(image.get(a, fill) for a in range(addr, addr + row_len))
            record = bytes([row_len, (addr >> 8) & 0xFF, addr & 0xFF, 0x00]) + payload
            checksum = (-sum(record)) & 0xFF
            f.write(":" + record.hex().upper() + f"{checksum:02X}\n")
            addr += row_len
        f.write(":00000001FF\n")


def image_to_runs(image: dict[int, int]) -> list[tuple[int, list[int]]]:
    """Collapse a sparse address->byte map into sorted contiguous runs."""
    if not image:
        return []
    addrs = sorted(image)
    runs: list[tuple[int, int]] = []
    run_start = addrs[0]
    prev = addrs[0]
    for a in addrs[1:]:
        if a == prev + 1:
            prev = a
            continue
        runs.append((run_start, prev))
        run_start = a
        prev = a
    runs.append((run_start, prev))
    return [(s, [image[a] for a in range(s, e + 1)]) for s, e in runs]


def to_token(n: int) -> str:
    return f"0x{n:X}"


def send_command(ser, words: list[str], timeout: float) -> tuple[bool, list[str]]:
    command = " ".join(words)
    ser.write((command + "\n").encode("ascii"))
    ser.flush()

    deadline = time.monotonic() + timeout
    lines: list[str] = []
    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("ascii", errors="replace").rstrip("\r\n")
        if not line:
            continue
        if line.startswith("> "):
            line = line[2:]
            if not line:
                continue
        lines.append(line)
        if line.startswith("OK"):
            return True, lines
        if line.startswith("ERR"):
            return False, lines
    return False, lines + ["ERR timeout"]


def progress(done: int, total: int) -> None:
    print(f"\r{done}/{total} bytes", end="", file=sys.stderr, flush=True)


def cmd_write(ser, args, image: dict[int, int]) -> int:
    runs = image_to_runs(image)
    total = sum(len(data) for _, data in runs)
    if total == 0:
        print("Nothing to write (empty hex file)")
        return 0

    for start, data in runs:
        if start + len(data) > EEPROM_SIZE:
            print(f"ERR: data at 0x{start:04X}..0x{start + len(data) - 1:04X} exceeds EEPROM size", file=sys.stderr)
            return 1

    written = 0
    for start, data in runs:
        for offset in range(0, len(data), args.chunk_size):
            chunk = data[offset:offset + args.chunk_size]
            addr = start + offset
            words = ["W", to_token(addr), *(to_token(b) for b in chunk)]
            ok, lines = send_command(ser, words, args.command_timeout)
            if not ok:
                print(file=sys.stderr)
                print(f"ERR writing at 0x{addr:04X}: {lines[-1] if lines else 'no response'}", file=sys.stderr)
                return 1
            written += len(chunk)
            progress(written, total)
    print(file=sys.stderr)
    print(f"Wrote {written} bytes across {len(runs)} run(s)")
    return 0


def read_range(ser, args, address: int, length: int) -> dict[int, int] | None:
    image: dict[int, int] = {}
    for offset in range(0, length, args.chunk_size):
        chunk_len = min(args.chunk_size, length - offset)
        addr = address + offset
        words = ["R", to_token(addr), to_token(chunk_len)]
        ok, lines = send_command(ser, words, args.command_timeout)
        if not ok:
            print(file=sys.stderr)
            print(f"ERR reading at 0x{addr:04X}: {lines[-1] if lines else 'no response'}", file=sys.stderr)
            return None
        data_line = next((l for l in lines if l.startswith("DATA")), None)
        if data_line is None:
            print(file=sys.stderr)
            print(f"ERR no DATA line in response at 0x{addr:04X}", file=sys.stderr)
            return None
        actual = [int(x, 16) for x in data_line.split()[2:]]
        for i, b in enumerate(actual):
            image[addr + i] = b
        progress(offset + chunk_len, length)
    print(file=sys.stderr)
    return image


def cmd_verify(ser, args, image: dict[int, int]) -> int:
    runs = image_to_runs(image)
    total = sum(len(data) for _, data in runs)
    if total == 0:
        print("Nothing to verify (empty hex file)")
        return 0

    for start, data in runs:
        if start + len(data) > EEPROM_SIZE:
            print(f"ERR: data at 0x{start:04X}..0x{start + len(data) - 1:04X} exceeds EEPROM size", file=sys.stderr)
            return 1

    checked = 0
    mismatches = 0
    for start, data in runs:
        actual_image = read_range(ser, args, start, len(data))
        if actual_image is None:
            return 1
        for i, expected in enumerate(data):
            addr = start + i
            actual = actual_image[addr]
            if actual != expected:
                mismatches += 1
                print(f"MISMATCH at 0x{addr:04X}: expected 0x{expected:02X} got 0x{actual:02X}")
        checked += len(data)

    if mismatches:
        print(f"FAILED: {mismatches} mismatch(es) out of {checked} bytes")
        return 1
    print(f"OK: {checked} bytes verified")
    return 0


def cmd_read(ser, args) -> int:
    length = args.length if args.length is not None else EEPROM_SIZE - args.address
    if length <= 0 or args.address + length > EEPROM_SIZE:
        print("ERR: read range exceeds EEPROM size", file=sys.stderr)
        return 1

    image = read_range(ser, args, args.address, length)
    if image is None:
        return 1

    write_intel_hex(args.output, image, start=args.address, length=length)
    print(f"Wrote {length} bytes to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write, read, and verify Intel HEX files on the AT28C256 programmer"
    )
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=0.2, help="Serial read timeout in seconds")
    parser.add_argument("--reset-delay", type=float, default=2.0, help="Delay after opening port; Mega resets on serial open")
    parser.add_argument("--command-timeout", type=float, default=10.0, help="Per-command timeout in seconds")
    parser.add_argument(
        "--chunk-size", type=int, default=16,
        help="Bytes per W/R firmware command (default 16; keep <=32, the firmware's input line is 192 chars)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    write = sub.add_parser("write", help="Write an Intel HEX file to the EEPROM")
    write.add_argument("hexfile")
    write.add_argument("--no-verify", action="store_true", help="Skip verification after writing")

    verify = sub.add_parser("verify", help="Verify EEPROM contents against an Intel HEX file")
    verify.add_argument("hexfile")

    read = sub.add_parser("read", help="Read EEPROM contents to an Intel HEX file")
    read.add_argument("output")
    read.add_argument("--address", type=lambda s: int(s, 0), default=0, help="Start address (default 0)")
    read.add_argument("--length", type=lambda s: int(s, 0), default=None, help="Bytes to read (default: to end of EEPROM)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not 1 <= args.chunk_size <= 32:
        parser.error("--chunk-size must be between 1 and 32")

    image = None
    if args.cmd in ("write", "verify"):
        try:
            image = parse_intel_hex(args.hexfile)
        except (OSError, HexFormatError) as exc:
            print(f"ERR: {exc}", file=sys.stderr)
            return 1

    ser = eeprom_tool.open_port(args)
    try:
        if args.cmd == "write":
            rc = cmd_write(ser, args, image)
            if rc == 0 and not args.no_verify:
                print("Verifying...")
                rc = cmd_verify(ser, args, image)
            return rc
        if args.cmd == "verify":
            return cmd_verify(ser, args, image)
        if args.cmd == "read":
            return cmd_read(ser, args)
        parser.error(f"unknown command {args.cmd}")  # pragma: no cover
        return 1
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
