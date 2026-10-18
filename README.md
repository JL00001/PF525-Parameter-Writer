# PowerFlex 525 tools

Bulk audit and configuration of PowerFlex 525 drives over EtherNet/IP (pycomm3).

```
pip install -r requirements.txt          # Python 3.11+
python Main.py --help
```

## Quick start

```
python Main.py --ip 192.168.1.143 read 41
python Main.py --ip 192.168.1.143 write 41 100             # DRY RUN: shows old -> new
python Main.py --ip 192.168.1.143 write 41 100 --apply     # writes
python Main.py --ip-file drives.txt dump -o "Drive Parameter Dump"
python Main.py --ip-file drives.txt load "Full Drive Parameter Template.xlsx"           # dry run
python Main.py --ip-file drives.txt load "Full Drive Parameter Template.xlsx" --apply
python Main.py --discover 15 health --csv health.csv       # report only
python Main.py --discover 15 health --fix --dry-run        # show the fixes it would make
python Main.py --discover 15 health --fix
python Main.py --ip 192.168.1.143 autotune --yes           # STARTS THE MOTOR
python Main.py --ip 192.168.1.143 restore pf525_backups/192.168.1.143_20261018-141500.json --apply
```

Drives come from `--ip` (repeat it), `--ip-file` (one IP per line, `#` comments) or
`--discover SECONDS`. `-v` / `-vv` show more logging, `--log-file` writes it to a file.

## Safety

Everything that changes a drive goes through `Drive.write_parameters`, which:

* reads the current values first and **skips values that already match**,
* with `--apply` absent (or `dry_run=True`) **changes nothing** and prints `old -> new`,
* if the drive is **running**, refuses parameters that are read-only or
  *Not Writable When Enabled* (decoded from the parameter descriptor),
* **saves the old values** to `pf525_backups/<ip>_<timestamp>.json` before writing
  (`--no-backup` to disable) - undo with `restore`,
* **reads every value back** and reports `verify_failed` if it did not stick.

Autotune refuses a running drive, needs `--yes`, and if the tune does not finish it writes the
old Motor Rr, Start Source and Speed Reference back and reports failure.

## Health scanner

`health` reads each drive once (one batched request) and checks it against the rule table in
`pf525/health.py`. Some rules only report; the rest are fixable with `--fix`. Settings live in
`DriveHealthConfig.toml` (commented) or the original `DriveHealthConfig.json`
(old key names still work). Each key is documented in the `.toml`.

Adding a check is one line in `RULES`:

```python
_expect("static_ip", 128, 1, "drive is using BOOTP instead of a static IP"),
```

## Spreadsheet format

Column A = parameter number, column B = name, row 1 = drive IP addresses (from C onward).
Empty cells are ignored; values must be whole numbers. `dump` writes this layout, `load` reads it.
Drives named in the sheet but not on your drive list are skipped unless you pass `--add-sheet-drives`.

## Values and signedness

Parameters are read as raw unsigned 16-bit values (so Maximum Freq = 40000 reads as 40000).
Writes accept -32768..65535. Use `drive.read_parameter(p, signed=True)` for signed parameters.

## Library use

```python
from pf525 import Network, Drive

net = Network()
net.add_drive("192.168.1.143")
net.write(41, 100, dry_run=True).values        # {ip: WriteResult}

with Drive("192.168.1.143") as d:              # one session for all of these
    d.read_parameters([41, 42, 44])            # {41: ..., 42: ..., 44: ...}
    d.write_parameters({41: 100, 42: 100})
```

The old method names (`single_read_parameter`, `read_pf525_parameter`, `network_parameter_dump`, ...)
still exist as thin wrappers. The old `network_autoTune_drive` / `network_masked_autoTune_drive`
are replaced by `Network.autotune(confirm=True)` on purpose.

## Tests

`pip install pytest && python -m pytest tests`. The tests run against a simulated drive
(`tests/fake_pycomm3.py`), so they check this code's logic but **not** pycomm3's wire encoding or a
real drive. Try a read-only command and a dry-run write on one drive before trusting it on the line.
