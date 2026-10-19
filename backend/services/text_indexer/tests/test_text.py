from __future__ import annotations

import unittest
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.services.text_indexer.config import Settings
from backend.services.text_indexer.text import chunks, classify, normalize
from backend.services.text_indexer.tika import (
    ExtractionError, extract, extract_pdf, pdf_native_text_is_sufficient,
    pdf_page_count,
)
from backend.services.text_indexer.worker import Worker


class TextPolicyTests(unittest.TestCase):
    def test_normalization_removes_controls_and_bounds_chunks(self):
        value = normalize("alpha\x00  beta\r\n\r\n\r\ngamma")
        self.assertEqual(value, "alpha beta\n\ngamma")
        result = chunks("word " * 12_000)
        self.assertTrue(result)
        self.assertTrue(all(len(chunk.text) <= 20_000 for chunk in result))

    def test_language_policy(self):
        self.assertEqual(classify("This is short.")[0], "short")
        self.assertEqual(classify("SELECT value FROM table WHERE id=1")[0], "code_like")
        self.assertEqual(classify("The approved records policy provides reliable evidence. " * 8), ("english", "en"))
        self.assertEqual(classify("توفر سياسة السجلات المعتمدة أدلة موثوقة للمؤسسة. " * 8), ("arabic", "ar"))

    def test_pdf_page_limit_fails_before_extraction(self):
        completed=__import__('subprocess').CompletedProcess(["pdfinfo"],0,"Pages: 1001\n","")
        with patch("backend.services.text_indexer.tika.subprocess.run",return_value=completed):
            self.assertEqual(pdf_page_count(Path("document.pdf")),1001)
        with patch("backend.services.text_indexer.tika.pdf_page_count",return_value=1001), \
             patch("backend.services.text_indexer.tika.extract") as tika_extract:
            with self.assertRaisesRegex(ExtractionError,"page limit"):
                extract_pdf(Path("/tika"),Path("/tmp/document.pdf"),120,1000,1024)
            tika_extract.assert_not_called()

    def test_pdf_with_sufficient_native_text_skips_rendering_and_ocr(self):
        native = "This page already contains searchable native text. " * 20
        with patch("backend.services.text_indexer.tika.pdf_page_count", return_value=2), \
             patch("backend.services.text_indexer.tika.extract", return_value=native), \
             patch("backend.services.text_indexer.tika.subprocess.run") as render, \
             patch("backend.services.text_indexer.tika.extract_image_ocr") as ocr:
            text, ocr_used = extract_pdf(
                Path("/tika"), Path("/tmp/document.pdf"), 120, 1000, 1024,
            )
        self.assertEqual(text, native)
        self.assertFalse(ocr_used)
        render.assert_not_called()
        ocr.assert_not_called()

    def test_pdf_native_text_density_gate_keeps_text_poor_documents_on_ocr_path(self):
        self.assertTrue(pdf_native_text_is_sufficient("word " * 100, 2))
        self.assertFalse(pdf_native_text_is_sufficient("cover page", 20))

    def test_text_poor_pdf_still_uses_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "document.pdf"
            source.write_bytes(b"pdf")

            def render_pages(command, **_kwargs):
                prefix = Path(command[-1])
                prefix.with_name(prefix.name + "-1.png").write_bytes(b"one")
                prefix.with_name(prefix.name + "-2.png").write_bytes(b"two")
                return __import__('subprocess').CompletedProcess(command, 0, "", "")

            ocr_text = "ن" * 30
            with patch("backend.services.text_indexer.tika.pdf_page_count", return_value=2), \
                 patch("backend.services.text_indexer.tika.extract", return_value="cover"), \
                 patch("backend.services.text_indexer.tika.subprocess.run", side_effect=render_pages), \
                 patch("backend.services.text_indexer.tika.extract_image_ocr", return_value=ocr_text) as ocr:
                text, ocr_used = extract_pdf(
                    Path("/tika"), source, 120, 1000, 1024,
                )
        self.assertEqual(text, f"{ocr_text}\n\n{ocr_text}")
        self.assertTrue(ocr_used)
        self.assertEqual(ocr.call_count, 2)

    def test_tika_fork_failure_is_retryable_extractor_unavailable(self):
        completed = __import__('subprocess').CompletedProcess(
            ["java"], 1, "", "ServerInitializationException: couldn't connect to server",
        )
        with patch("backend.services.text_indexer.tika.app_jar", return_value=Path("tika.jar")), \
             patch("backend.services.text_indexer.tika.subprocess.run", return_value=completed):
            with self.assertRaises(ExtractionError) as raised:
                extract(Path("/tika"), Path("/tmp/document.txt"), 120)
        self.assertEqual(raised.exception.code, "extractor_unavailable")
        self.assertEqual(raised.exception.summary, "Tika fork parser failed to initialize")
        self.assertTrue(raised.exception.retryable)

    def test_tika_unknown_process_failure_does_not_claim_content_is_corrupt(self):
        completed = __import__('subprocess').CompletedProcess(["java"], 1, "", "exit 1")
        with patch("backend.services.text_indexer.tika.app_jar", return_value=Path("tika.jar")), \
             patch("backend.services.text_indexer.tika.subprocess.run", return_value=completed):
            with self.assertRaises(ExtractionError) as raised:
                extract(Path("/tika"), Path("/tmp/document.txt"), 120)
        self.assertEqual(raised.exception.code, "extractor_unavailable")
        self.assertTrue(raised.exception.retryable)

    def test_tika_reports_corrupt_only_with_malformed_content_evidence(self):
        completed = __import__('subprocess').CompletedProcess(
            ["java"], 1, "", "TikaException: malformed document structure",
        )
        with patch("backend.services.text_indexer.tika.app_jar", return_value=Path("tika.jar")), \
             patch("backend.services.text_indexer.tika.subprocess.run", return_value=completed):
            with self.assertRaises(ExtractionError) as raised:
                extract(Path("/tika"), Path("/tmp/document.bin"), 120)
        self.assertEqual(raised.exception.code, "corrupt")
        self.assertFalse(raised.exception.retryable)

    def test_startup_recovery_removes_only_old_owned_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); stale=root/"wathiq-index-stale"; recent=root/"wathiq-index-recent"; unrelated=root/"keep"
            stale.mkdir(); recent.mkdir(); unrelated.mkdir()
            old=time.time()-7200; os.utime(stale,(old,old))
            settings=Settings("http://127.0.0.1:8000","wti_x","test",Path("/tika"),4,5,60,120,
                              100,1000,100,200,10,1000,root,1,100)
            worker=object.__new__(Worker); worker.settings=settings
            with self.assertRaisesRegex(RuntimeError,'legacy_indexer_temporary_cleanup_required'):worker.recover_temporary_files()
            self.assertFalse(stale.exists()); self.assertTrue(recent.exists()); self.assertTrue(unrelated.exists())

    def test_startup_recovery_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for number in range(3):
                entry=root/f"wathiq-index-{number}"; entry.mkdir()
                old=time.time()-7200-number; os.utime(entry,(old,old))
            settings=Settings("http://127.0.0.1:8000","wti_x","test",Path("/tika"),4,5,60,120,
                              100,1000,100,200,10,1000,root,1,2)
            worker=object.__new__(Worker); worker.settings=settings
            with self.assertRaisesRegex(RuntimeError,'legacy_indexer_temporary_cleanup_required'):worker.recover_temporary_files()
            self.assertEqual(len(list(root.iterdir())),1)
            self.assertEqual(worker.recover_temporary_files(),1)
            self.assertFalse(list(root.iterdir()))

    def test_startup_recovery_tolerates_another_worker_removing_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); stale=root/"wathiq-index-stale"; stale.mkdir()
            old=time.time()-7200; os.utime(stale,(old,old))
            settings=Settings("http://127.0.0.1:8000","wti_x","test",Path("/tika"),4,5,60,120,
                              100,1000,100,200,10,1000,root,1,100)
            worker=object.__new__(Worker); worker.settings=settings
            with patch("backend.services.text_indexer.worker.shutil.rmtree", side_effect=FileNotFoundError):
                with self.assertRaisesRegex(RuntimeError,'legacy_indexer_temporary_cleanup_required'):worker.recover_temporary_files()


if __name__ == "__main__":
    unittest.main()
