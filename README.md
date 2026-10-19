# dahua-tftp-recovery

Recover a boot-looping Dahua IP camera (including rebadged ones like Amcrest) by reflashing its
official firmware over TFTP, without opening it up or attaching a serial console.

Two small Python scripts: one turns a vendor firmware `.bin` into a TFTP root the camera's
bootloader can consume, and one serves it.

## Background

Built to rescue an Amcrest IP4M-1051W that sat in a boot loop: solid red LED, pan/tilt sweeping
every 30 seconds to a few minutes (each sweep a reboot), never joining the network. A factory reset
didn't help, and the vendor had nothing to offer for an out-of-warranty unit. The bootloader was
fine, though, and still checks for a recovery server on every boot.

## How it works

- On every boot, Dahua's U-Boot sets itself to `192.168.1.251`, ARPs for `192.168.1.1` (gateway),
  and requests `upgrade_info_7db780a713a4.txt` over TFTP from `192.168.254.254`. Nothing answers on
  a normal network, so it carries on booting.
- If a file comes back with a valid header (a CRC and a fixed magic string), U-Boot runs the
  commands in it. Here those are `tftp <addr> <part>; flwrite` for each firmware part: load it into
  RAM, then write it to flash. `flwrite` reads where to write from the part's own header.
- `prepare.py` builds that file from the official firmware. The `.bin` is a zip with `DH` in place
  of `PK`; its `Install` file lists the parts. The RAM load address differs between chips (and a
  wrong one hangs the camera), so it's read from the recovery commands baked into the firmware's own
  bootloader image (e.g. `dk=tftp 0x02000000 kernel.img`) rather than guessed.
- The bootloader, mini-boot and partition table are never flashed. The bootloader is what runs the
  recovery, and if a write to it goes wrong the only way back is a serial console.
- `tftpd.py` serves the folder and logs every request. When the camera fetches the done marker, it
  stops answering for `upgrade_info`, so the next boot runs the new firmware instead of reflashing.

## Requirements

- Python 3, no dependencies.
- The camera on Ethernet, on the same layer-2 network as the machine running the server. Through a
  home router is fine, including from Wi-Fi.
- Root, to bind port 69 and add addresses.
- The official firmware for your exact model from the vendor. Not included here.

## Usage

1. **Check the camera asks.** Watch for its requests during a boot (each sweep, if it's looping):
   ```sh
   sudo tcpdump -n -e 'port 69 or arp host 192.168.1.1'
   ```
   You should see `who-has 192.168.1.1 tell 192.168.1.251`. Nothing at all means its network
   recovery is off or broken, and this won't help.

2. **Build the TFTP root:**
   ```sh
   python3 prepare.py firmware.bin recovery/
   ```
   It prints the load address it found and the commands it'll run. Check they look sane before going
   further. If it can't find the address, pass `--addr`, but only with a value you're sure of.

3. **Add the addresses the camera expects** (cleared on reboot):
   ```sh
   # macOS
   sudo ifconfig en0 alias 192.168.1.1 netmask 255.255.255.0
   sudo ifconfig en0 alias 192.168.254.254 netmask 255.255.255.255
   # Linux
   sudo ip addr add 192.168.1.1/24 dev eth0
   sudo ip addr add 192.168.254.254/32 dev eth0
   ```

4. **Serve it, then power-cycle the camera** once the first log line appears:
   ```sh
   sudo python3 tftpd.py recovery/
   ```

5. **Leave it alone until it's done** (a few minutes). Expected log:
   ```
   RRQ from 192.168.1.251: upgrade_info_7db780a713a4.txt ...
   RRQ from 192.168.1.251: kernel.img ...
     sent kernel.img (1568244 bytes)
   ...
   *** camera reports flashing done ***
   RRQ from 192.168.1.251: success.txt ...
     not found: success.txt
   ```
   `success.txt` is how the bootloader reports a good flash; the "not found" reply is fine.

6. **Clean up.** Ctrl-C the server and remove the two addresses. The camera reboots onto the new
   firmware and gets an address by DHCP (it may also answer on `192.168.1.108`). Expect it to need
   a new admin password.

## Tested

| Model | Firmware | Load address | Result |
|---|---|---|---|
| Amcrest IP4M-1051W | V2.620.00AC003.0.R | `0x02000000` | Recovered |

That camera was flashed with the same parts and load address `prepare.py` produces, but in a
different order (the order shouldn't matter, since each part's header says where it goes). The
scripts' exact output has been checked end to end against a simulated bootloader, not a camera.

Everything else is untested. Other Dahua-based cameras should work the same way if their bootloader
does TFTP recovery, but check what `prepare.py` prints for your firmware. For example, Amcrest's
IP4M-1041 firmware is a different chip with a load address of `0x22000000` and fewer parts; it
builds fine but hasn't been flashed. Reports for other models are welcome.

## Notes

- A wrong load address hangs the camera as soon as it loads the first part. Nothing has been written
  to flash at that point, so stop the server and power-cycle it.
- Each part is loaded and then written with `tftp ...; flwrite`. If a transfer fails partway,
  `flwrite` still runs and that part is left half-written. The bootloader is untouched, so running
  the recovery again fixes it.
- `tftpd.py --bind 127.0.0.1 --port 6969` is handy for testing without root.

## References

- [Dahua IPC EASY unbricking / recovery over TFTP](https://ipcamtalk.com/threads/dahua-ipc-easy-unbricking-recovery-over-tftp.17189/)
  on IPCamTalk: the method, and the format of `upgrade_info_7db780a713a4.txt`, which forum member
  @resegun worked out.
- [ayushin/dahua-tftp-recover-docker](https://github.com/ayushin/dahua-tftp-recover-docker): a
  working setup for a Dahua VTH15xx. Its `upgrade_info.py` and example command file confirmed the
  header (CRC over the magic string plus the commands) and the `tftp ...; flwrite` pattern.

## License

MIT
