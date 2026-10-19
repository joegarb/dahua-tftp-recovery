#!/usr/bin/env python3
"""Minimal read-only TFTP server for Dahua recovery. Logs every request.

Supports the blksize/tsize/timeout options the bootloader asks for. Once the camera fetches the
done marker, later requests for upgrade_info are ignored so the camera boots instead of reflashing.
"""
import argparse, os, socket, struct, threading, time

RRQ, DATA, ACK, ERR, OACK = 1, 3, 4, 5, 6
DONE = ".FLASHING_DONE_STOP_TFTP_NOW"
done = threading.Event()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def serve(root, bind, client, name, opts):
    path = os.path.join(root, os.path.basename(name))
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((bind, 0))
    s.settimeout(3)
    if not os.path.isfile(path):
        log(f"  not found: {name}")
        s.sendto(struct.pack("!HH", ERR, 1) + b"File not found\0", client)
        return
    data = open(path, "rb").read()
    blksize = 512
    reply = {}
    if "blksize" in opts:
        blksize = max(8, min(int(opts["blksize"]), 1468))
        reply["blksize"] = str(blksize)
    if "tsize" in opts:
        reply["tsize"] = str(len(data))
    if "timeout" in opts:
        reply["timeout"] = opts["timeout"]

    def send_wait(pkt, want):
        for _ in range(8):
            s.sendto(pkt, client)
            try:
                while True:
                    r, addr = s.recvfrom(1024)
                    if addr != client:
                        continue
                    op, blk = struct.unpack("!HH", r[:4])
                    if op == ACK and blk == want:
                        return True
                    if op == ERR:
                        log(f"  client error during {name}: {r[4:].rstrip(b'\\0')!r}")
                        return False
            except socket.timeout:
                continue
        log(f"  gave up on {name} at block {want}")
        return False

    if reply:
        body = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in reply.items())
        if not send_wait(struct.pack("!H", OACK) + body, 0):
            return
    for i in range(len(data) // blksize + 1):
        blk = (i + 1) & 0xFFFF
        if not send_wait(struct.pack("!HH", DATA, blk) + data[i * blksize:(i + 1) * blksize], blk):
            return
    log(f"  sent {name} ({len(data)} bytes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", help="folder written by prepare.py")
    ap.add_argument("--bind", default="192.168.254.254", help="address to listen on (default: %(default)s)")
    ap.add_argument("--port", type=int, default=69, help="port to listen on (default: %(default)s)")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((args.bind, args.port))
    log(f"serving {root} on {args.bind}:{args.port}; Ctrl-C to stop")
    while True:
        pkt, client = srv.recvfrom(2048)
        if struct.unpack("!H", pkt[:2])[0] != RRQ:
            continue
        parts = pkt[2:].split(b"\0")
        name = parts[0].decode(errors="replace")
        opts = {parts[i].decode().lower(): parts[i + 1].decode() for i in range(2, len(parts) - 1, 2) if parts[i]}
        log(f"RRQ from {client[0]}: {name} {opts}")
        if name == DONE:
            done.set()
            log("*** camera reports flashing done ***")
        elif done.is_set() and name.startswith("upgrade_info"):
            # Stay silent so the camera times out and boots normally.
            log("  already flashed; ignoring")
            continue
        threading.Thread(target=serve, args=(root, args.bind, client, name, opts), daemon=True).start()


if __name__ == "__main__":
    main()
