"""Owned temporary files with durable non-content receipts and cleanup acks.

A copy is registered before content is written; cleanup acknowledgment follows
real deletion. Crashed owners leave a receipt for bounded startup recovery.
An inherited flock keeps recovery away from a still-running converter child.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4
import fcntl,json,os,shutil

_FDS=ContextVar('processing_copy_fds',default=())
RECEIPT='receipt.json'
LOCK='.lock'


def working_copy_fds():return _FDS.get()


def _erase(directory):
    for entry in directory.iterdir():
        if entry.name in (RECEIPT,LOCK):continue
        if entry.is_dir() and not entry.is_symlink():shutil.rmtree(entry)
        else:entry.unlink(missing_ok=True)


def cleanup_owned(directory,metadata,acknowledge):
    with (directory/LOCK).open('ab') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        _erase(directory);acknowledge(metadata);shutil.rmtree(directory);return True


@contextmanager
def workspace(root,metadata,register,acknowledge):
    root=Path(root);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    token=str(uuid4());directory=root/('wathiq-processing-'+token);directory.mkdir(mode=0o700)
    metadata={**metadata,'token':token}
    (directory/RECEIPT).write_text(json.dumps(metadata));os.chmod(directory/RECEIPT,0o600)
    with (directory/LOCK).open('xb') as lock:
        os.chmod(directory/LOCK,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        state=_FDS.set((*_FDS.get(),lock.fileno()))
        try:
            register(metadata)
            yield directory
        finally:
            _FDS.reset(state)
            lock.close()
            cleanup_owned(directory,metadata,acknowledge)  # A live child or error keeps the receipt.


def recover(root,acknowledge,limit=100):
    root=Path(root);root.mkdir(mode=0o700,parents=True,exist_ok=True);removed=0
    # Never follow links or scan outside this service's configured owned root.
    for directory in sorted(root.glob('wathiq-processing-*'))[:limit]:
        if directory.is_symlink() or not directory.is_dir():continue
        try:
            with (directory/LOCK).open('ab') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:continue
                metadata=json.loads((directory/RECEIPT).read_text())
                if directory.name!='wathiq-processing-'+metadata['token']:continue
                _erase(directory);acknowledge(metadata);shutil.rmtree(directory);removed+=1
        except FileNotFoundError:continue
    return removed
