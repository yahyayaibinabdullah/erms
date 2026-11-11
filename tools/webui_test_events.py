"""Append-only evidence streams for owned, disposable browser tests.

Keep handles open for a process/run. Reopening logs on every request or polling
iteration can block the measured event loop. Writers flush each complete row;
readers consume only newly appended complete lines. No production code imports
this module, and these streams must never be rotated or truncated during a run.

Reader state belongs to one Acceptance run and one filename in its unique output
directory. Each read refreshes it from appended bytes; shutdown closes it and a
new run creates new readers. Missing files return no events until created;
malformed complete rows fail loudly. Callers must treat event dictionaries as
read-only. Evidence is never shared between browser-run directories.
"""
import atexit
import json
from pathlib import Path


class EventWriter:
    def __init__(self, path):
        self.file = Path(path).open('a', encoding='utf-8')
        atexit.register(self.close)

    def append(self, event):
        self.file.write(json.dumps(event) + '\n')
        self.file.flush()

    def close(self):
        self.file.close()


class EventReader:
    def __init__(self, path):
        self.path = Path(path)
        self.file = None
        self.pending = b''
        self.rows = []

    def read(self):
        if self.file is None:
            try:
                self.file = self.path.open('rb')
            except FileNotFoundError:
                return []
        incoming = self.pending + self.file.read()
        lines = incoming.split(b'\n')
        self.pending = lines.pop()
        self.rows.extend(json.loads(line) for line in lines)
        return list(self.rows)

    def close(self):
        if self.file is not None:
            self.file.close()
