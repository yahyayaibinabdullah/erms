"""Repeatable original-PDF measurements inside the owning disposable browser runner."""

import hashlib
import os
from pathlib import Path
import random
import subprocess
import threading
import time
from contextlib import contextmanager

from selenium.webdriver.support.ui import WebDriverWait


def large_pdf(scanned):
    """Flat page tree with a distinct content stream per page and a conventional trailing xref."""
    count = 160 if scanned else 3200
    refs = " ".join(f"{4+i} 0 R" for i in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {count} /Kids [{refs}] >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    contents = []
    images = []
    rng = random.Random(4242)
    for i in range(count):
        resources = "/Font << /F1 3 0 R >>"
        if scanned:
            resources = f"/XObject << /Scan {4+2*count+i} 0 R >>"
            pixels = rng.randbytes(512 * 512)
            images.append(
                b"<< /Type /XObject /Subtype /Image /Width 512 /Height 512 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 262144 >>\nstream\n"
                + pixels
                + b"\nendstream"
            )
            content = b"q 500 0 0 500 20 40 cm /Scan Do Q"
        else:
            lines = [f"(Page {i+1} line {j+1} {rng.randbytes(56).hex()}) Tj T*" for j in range(96)]
            content = ("BT /F1 6 Tf 8 TL 10 780 Td\n" + "\n".join(lines) + "\nET").encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << {resources} >> /Contents {4+count+i} 0 R >>".encode()
        )
        contents.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    data = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects + contents + images, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data), count


@contextmanager
def memory_samples(chrome_pid):
    """macOS ps reports RSS in KiB. Sum Chrome's process tree, including renderer and worker."""
    peak = {}
    stopped = threading.Event()

    def sample():
        while not stopped.is_set():
            rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss=,command="], text=True)
            tree = {}
            chrome = {chrome_pid}
            for row in rows.splitlines():
                fields = row.split(None, 3)
                if len(fields) < 4:
                    continue
                pid, parent, rss = map(int, fields[:3])
                tree[pid] = (parent, rss)
                if parent == os.getppid():
                    label = (
                        "api"
                        if "tools.webui_browser_server --fd" in fields[3]
                        else "webui" if "runpy.run_module" in fields[3] else None
                    )
                    if label:
                        peak[label] = max(peak.get(label, 0), rss)
            while descendants := {p for p, (parent, _) in tree.items() if parent in chrome} - chrome:
                chrome.update(descendants)
            peak["chrome"] = max(peak.get("chrome", 0), sum(tree[p][1] for p in chrome if p in tree))
            stopped.wait(0.10)

    thread = threading.Thread(target=sample)
    thread.start()
    try:
        yield peak
    finally:
        stopped.set()
        thread.join()


def check_pdf_performance(page):
    parent = page.api.post(
        "/api/v1/aggregations/search",
        json={
            "where": {"field": "aggregation_number", "operator": "eq", "value": "TEST-AGG"},
            "limit": 1,
            "offset": 0,
        },
    ).json()["items"][0]
    aggregation = page.api.post(
        "/api/v1/aggregations",
        json={
            "aggregation_number": "PDF-BENCH",
            "title": "Preview benchmark",
            "classification_id": parent["classification_id"],
            "medium": "digital",
        },
    )
    aggregation.raise_for_status()
    saved = page.api.post(
        "/api/v1/records",
        json={
            "aggregation_id": aggregation.json()["id"],
            "record_number": "PDF-BENCH",
            "title": "Reader benchmark",
            "medium": "digital",
        },
    )
    saved.raise_for_status()
    record = saved.json()
    fixtures = []
    for order, kind in enumerate(("text", "scan"), 10):
        mime = "application/pdf"
        if page.args.pdf_workbook:
            source = Path(page.args.pdf_workbook).with_suffix(".docx" if kind == "text" else ".pdf")
            data, count, name = source.read_bytes(), 200, source.name
            if source.suffix == ".docx":
                mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            data, count = large_pdf(kind == "scan")
            name = f"benchmark-{kind}.pdf"
        result = page.api.post(
            f"/api/v1/records/{record['id']}/digital-components/upload",
            data={"component_order": str(order)},
            files={"file": (name, data, mime)},
        )
        result.raise_for_status()
        fixtures.append((name, count, len(data), hashlib.sha256(data).hexdigest()))

    if page.args.pdf_workbook and not page.args.pdf_baseline:
        page.api.post(f"/api/v1/records/{record['id']}/digital-components/upload",
                      data={"component_order": "12"},
                      files={"file": ("workbook-notes.txt", b"Workbook reading notes.", "text/plain")}).raise_for_status()
    page.drawer("records")
    page.fill(page.t("webui.index.input.search_by_number_title_or_description_e21ed520"), "PDF-BENCH")
    page.click(page.t("webui.index.button.search_4d02b714"), page.one(".erms-card"))
    page.activate(page.one('button[aria-label="Open record"]', scope=page.one(".compact-result-item")))
    driver = page.driver
    wait = WebDriverWait(driver, 60, poll_frequency=0.025)
    chrome_pid = driver.capabilities["goog:processID"]
    for name, count, size, checksum in fixtures:
        row = page.one(".record-file-name", name).find_element(
            "xpath", "ancestor::*[contains(@class,'record-file-row')][1]"
        )
        for profile in ("local", "limited", "local", "limited"):
            limiter = Path(page.args.output) / "limited-profile"
            if profile == "limited":
                limiter.write_text("32")
            else:
                limiter.unlink(missing_ok=True)
            with page.check(f"{name} {profile} first and final page"), memory_samples(chrome_pid) as peak:
                button = next(b for b in page.visible("button", row) if "visibility" in b.text)
                started = time.monotonic()
                button.click()
                frame = wait.until(
                    lambda _: driver.execute_script("return document.querySelector('.q-dialog iframe')")
                )
                driver.switch_to.frame(frame)
                try:
                    wait.until(
                        lambda _: driver.execute_script(
                            "return !!document.querySelector('.page[data-page-number=\"1\"][data-loaded] canvas') && window.PDFViewerApplication?.pdfViewer?.getPageView(0)?.renderingState===3"
                        )
                    )
                    painted = time.monotonic()
                    assert driver.execute_script("return PDFViewerApplication.pagesCount") == count
                    first = painted - started
                    resources = driver.execute_script(
                        "return performance.getEntriesByType('resource').filter(e=>e.name.includes('/preview-pdf/')).map(e=>e.encodedBodySize)"
                    )
                    jump = time.monotonic()
                    driver.execute_script("PDFViewerApplication.page=arguments[0]", count)
                    wait.until(
                        lambda _: driver.execute_script(
                            "return PDFViewerApplication.pdfViewer.getPageView(arguments[0]-1)?.renderingState===3",
                            count,
                        )
                    )
                    finished = time.monotonic()
                    last = finished - jump
                finally:
                    driver.switch_to.default_content()
                dialog = page.one(".q-dialog__inner > .q-card")
                next(b for b in page.visible("button", dialog) if "close" in b.text).click()
                page.wait.until(lambda _: not page.visible(".q-dialog iframe"))
            page.report.setdefault("pdf_samples", []).append(
                dict(
                    file=name,
                    size=size,
                    pages=count,
                    sha256=checksum,
                    profile=profile,
                    first_ms=round(first * 1000),
                    jump_ms=round(last * 1000),
                    completed_http_body_bytes_at_first=sum(resources),
                    completed_http_requests_at_first=len(resources),
                    peak_rss_kib=peak,
                )
            )
            sample = page.report["pdf_samples"][-1]
            if page.args.pdf_workbook:
                sample["conversion_ms"] = [
                    event["ms"] for event in page.events("pdf-conversions.jsonl")
                    if started <= event["at"] <= finished
                ]
            for filename, key in [
                ("pdf-transfer.jsonl", "webui_bytes"),
                ("pdf-storage.jsonl", "storage_bytes"),
                ("pdf-rendition-reads.jsonl", "rendition_bytes"),
            ]:
                events = page.events(filename)
                sample[key + "_to_first"] = sum(e["bytes"] for e in events if started <= e["at"] <= painted)
                sample[key + "_during_jump"] = sum(
                    e["bytes"] for e in events if jump <= e["at"] <= finished
                )
    limiter.unlink(missing_ok=True)
    if page.args.pdf_workbook and not page.args.pdf_baseline:
        with page.check("one dialog retains two conversions across component switches"):
            names = [fixtures[0][0], fixtures[1][0], "workbook-notes.txt"]
            row = page.one(".record-file-name", names[0]).find_element(
                "xpath", "ancestor::*[contains(@class,'record-file-row')][1]"
            )
            conversions_before = len(page.events("pdf-conversions.jsonl"))
            next(b for b in page.visible("button", row) if "visibility" in b.text).click()
            seen = {}
            for visit, index in enumerate([0, 1, 2, 0, 2]):
                if visit:
                    page.activate(page.visible(".component-switcher-button", page.one(".q-dialog__inner > .q-card"))[index])
                url = wait.until(lambda _: driver.execute_script("""
                    const frame = document.querySelector('.q-dialog iframe');
                    const app = frame?.contentWindow?.PDFViewerApplication;
                    return frame?.title === arguments[0] && app?.pdfViewer?.getPageView(0)?.renderingState === 3 && app.url;
                """, names[index]))
                if index in seen:
                    assert url == seen[index]
                seen[index] = url
            assert len(page.events("pdf-conversions.jsonl")) - conversions_before == 2
            next(b for b in page.visible("button", page.one(".q-dialog__inner > .q-card")) if "close" in b.text).click()
            page.wait.until(lambda _: not page.visible(".q-dialog iframe"))
        with page.check("closing workbook viewers releases converted bytes"):
            subprocess.run([page.args.api_python, "-c", """
import time
import psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url(), autocommit=True) as db:
    deadline = time.monotonic() + 8
    while db.execute('SELECT EXISTS(SELECT FROM preview_renditions) OR EXISTS(SELECT FROM preview_rendition_chunks)').fetchone()[0]:
        if time.monotonic() >= deadline:
            raise AssertionError('closed viewer retained converted bytes')
        time.sleep(.1)
"""], check=True)
    for sample in page.report["pdf_samples"]:
        converted = sample["file"].endswith(".docx")
        if page.args.pdf_workbook and converted:
            assert sample["storage_bytes_to_first"] == sample["size"]
            assert sample["storage_bytes_during_jump"] == 0
            assert bool(sample["completed_http_requests_at_first"]) != page.args.pdf_baseline
            assert len(sample["conversion_ms"]) == 1
            if not page.args.pdf_baseline:
                assert 0 < sample["webui_bytes_to_first"] < fixtures[1][2]
                assert sample["rendition_bytes_to_first"] > 0
                assert sample["rendition_bytes_during_jump"] < fixtures[1][2]
        elif page.args.pdf_workbook:
            assert sample["completed_http_requests_at_first"] > 0
            assert sample["storage_bytes_during_jump"] < sample["size"]
            assert not sample["conversion_ms"]
        elif page.args.pdf_baseline and not page.args.pdf_workbook:
            assert sample["storage_bytes_to_first"] >= sample["size"]
        else:
            assert sample["completed_http_requests_at_first"] > 0
            assert 0 < sample["webui_bytes_to_first"] < sample["size"]
            assert 0 < sample["storage_bytes_to_first"] < sample["size"]
            assert sample["storage_bytes_during_jump"] < sample["size"]
    if not page.args.pdf_baseline and not page.args.pdf_workbook:
        check_abandoned_pdf(page, fixtures)
        check_concurrent_viewers(page, fixtures[1][0])


def check_abandoned_pdf(page, fixtures):
    """Switch while fetching a slow PDF, abort a binary stream, then verify its fence is gone."""
    import httpx

    driver = page.driver
    with page.check("switch during original PDF load and release abandoned responses"):
        first_name = fixtures[0][0]
        row = page.one(".record-file-name", first_name).find_element(
            "xpath", "ancestor::*[contains(@class,'record-file-row')][1]"
        )
        limiter = Path(page.args.output) / "limited-profile"
        limiter.write_text("4")
        try:
            start = len(page.events("requests-started.jsonl"))
            next(b for b in page.visible("button", row) if "visibility" in b.text).click()
            page.wait.until(
                lambda _: any(
                    event["path"].endswith("/rendition") and event["method"] == "GET"
                    for event in page.events("requests-started.jsonl")[start:]
                )
            )
            dialog = page.one(".q-dialog__inner > .q-card")
            page.activate(page.visible(".component-switcher-button", dialog)[1])
            page.wait.until(
                lambda _: driver.execute_script(
                    """
                const f = document.querySelector('.q-dialog iframe');
                return f?.contentWindow?.PDFViewerApplication?.pdfDocument?.numPages === arguments[0]
                    && f.contentWindow.PDFViewerApplication.pdfViewer.getPageView(0)?.renderingState === 3
            """,
                    fixtures[1][1],
                )
            )
            url = driver.execute_script(
                "return document.querySelector('.q-dialog iframe').contentWindow.PDFViewerApplication.url"
            )
            with httpx.Client(trust_env=False) as anonymous:
                assert anonymous.get(url, headers={"Range": "bytes=0-5"}).status_code == 401
            result = driver.execute_async_script(
                """
                const [url, done] = arguments;
                (async () => {
                    const probe = await fetch(url, {method:'HEAD'});
                    const intervals = await Promise.all(['bytes=0-4','bytes=-5','bytes=123-126'].map(async range => {
                        const response = await fetch(url,{headers:{Range:range}});
                        return [response.status,(await response.arrayBuffer()).byteLength];
                    }));
                    const controller = new AbortController();
                    const full = await fetch(url,{signal:controller.signal});
                    await full.body.getReader().read();
                    controller.abort();
                    return [probe.status, probe.headers.get('accept-ranges'), intervals];
                })().then(done, error => done(String(error)));
            """,
                url,
            )
            assert result == [200, "bytes", [[206, 5], [206, 5], [206, 4]]], result
            next(b for b in page.visible("button", dialog) if "close" in b.text).click()
            page.wait.until(lambda _: not page.visible(".q-dialog iframe"))
        finally:
            limiter.unlink(missing_ok=True)
        subprocess.run(
            [
                page.args.api_python,
                "-c",
                """
import time
import psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url(), autocommit=True) as conn:
    deadline = time.monotonic()+8
    while conn.execute('SELECT count(*) FROM disposition_private.processing_copies').fetchone()[0]:
        if time.monotonic() >= deadline:
            raise AssertionError('Original PDF retained a processing copy after disconnect')
        time.sleep(.1)
""",
            ],
            check=True,
        )


def check_concurrent_viewers(page, filename):
    """Three WebUI windows open the same PDF through independent Preview actions."""
    driver = page.driver
    original = driver.current_window_handle
    windows = [original]
    limiter = Path(page.args.output) / "limited-profile"
    with page.check("three concurrent original-PDF windows under a shared login"):
        try:
            for _ in range(2):
                driver.switch_to.new_window("window")
                windows.append(driver.current_window_handle)
                driver.get(page.args.url + "/")
                page.drawer("records")
                page.fill(
                    page.t("webui.index.input.search_by_number_title_or_description_e21ed520"), "PDF-BENCH"
                )
                page.click(page.t("webui.index.button.search_4d02b714"), page.one(".erms-card"))
                page.activate(
                    page.one('button[aria-label="Open record"]', scope=page.one(".compact-result-item"))
                )
                page.one(".record-file-name", filename)
            buttons = []
            for window in windows:
                driver.switch_to.window(window)
                row = page.one(".record-file-name", filename).find_element(
                    "xpath", "ancestor::*[contains(@class,'record-file-row')][1]"
                )
                buttons.append(next(b for b in page.visible("button", row) if "visibility" in b.text))
            limiter.write_text("4")
            trigger = int(time.time() * 1000) + 1500
            with memory_samples(driver.capabilities["goog:processID"]) as peak:
                for window, button in zip(windows, buttons):
                    driver.switch_to.window(window)
                    driver.execute_script(
                        """
                        const [button, trigger] = arguments;
                        setTimeout(() => {
                            window.previewTiming = {start: Date.now()};
                            button.click();
                            const poll = setInterval(() => {
                                const app = document.querySelector('.q-dialog iframe')?.contentWindow?.PDFViewerApplication;
                                if (app?.pdfViewer?.getPageView(0)?.renderingState === 3) {
                                    window.previewTiming.ready = Date.now();
                                    clearInterval(poll);
                                }
                            }, 25);
                        }, trigger - Date.now());
                    """,
                        button,
                        trigger,
                    )
                timings = []
                for window in windows:
                    driver.switch_to.window(window)
                    timings.append(
                        page.wait.until(
                            lambda _: driver.execute_script(
                                "return window.previewTiming?.ready ? window.previewTiming : null"
                            )
                        )
                    )
            assert max(row["start"] for row in timings) < min(row["ready"] for row in timings), timings
            page.report["concurrent_pdfs"] = {
                "windows": len(windows),
                "first_page_ms": [row["ready"] - row["start"] for row in timings],
                "all_first_pages_ms": max(row["ready"] for row in timings)
                - min(row["start"] for row in timings),
                "peak_rss_kib": peak,
            }
        finally:
            limiter.unlink(missing_ok=True)
            for window in reversed(windows[1:]):
                driver.switch_to.window(window)
                driver.close()
            driver.switch_to.window(original)
            dialogs = page.visible(".q-dialog__inner > .q-card")
            if dialogs:
                next(b for b in page.visible("button", dialogs[-1]) if "close" in b.text).click()
