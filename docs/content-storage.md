# Digital component content storage

Digital components are lifecycle-dependent parts of their record. Deleting an
open record cascades through its digital-component metadata, active/staged
content sets, and every stored segment.

## Segmented PostgreSQL provider

The PostgreSQL provider stores a logical file as ordered `bytea` rows rather
than one database value. `digital_component_content_sets` identifies a complete
candidate copy and `digital_component_blobs` stores its numbered segments. The
default segment size is 16 MiB, avoiding PostgreSQL's approximately 1 GiB limit
for an individual `bytea` value without assembling a large file in API memory.

`digital_components.active_content_set_id` selects the verified set served to
users. Replacement uploads use a separate staged set. Only after its size,
sequence, and SHA-256 checksum are verified does one transaction switch the
active pointer; failed replacements leave the original available.

Record-draft files use `record_draft_component_blobs`. A successfully uploaded
draft file remains there until the record package is created, the component or
draft is cancelled, or the draft expires. Permanently failed, cancelled, and
expired uploads have their bytes removed by cleanup.

## Streaming and ranges

Uploads are hashed and divided without collecting the complete file in memory.
Downloads, original PDFs, images, audio, and video are streamed in segment
order. Content endpoints accept one HTTP byte range and return `206`,
`Content-Range`, `Content-Length`, `Accept-Ranges`, and a checksum-derived
`ETag`. This supports PDF.js loading, native media seeking, and resumable
downloads. Office, Markdown, HTML and email conversion currently requires
materializing the bounded source for LibreOffice and remains subject to
rendition-size configuration. MSG first uses a timeout-bounded `extract-msg`
subprocess to generate inert UTF-8 HTML before LibreOffice creates the PDF;
EML uses the same bounded intermediary path with Python's standard MIME parser.
XML uses a bounded, encoding-aware, escaped HTML source view before PDF
conversion and does not parse or resolve XML entities or stylesheets.
Wide XLSX worksheets receive preview-only fit-to-page print settings in a
temporary copy; the authoritative workbook is never rewritten.
Other Python conversion fallbacks are documented as future options in
[document viewing](document-viewing.md) but are not implemented.

## Configuration

| Setting | Default | Purpose |
|---|---:|---|
| `CONTENT_STORAGE_BACKEND` | `postgresql` | Storage provider; S3-compatible storage is planned |
| `MAX_UPLOAD_SIZE_BYTES` | `52428800` | Policy limit for a complete file; raise deliberately for large-file deployments |
| `CONTENT_SEGMENT_SIZE_BYTES` | `16777216` | Segment size; accepted range is 1 byte–64 MiB |
| `CONTENT_SEGMENT_CHECKSUMS_ENABLED` | `true` | Store SHA-256 for each segment |
| `CONTENT_UPLOAD_SESSION_TTL_SECONDS` | `86400` | Intended lifetime of an incomplete resumable upload |
| `CONTENT_CLEANUP_INTERVAL_SECONDS` | `3600` | Dedicated cleanup-worker interval |

The complete logical file always has an authoritative SHA-256 checksum and
64-bit size. Segment checksums provide localized integrity evidence.

## Endpoints

- `POST /api/v1/records/{record_id}/digital-components/upload`
- `GET /api/v1/digital-components/{id}/content`
- `GET /api/v1/digital-components/{id}/rendition`
- `PUT /api/v1/digital-components/{id}/content` with `If-Match`
- `DELETE /api/v1/digital-components/{id}/content` with `If-Match`

Clients do not need to know whether content is segmented or, later, stored in
S3. File bytes are never copied into `event_history`.

## Cleanup

The same cleanup service supports manual and scheduled execution:

```bash
python -m backend.services.api.content_cleanup --dry-run
python -m backend.services.api.content_cleanup --batch-size 100
python -m backend.services.api.content_cleanup --watch
```

Run `--watch` as one dedicated worker, or invoke the one-shot command from an
operating-system/container scheduler. Do not run an independent timer in every
FastAPI worker. Cleanup uses an advisory lock, bounded batches, idempotent
deletion, and records a `CONTENT_CLEANUP` domain event when it changes state.

It removes expired incomplete sessions, permanently failed/cancelled staged
sets, expired drafts and their segments, and unreferenced superseded content
sets. It never removes a verified file belonging to an unexpired open draft.

This service is listed with every other backend cleanup responsibility in the
[central cleanup-service inventory](operations.md#3-central-cleanup-service-inventory).

## Operational boundary

Segmentation removes the single-value limit, not PostgreSQL's operational cost.
Content still increases database I/O, WAL, replication traffic, backup size,
restore time, and connection occupancy during slow downloads. Deployments using
large files must monitor these resources and size the upload policy and pools
accordingly. S3-compatible storage remains the recommended later provider for
large scale or high concurrency.

The detailed design, lifecycle, migration rules, and acceptance criteria are in
[`specs/segmented-postgresql-content-storage.md`](../specs/segmented-postgresql-content-storage.md).

## Database-managed policy

Upload maximum, segment size/checksums, upload-session lifetime, cleanup interval,
conversion timeout and rendition maximum now come from Administration Settings.
The API uses one validated settings snapshot throughout each upload/conversion;
changes converge within 30 seconds without restart. The storage backend and
LibreOffice executable remain deployment environment settings. Existing segments
and checksums retain their stored representation when policy changes.

Content cleanup loads a fresh snapshot for one shot and the shared 30-second
cache before each watch pass. Its interval override is optional; the fixed
bounded batch default of 100 is unchanged. See the
[reviewed legacy migration](application-settings-upgrade.md) before upgrade startup.
