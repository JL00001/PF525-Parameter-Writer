"""Command line interface for the PowerFlex 525 tools.

    python Main.py --ip 192.168.1.143 read 41
    python Main.py --ip 192.168.1.143 write 41 100            # dry run: shows the change
    python Main.py --ip 192.168.1.143 write 41 100 --apply    # actually writes
    python Main.py --discover 15 health --csv health.csv
    python Main.py --ip-file drives.txt load "Full Drive Parameter Template.xlsx" --apply
    python Main.py --discover 15 dump -o "Drive Parameter Dump"

Anything that changes a drive is a dry run unless you pass --apply (or --fix / --yes).
Run ``python Main.py --help`` or ``python Main.py <command> --help`` for details.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pf525 import ConfigError, ConfirmationRequired, HealthConfig, Network, PF525Error
from pf525.constants import DEFAULT_BACKUP_DIR
from pf525.labels import label

DEFAULT_CONFIGS = ("DriveHealthConfig.toml", "DriveHealthConfig.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Main.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", action="append", default=[], metavar="IP",
                        help="drive IP address (repeatable)")
    parser.add_argument("--ip-file", metavar="FILE",
                        help="text file with one drive IP per line ('#' starts a comment)")
    parser.add_argument("--discover", type=float, metavar="SECONDS",
                        help="broadcast for PowerFlex 525 drives for this long before running")
    parser.add_argument("--workers", type=int, default=16, help="drives handled in parallel (default 16)")
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR,
                        help=f"where pre-write backups go (default ./{DEFAULT_BACKUP_DIR})")
    parser.add_argument("--no-backup", action="store_true", help="do not save backups before writing")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="-v = info, -vv = debug (default shows warnings only)")
    parser.add_argument("--log-file", metavar="FILE", help="also log to this file")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="list the PowerFlex 525 drives found on the network")

    p = sub.add_parser("read", help="read one parameter from every drive")
    p.add_argument("parameter", type=int)

    p = sub.add_parser("write", help="write one parameter on every drive (dry run unless --apply)")
    p.add_argument("parameter", type=int)
    p.add_argument("value", type=int)
    p.add_argument("--apply", action="store_true", help="actually write")

    p = sub.add_parser("search", help="list drives whose parameter differs from VALUE")
    p.add_argument("parameter", type=int)
    p.add_argument("value", type=int)
    p.add_argument("--matching", action="store_true", help="list drives that equal VALUE instead")

    p = sub.add_parser("dump", help="save every parameter of every drive to an Excel file")
    p.add_argument("-o", "--output", default="Drive Parameter Dump")

    p = sub.add_parser("load", help="write the values in an Excel sheet (dry run unless --apply)")
    p.add_argument("file")
    p.add_argument("--apply", action="store_true", help="actually write")
    p.add_argument("--add-sheet-drives", action="store_true",
                   help="also write to drives named in the sheet that were not given with --ip/--discover")

    p = sub.add_parser("health", help="check drives against DriveHealthConfig")
    p.add_argument("--config", help="health config (.toml or .json); default DriveHealthConfig.toml/.json")
    p.add_argument("--fix", action="store_true", help="write the proposed fixes to the drives")
    p.add_argument("--dry-run", action="store_true", help="with --fix: show the writes without making them")
    p.add_argument("--csv", metavar="FILE", help="also save the findings as CSV")

    p = sub.add_parser("autotune", help="autotune drives (STARTS THE MOTORS)")
    p.add_argument("--network", metavar="CIDR", help="only drives inside this network, e.g. 192.168.1.0/24")
    p.add_argument("--yes", action="store_true", help="confirm that the machinery is clear")

    p = sub.add_parser("restore", help="write a backup file back to its drive (needs exactly one --ip)")
    p.add_argument("file")
    p.add_argument("--apply", action="store_true", help="actually write")
    return parser


def configure_logging(verbosity: int, log_file: str | None) -> None:
    level = logging.DEBUG if verbosity >= 2 else logging.INFO if verbosity == 1 else logging.WARNING
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(level=level, handlers=handlers, force=True,
                        format="%(asctime)s|%(name)-22s| %(levelname)-8s| %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")


def read_ip_file(path: str) -> list[str]:
    lines = Path(path).read_text().splitlines()
    return [line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()]


def make_network(args) -> Network:
    network = Network(max_workers=args.workers,
                      backup_dir=None if args.no_backup else args.backup_dir)
    for ip in [*args.ip, *(read_ip_file(args.ip_file) if args.ip_file else [])]:
        network.add_drive(ip)
    seconds = args.discover if args.discover is not None else (10.0 if args.command == "discover" else None)
    if seconds:
        print(f"Looking for drives for {seconds:g} s ...", file=sys.stderr)
        network.discover(seconds)
    return network


def print_errors(errors) -> None:
    for ip, exc in sorted(errors.items()):
        print(f"{ip}: ERROR {exc}", file=sys.stderr)


def print_writes(batch, dry_run: bool) -> None:
    for ip, results in sorted(batch.values.items()):
        results = results if isinstance(results, list) else [results]
        changes = [r for r in results if r.status != "unchanged"]
        print(f"{ip}: {len(changes)} change(s), {len(results) - len(changes)} already correct")
        for r in changes:
            print(f"    {r}")
    print_errors(batch.errors)
    if dry_run:
        print("\nDry run - nothing was written. Re-run with --apply to write.")


def run(args) -> int:
    network = make_network(args)

    if args.command == "restore":
        if len(network.drives) != 1:
            raise ConfigError("restore needs exactly one drive: pass a single --ip")
        (drive,) = network.drives.values()
        results = drive.restore(args.file, dry_run=not args.apply,
                                backup_dir=None if args.no_backup else args.backup_dir)
        for r in results:
            print(r)
        return 0 if all(r.ok for r in results) else 1

    if not network.drives and not (args.command == "load" and args.add_sheet_drives):
        if args.command == "discover":
            print("No PowerFlex 525 drives found.")
            return 1
        raise ConfigError("No drives. Use --ip, --ip-file or --discover SECONDS.")

    if args.command == "discover":
        for ip in sorted(network.drives):
            print(ip)
        return 0

    if args.command == "read":
        batch = network.read(args.parameter)
        print(f"P{args.parameter} {label(args.parameter)}")
        for ip, value in sorted(batch.values.items()):
            print(f"  {ip:15} {value}")
        print_errors(batch.errors)
        return 0 if batch.ok else 1

    if args.command == "write":
        batch = network.write(args.parameter, args.value, dry_run=not args.apply)
        print_writes(batch, dry_run=not args.apply)
        return 0 if batch.ok and all(r.ok for r in batch.values.values()) else 1

    if args.command == "search":
        batch = network.search(args.parameter, args.value, match=args.matching)
        verb = "equal" if args.matching else "differ from"
        print(f"Drives whose P{args.parameter} {label(args.parameter)} {verb} {args.value}:")
        for ip, value in sorted(batch.values.items()):
            print(f"  {ip:15} {value}")
        print_errors(batch.errors)
        return 0 if batch.ok else 1

    if args.command == "dump":
        result = network.dump(args.output)
        print(f"Saved {result.path}")
        print_errors(result.errors)
        return 0 if not result.errors else 1

    if args.command == "load":
        batch = network.load_parameters_from_excel(args.file, dry_run=not args.apply,
                                                   add_missing=args.add_sheet_drives)
        print_writes(batch, dry_run=not args.apply)
        return 0 if batch.ok and all(r.ok for rs in batch.values.values() for r in rs) else 1

    if args.command == "health":
        config_path = args.config or next((c for c in DEFAULT_CONFIGS if Path(c).exists()), None)
        if config_path is None:
            raise ConfigError(f"No health config found (looked for {', '.join(DEFAULT_CONFIGS)})")
        report = network.health(HealthConfig.from_file(config_path), fix=args.fix, dry_run=args.dry_run)
        print(report.format())
        if args.csv:
            report.to_csv(args.csv)
            print(f"\nFindings saved to {args.csv}")
        return 0 if not report.unresolved and not report.errors else 1

    if args.command == "autotune":
        batch = network.autotune(network=args.network, confirm=args.yes)
        for ip, result in sorted(batch.values.items()):
            print(f"{ip}: {'OK, Motor Rr = ' + str(result.rr_after) if result.success else 'FAILED - ' + result.reason}")
        print_errors(batch.errors)
        return 0 if batch.ok and all(r.success for r in batch.values.values()) else 1

    raise AssertionError(args.command)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose, args.log_file)
    try:
        return run(args)
    except ConfirmationRequired as exc:
        print(f"{exc}\nRe-run with --yes to proceed.", file=sys.stderr)
        return 2
    except (ConfigError, PF525Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
