from datetime import datetime, timedelta, timezone
from io import StringIO
import re
import subprocess
import sys
from pathlib import Path

from tools.local_stack_log import write_lines


def test_each_line_has_time_offset_and_console_copy():
    output, console = StringIO(), StringIO()
    clock = lambda: datetime(2026, 10, 20, 12, 34, 56, 123000,
                             tzinfo=timezone(timedelta(hours=4)))
    write_lines(StringIO('Worker started\n\n  traceback detail\nالعربية'), output, console, now=clock)
    assert output.getvalue() == console.getvalue()
    assert output.getvalue().splitlines() == [
        '[2026-10-20T12:34:56.123+04:00] Worker started',
        '[2026-10-20T12:34:56.123+04:00] ',
        '[2026-10-20T12:34:56.123+04:00]   traceback detail',
        '[2026-10-20T12:34:56.123+04:00] العربية',
    ]


def test_closed_console_does_not_stop_file_logging():
    class ClosedConsole:
        def write(self, text):
            raise BrokenPipeError()
    output = StringIO()
    write_lines(StringIO('first\nsecond\n'), output, ClosedConsole())
    assert len(output.getvalue().splitlines()) == 2
    assert 'second' in output.getvalue()


def test_cli_appends_timestamped_lines_without_console_duplication(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'local_stack_log.py'
    log = tmp_path / 'stack.log'
    log.write_text('Existing undated history\n')
    result = subprocess.run([sys.executable, str(script), str(log)],
                            input='new entry\n', text=True, capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout == ''
    lines = log.read_text().splitlines()
    assert lines[0] == 'Existing undated history'
    assert re.match(r'^\[\d{4}-\d{2}-\d{2}T.+[+-]\d{2}:\d{2}\] new entry$', lines[1])
