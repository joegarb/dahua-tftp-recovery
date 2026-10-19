#!/usr/bin/env python3
"""Build a TFTP recovery folder from an official Dahua (or Dahua-based, e.g. Amcrest) firmware .bin.

The .bin is a zip with "DH" in place of the "PK" magic. Its Install file lists the parts to burn,
and the bootloader's built-in recovery commands give the RAM load address for that chip.
"""
import argparse, io, json, os, re, sys, zipfile, zlib

# The bootloader is never rewritten: it's what runs this recovery, and if a write to it fails the
# camera is unrecoverable without a serial console.
SKIP_TARGETS = {"bootloader", "mini-boot", "partition"}
MAGIC = b"MagicString:c016dcd6-cdeb-45df-9fd0-e821bf0e1e62\n"
DONE = ".FLASHING_DONE_STOP_TFTP_NOW"


def find_load_address(z):
    # Recovery commands like "dk=tftp 0x02000000 kernel.img; flwrite" are baked into the bootloader.
    for name in sorted(z.namelist(), key=lambda n: "boot" not in n):
        m = re.search(rb"\b(?:dk|dr|du|dw)=tftp (0x[0-9a-fA-F]+) ", z.read(name))
        if m:
            return m.group(1).decode(), name
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("firmware", help="official firmware .bin")
    ap.add_argument("out_dir", help="folder to write the TFTP root to")
    ap.add_argument("--addr", help="RAM load address, if it can't be found in the firmware")
    args = ap.parse_args()

    raw = bytearray(open(args.firmware, "rb").read())
    if raw[:2] != b"DH":
        sys.exit(f"{args.firmware} doesn't start with 'DH'; not a Dahua firmware package")
    raw[:2] = b"PK"
    z = zipfile.ZipFile(io.BytesIO(bytes(raw)))
    names = set(z.namelist())

    if "Install" not in names:
        sys.exit("no Install file in the firmware; can't tell which parts to flash")
    install = z.read("Install").decode()
    install = json.loads(install[: install.rindex("}") + 1])
    parts = []
    for cmd in install["Commands"]:
        _, fname, target = cmd.split()
        if fname in names and target not in SKIP_TARGETS:
            parts.append(fname)
    if not parts:
        sys.exit("no flashable parts found in Install")

    addr, source = find_load_address(z)
    if args.addr:
        addr, source = args.addr, "--addr"
    if not addr:
        sys.exit("couldn't find the load address in the firmware; pass --addr (a wrong one freezes the camera)")

    os.makedirs(args.out_dir, exist_ok=True)
    for fname in parts:
        with open(os.path.join(args.out_dir, fname), "wb") as f:
            f.write(z.read(fname))
    cmds = "".join(f"tftp {addr} {p}; flwrite\n" for p in parts) + f"tftp {addr} {DONE}\n"
    open(os.path.join(args.out_dir, "commands.txt"), "w").write(cmds)
    crc = zlib.crc32(cmds.encode(), zlib.crc32(MAGIC))
    with open(os.path.join(args.out_dir, "upgrade_info_7db780a713a4.txt"), "wb") as f:
        f.write(b"CRC:%d\n" % crc + MAGIC + cmds.encode())
    open(os.path.join(args.out_dir, DONE), "w").write("ok\n")

    print(f"Devices:      {install.get('Devices')}")
    print(f"Load address: {addr} (from {source})")
    print(f"Wrote {args.out_dir} with commands:\n{cmds}")


if __name__ == "__main__":
    main()
