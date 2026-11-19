# Document viewing and downloads

ERMS keeps the uploaded digital component as the authoritative original. The UI
offers two deliberately separate actions:

- **Download original** returns the stored bytes with attachment disposition.
- **View document** requests a PDF rendition and displays it with the PDF.js
  viewer bundled under `frontend/webui/static/pdfjs`.

The component switcher moves between files. Within a PDF, the sidebar shows
page thumbnails. The reader supports zoom, page navigation, text selection,
find, and viewing embedded annotations. Selection and find require a text layer
in the rendition. Annotation editing is disabled. Use the Wathiq toolbar to
print or download with the corresponding permission. Staged previews are
read-only and offer neither action.

Neither operation sends record content to an external service or CDN.

## Supported previews

PDF content is passed directly to PDF.js. Safe raster images use the browser's
native image renderer, while audio and video use native HTML5 media controls.
SVG is deliberately excluded because it can contain active content. LibreOffice
converts these formats to PDF on demand: DOC, DOCX, ODT, RTF, XLS, XLSX, ODS,
CSV, PPT, PPTX, ODP, Markdown (`.md`), Outlook Message (`.msg`), Internet
Message (`.eml`), HTML (`.html`), plain text (`.txt`) and XML (`.xml`). Other
content remains downloadable but produces an unsupported-preview response.

XML is not imported directly as a LibreOffice data document. The API detects
the XML byte-order mark or declared character encoding, escapes the complete
source as inert text, preserves whitespace with wrapping, and asks
LibreOffice to convert that controlled UTF-8 HTML source view. It does not
parse XML, resolve entities, apply stylesheets, or retrieve referenced
resources.

Before converting XLSX, the API examines each worksheet's used-column widths
and print settings. A worksheet wider than its current printable orientation
is normalized in a temporary workbook copy to A4 landscape, one page wide and
unlimited pages tall. Narrow sheets and the authoritative stored workbook are
left unchanged. This prevents wide columns from being clipped while avoiding
unnecessary scaling of already printable sheets.

MSG is not passed directly to LibreOffice because that path can misinterpret
the binary Outlook container and produce mojibake. The API runs `extract-msg`
in a timeout-bounded subprocess, escapes the extracted sender, recipients,
date, subject and plain-text body into inert UTF-8 HTML, and lists attachment
names without opening or embedding attachment content. LibreOffice then
converts that controlled HTML document to PDF. This preserves English and
Arabic text while excluding scripts, remote resources and active message HTML.

EML likewise is not passed directly to LibreOffice because LibreOffice can
display raw MIME headers and transfer-encoded payloads. A timeout-bounded
subprocess uses Python's standard email parser to decode MIME headers,
base64/quoted-printable transfer encoding and declared character sets. It
prefers the plain-text MIME body; when only HTML exists it extracts visible
text without preserving active markup. The same inert template and attachment
handling used for MSG then feeds LibreOffice.

These formats use the same isolated temporary workspace, bounded
source/rendition size, timeout and sandboxed PDF response as the existing
Office conversions. Deployments must verify that their installed LibreOffice
build includes the applicable import filters. The conversion worker or
container must have no general outbound network access, particularly when
processing HTML or email content that can reference external resources.

The dedicated MSG and EML extraction paths are implemented. Other Python fallbacks remain
deferred. A future bounded fallback may convert Markdown to sanitized HTML with
Python-Markdown, then render a controlled HTML template with WeasyPrint. Such a fallback must disable external
network and unrestricted local-file access, sanitize untrusted HTML, block
scripts and active content, treat attachments as inert metadata, use
Arabic-capable fonts with RTL styling, and retain the existing CPU, memory,
size and timeout limits.

Every View action opens an indeterminate **Preparing preview** progress dialog
before requesting content. For PDFs and browser-native media it explains that
the document is loading; for formats handled by LibreOffice it explains that
conversion is taking place. It remains visible until the content is received or
the API reports an error, so a large transfer or long-running conversion is not
mistaken for an unresponsive action. The indicator is intentionally
indeterminate because the current rendition endpoint does not expose transfer
or conversion percentage data.

The API searches for `soffice` or `libreoffice` on `PATH`. Set
`LIBREOFFICE_BINARY` to an absolute executable path when it is installed
elsewhere. Direct PDF viewing and all original downloads continue to work when
LibreOffice is absent.

Configuration:

- `DOCUMENT_CONVERSION_TIMEOUT_SECONDS` defaults to 60 seconds.
- `MAX_RENDITION_SIZE_BYTES` defaults to 100 MiB.
- `LIBREOFFICE_BINARY` optionally selects the executable explicitly.

For production, run conversion in a separately isolated worker or container
with CPU, memory and execution-time limits. The current synchronous conversion
is suitable for initial development but should move to a rendition job queue as
the repository grows.

## API operations

- `GET /api/v1/digital-components/{id}/content` downloads the original.
- `GET /api/v1/digital-components/{id}/rendition` returns an inline PDF.

Both require authentication. Downloads append `CONTENT_DOWNLOADED` to event
history; successful views append `CONTENT_VIEWED`. The rendition response uses
`nosniff` and a sandbox content-security policy.

## PDF.js licensing

The vendored PDF.js distribution is version 4.10.38 and is provided under the
Apache License 2.0. Its upstream license is retained at
`frontend/webui/static/pdfjs/LICENSE`.
