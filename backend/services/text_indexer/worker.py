from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import time
import shutil
from pathlib import Path
from uuid import uuid4

import httpx

from .config import MIME_TYPES, Settings
from backend.services.processing_workspace import workspace as owned_workspace,recover as recover_owned
from .text import chunks
from .tika import ExtractionError, extract, extract_image_ocr, extract_pdf, self_test


LOG = logging.getLogger("wathiq.text_indexer")


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.nonce = uuid4().hex
        self.client = httpx.Client(
            base_url=settings.api_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=httpx.Timeout(30, read=180), follow_redirects=False,
        )

    def recover_temporary_files(self) -> int:
        recovered=recover_owned(self.settings.temp_root,self._acknowledge_copy,limit=self.settings.temp_sweep_limit)
        root=self.settings.temp_root
        root.mkdir(mode=0o700,parents=True,exist_ok=True); os.chmod(root,0o700)
        cutoff=time.time()-(self.settings.stale_temp_hours*3600)
        removed=0
        candidates=[]
        for entry in root.iterdir():
            try:
                candidates.append((entry.stat().st_mtime,entry))
            except FileNotFoundError:
                # Another worker may have completed the same bounded startup
                # sweep after this directory listing was produced.
                continue
        # Recovery work is intentionally bounded so startup cannot be held up by
        # an unexpectedly large or hostile temporary directory. Multiple
        # supervised workers can perform this idempotent sweep concurrently.
        for modified,entry in sorted(candidates,key=lambda item:item[0])[:self.settings.temp_sweep_limit]:
            if not entry.name.startswith("wathiq-index-") or modified>cutoff:
                continue
            try:
                if entry.is_dir(): shutil.rmtree(entry)
                else: entry.unlink()
            except FileNotFoundError:
                continue
            removed+=1
        if any(root.glob('wathiq-index-*')):
            raise RuntimeError('legacy_indexer_temporary_cleanup_required; drain old workers and remove their owned scratch first')
        return removed+recovered

    def _register_copy(self,metadata):
        response=self.client.post(f"/api/v1/internal/text-indexing/jobs/{metadata['job_id']}/processing-copy",json={k:v for k,v in metadata.items() if k!='job_id'})
        response.raise_for_status()

    def _acknowledge_copy(self,metadata):
        response=self.client.delete(f"/api/v1/internal/text-indexing/processing-copies/{metadata['token']}",params={'worker_id':metadata['worker_id']})
        response.raise_for_status()

    def _claim(self) -> list[dict]:
        response = self.client.post("/api/v1/internal/text-indexing/jobs/claim", json={
            "worker_id": self.settings.worker_id, "instance_nonce": self.nonce,
            "requested_count": self.settings.claim_batch_size, "contract_version": "1", "processing_copy_protocol":1,
            "extractor_version": "4.0.0",
            "extraction_config_version": "tika-4.0.0-ocr-eng-ara-v1",
            "index_config_version": "fts-content-v1",
            "supported_mime_types": list(MIME_TYPES), "ocr_languages": ["eng", "ara"],
            "limits": {"max_input_bytes": self.settings.max_input_bytes,
                       "max_characters": self.settings.max_extracted_characters,
                       "max_pages": self.settings.max_pages},
        })
        response.raise_for_status()
        return response.json()["jobs"]

    @staticmethod
    def lease(job: dict) -> dict:
        return {"worker_id": None, "lease_token": job["lease_token"],
                "lease_generation": job["lease_generation"]}

    def _lease(self, job: dict) -> dict:
        value = self.lease(job)
        value["worker_id"] = self.settings.worker_id
        return value

    def _start_heartbeat(self, job: dict) -> tuple[threading.Event, threading.Thread]:
        stop = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat,
            args=(job["job_id"], self._lease(job), stop),
            daemon=True,
            name=f"index-heartbeat-{job['job_id']}",
        )
        thread.start()
        return stop, thread

    @staticmethod
    def _stop_heartbeat(heartbeat: tuple[threading.Event, threading.Thread]) -> None:
        stop, thread = heartbeat
        stop.set()
        thread.join(timeout=2)

    @staticmethod
    def _is_lease_lost(error: httpx.HTTPStatusError) -> bool:
        if error.response.status_code != 409:
            return False
        try:
            detail = error.response.json().get("detail", {})
        except ValueError:
            return False
        return isinstance(detail, dict) and detail.get("code") == "lease_lost"

    def process(
        self,
        job: dict,
        heartbeat: tuple[threading.Event, threading.Thread] | None = None,
    ) -> None:
        lease = self._lease(job)
        job_id = job["job_id"]
        owned_heartbeat = heartbeat is None
        if heartbeat is None:
            heartbeat = self._start_heartbeat(job)
        try:
            if job["content_size"] > self.settings.max_input_bytes:
                raise ExtractionError("limit_exceeded", "input exceeds configured byte limit")
            with owned_workspace(self.settings.temp_root,{'job_id':job_id,**lease},self._register_copy,self._acknowledge_copy) as directory:
                os.chmod(directory, 0o700)
                source = Path(directory) / "source.bin"
                digest = hashlib.sha256()
                size = 0
                headers = {"X-Worker-ID": self.settings.worker_id,
                           "X-Lease-Token": job["lease_token"],
                           "X-Lease-Generation": str(job["lease_generation"])}
                with self.client.stream("GET", f"/api/v1/internal/text-indexing/jobs/{job_id}/content", headers=headers) as response:
                    response.raise_for_status()
                    with source.open("xb") as stream:
                        os.chmod(source, 0o600)
                        for block in response.iter_bytes():
                            size += len(block)
                            if size > self.settings.max_input_bytes:
                                raise ExtractionError("limit_exceeded", "input exceeds configured byte limit")
                            digest.update(block); stream.write(block)
                if digest.hexdigest() != job["content_checksum_value"]:
                    raise ExtractionError("checksum_mismatch", "download checksum did not match leased identity")
                mime_type = job["required_capabilities"]["mime_type"]
                if mime_type in {"image/png","image/jpeg","image/tiff"}:
                    text=extract_image_ocr(source,self.settings.extraction_timeout_seconds); ocr_used=True
                elif mime_type=="application/pdf":
                    text,ocr_used=extract_pdf(self.settings.tika_home,source,self.settings.extraction_timeout_seconds,
                                              self.settings.max_pages,self.settings.max_temp_bytes)
                else:
                    text=extract(self.settings.tika_home,source,self.settings.extraction_timeout_seconds); ocr_used=False
                if len(text) > self.settings.max_extracted_characters:
                    raise ExtractionError("limit_exceeded", "extracted text exceeds configured character limit")
                prepared = chunks(text, self.settings.chunk_target_characters, self.settings.chunk_max_characters)
                for number, chunk in enumerate(prepared):
                    body = {**lease, "idempotency_key": f"chunk-{job['lease_generation']}-{number}",
                            "text": chunk.text, "text_digest": hashlib.sha256(chunk.text.encode()).hexdigest(),
                            "language_decision": chunk.decision, "detected_language": chunk.detected_language}
                    response = self.client.put(f"/api/v1/internal/text-indexing/jobs/{job_id}/chunks/{number}", json=body)
                    response.raise_for_status()
                languages = {chunk.detected_language for chunk in prepared if chunk.detected_language}
                response = self.client.post(f"/api/v1/internal/text-indexing/jobs/{job_id}/complete", json={
                    **lease, "idempotency_key": f"complete-{job['lease_generation']}",
                    "chunk_count": len(prepared), "detected_mime_type": job["required_capabilities"]["mime_type"],
                    "detected_language": next(iter(languages)) if len(languages) == 1 else None,
                    "extractor_name": "Apache Tika", "extractor_version": "4.0.0",
                    "characters_extracted": sum(len(chunk.text) for chunk in prepared),
                    "ocr_used": ocr_used,
                })
                response.raise_for_status()
        except ExtractionError as error:
            response = self.client.post(f"/api/v1/internal/text-indexing/jobs/{job_id}/fail", json={
                **lease, "idempotency_key": f"fail-{job['lease_generation']}",
                "error_code": error.code, "error_summary": error.summary, "retryable": error.retryable,
            })
            response.raise_for_status()
        finally:
            if owned_heartbeat:
                self._stop_heartbeat(heartbeat)

    def _heartbeat(self, job_id: int, lease: dict, stop: threading.Event) -> None:
        while not stop.wait(self.settings.heartbeat_seconds):
            try:
                response = self.client.post(
                    f"/api/v1/internal/text-indexing/jobs/{job_id}/heartbeat",
                    json={**lease, "progress": {"phase": "extracting"}},
                )
                response.raise_for_status()
            except Exception:
                LOG.warning("heartbeat failed for job %s", job_id, exc_info=True)

    def run(self, once: bool = False) -> None:
        self_test(self.settings.tika_home)
        removed=self.recover_temporary_files()
        if removed: LOG.warning("removed %s abandoned indexing temporary entries",removed)
        retry_delay = min(30, max(1, self.settings.poll_seconds))
        disconnected = False
        while True:
            try:
                jobs = self._claim()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                # Keep the same worker identity/nonce during a temporary API
                # outage. Authentication and contract errors remain terminal;
                # an ambiguous claim is left to the API's lease expiry rules.
                retryable = isinstance(error, httpx.TransportError) or (
                    error.response.status_code in {429, 502, 503, 504}
                )
                if once or not retryable:
                    raise
                if not disconnected:
                    LOG.warning("indexing API unavailable; retrying with backoff (maximum 30 seconds)")
                disconnected = True
                time.sleep(retry_delay)
                retry_delay = min(30, retry_delay * 2)
                continue
            if disconnected:
                LOG.info("indexing API connection restored")
            disconnected = False
            retry_delay = min(30, max(1, self.settings.poll_seconds))
            # Every job in a claimed batch is already leased. Keep all leases
            # alive while jobs ahead of them are processed sequentially.
            heartbeats = {job["job_id"]: self._start_heartbeat(job) for job in jobs}
            try:
                for job in jobs:
                    heartbeat = heartbeats.pop(job["job_id"])
                    try:
                        self.process(job, heartbeat=heartbeat)
                    except httpx.HTTPStatusError as error:
                        if not self._is_lease_lost(error):
                            raise
                        LOG.warning(
                            "lease lost for indexing job %s; discarding local output",
                            job["job_id"],
                        )
                    finally:
                        self._stop_heartbeat(heartbeat)
            finally:
                for heartbeat in heartbeats.values():
                    self._stop_heartbeat(heartbeat)
            if once:
                return
            time.sleep(self.settings.poll_seconds)
