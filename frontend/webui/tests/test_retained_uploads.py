"""Retained retry files remain readable after the upload route releases them."""
from io import BytesIO
from tempfile import SpooledTemporaryFile

import pytest

from frontend.webui.upload_buffers import retain_upload_file


@pytest.mark.parametrize('disk',[False,True])
def test_owned_file_preserves_full_content_after_original_closes(disk):
    content=b'First bytes\x00\xff\n'+b'File content '*200000
    source=SpooledTemporaryFile(max_size=1024) if disk else BytesIO()
    source.write(content)
    source.seek(0)
    retained,size=retain_upload_file(source)
    source.close()
    try:
        assert size==len(content)
        assert retained.read()==content
        retained.seek(0)
        assert retained.read()==content  # A retry receives exactly the same bytes.
    finally:
        retained.close()
    assert retained.closed
