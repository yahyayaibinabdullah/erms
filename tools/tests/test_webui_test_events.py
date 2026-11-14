"""Evidence remains complete while request/poll paths avoid repeated file opens."""
import json
from pathlib import Path
import pytest
from tools.webui_test_events import EventReader, EventWriter


def test_live_append_is_visible_and_existing_handles_are_reused(tmp_path, monkeypatch):
    path=tmp_path/'events.jsonl';writer=EventWriter(path);reader=EventReader(path)
    writer.append({'event':'first'});assert reader.read()==[{'event':'first'}]
    original=Path.open
    def no_reopen(self,*args,**kwargs):
        if self==path:raise AssertionError('Request/poll path reopened its evidence stream')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',no_reopen)
    try:
        for number in range(20):
            writer.append({'sequence':number})
            observed=reader.read()
            assert len(observed)==number+2 and observed[-1]=={'sequence':number}
        assert reader.read()==observed
    finally:
        reader.close();writer.close()


def test_reader_waits_for_complete_utf8_line(tmp_path):
    path=tmp_path/'events.jsonl';raw=json.dumps({'label':'وثيقة'},ensure_ascii=False).encode()+b'\n'
    boundary=raw.index('و'.encode())+1
    path.write_bytes(raw[:boundary]);reader=EventReader(path)
    try:
        assert reader.read()==[]
        with path.open('ab') as file:file.write(raw[boundary:])
        assert reader.read()==[{'label':'وثيقة'}]
    finally:reader.close()


def test_reader_handles_file_created_after_first_poll(tmp_path):
    path=tmp_path/'events.jsonl';reader=EventReader(path)
    assert reader.read()==[]
    writer=EventWriter(path)
    try:
        writer.append({'status':200});assert reader.read()==[{'status':200}]
    finally:reader.close();writer.close()


def test_completed_corrupt_evidence_is_not_silently_ignored(tmp_path):
    path=tmp_path/'events.jsonl';path.write_text('not json\n');reader=EventReader(path)
    try:
        with pytest.raises(json.JSONDecodeError):reader.read()
    finally:reader.close()


def test_caller_cannot_remove_cached_rows(tmp_path):
    path=tmp_path/'events.jsonl';writer=EventWriter(path);reader=EventReader(path)
    try:
        writer.append({'event':'required'});reader.read().clear()
        assert reader.read()==[{'event':'required'}]
    finally:reader.close();writer.close()
