"""Timestamp merged stack output as it arrives; optionally mirror to console."""
import argparse
from datetime import datetime
from pathlib import Path
import signal
import sys


def write_lines(source, output, console=None, now=None):
    now = now or (lambda: datetime.now().astimezone())
    for line in source:
        message = line.removesuffix('\n')
        entry = f'[{now().isoformat(timespec="milliseconds")}] {message}\n'
        output.write(entry)
        output.flush()
        if console is not None:
            try:
                console.write(entry)
                console.flush()
            except BrokenPipeError:
                # A closed console pipe must not discard the persistent log.
                console = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--console', action='store_true')
    args = parser.parse_args()
    # Ctrl-C belongs to the launcher, which shuts down services and closes the
    # pipe. Keep draining their shutdown messages until EOF.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
    with args.path.open('a', encoding='utf-8') as output:
        write_lines(sys.stdin, output, sys.stdout if args.console else None)


if __name__ == '__main__':
    main()
