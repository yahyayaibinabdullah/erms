"""Compare fresh and resident full-PDF conversions through real Preview clicks."""
from uuid import uuid4

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import mimetypes
import subprocess
from threading import Barrier, Event

from selenium.webdriver.support.ui import WebDriverWait
from tools.check_webui_browser import Acceptance, create_driver

FORMATS = ("docx", "xlsx", "pptx")
PAGES = {"docx": 200, "xlsx": 40, "pptx": 60}


def upload(page):
    base = page.api.post(
        "/api/v1/aggregations/search",
        json={
            "where": {
                "field": "aggregation_number",
                "operator": "eq",
                "value": "TEST-AGG",
            },
            "limit": 1,
        },
    )
    base.raise_for_status()
    agg = page.api.post(
        "/api/v1/aggregations", headers={'Idempotency-Key': str(uuid4()), 'X-Event-Source': 'seeding'},
        json={
            "aggregation_number": "OFFICE-BENCH",
            "title": "Office benchmark",
            "medium": "digital",
            "classification_id": base.json()["items"][0]["classification_id"],
        },
    )
    agg.raise_for_status()
    rec = page.api.post(
        "/api/v1/records", headers={'Idempotency-Key': str(uuid4()), 'X-Event-Source': 'seeding'},
        json={
            "aggregation_id": agg.json()["id"],
            "record_number": "OFFICE-BENCH",
            "title": "Office benchmark",
            "medium": "digital",
        },
    )
    rec.raise_for_status()
    for order, ext in enumerate(FORMATS, 1):
        source = page.args.office_fixtures / f"benchmark.{ext}"
        data = source.read_bytes()
        result = page.api.post(
            f"/api/v1/records/{rec.json()['id']}/digital-components/upload",
            data={"component_order": str(order)},
            files={"file": (source.name, data, mimetypes.guess_type(source.name)[0])},
        )
        result.raise_for_status()
        page.report.setdefault("fixtures", {})[ext] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }


def record_page(page):
    page.drawer("records")
    page.fill(
        page.t("webui.index.input.search_by_number_title_or_description_e21ed520"),
        "OFFICE-BENCH",
    )
    page.click(page.t("webui.index.button.search_4d02b714"), page.one(".erms-card"))
    page.activate(
        page.one(
            'button[aria-label="Open record"]', scope=page.one(".compact-result-item")
        )
    )
    page.one(".record-file-name", "benchmark.docx")
    page.driver.set_script_timeout(110)


def process_memory(api, webui, chromes):
    # Single system snapshot, then sum only descendants of the runner-owned PIDs.
    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss="], text=True)
    tree = {
        pid: (parent, rss)
        for pid, parent, rss in (map(int, row.split()) for row in rows.splitlines())
    }

    def total(roots):
        owned = set(roots)
        while (
            new := {pid for pid, (parent, _) in tree.items() if parent in owned} - owned
        ):
            owned.update(new)
        return sum(tree[pid][1] for pid in owned if pid in tree)

    server = total([api])
    ui = total([webui])
    chrome = total(chromes)
    return {
        "api_tree": server,
        "api_children": server - tree[api][1],
        "webui_tree": ui,
        "chrome_trees": chrome,
        "server_total": server + ui,
        "total": server + ui + chrome,
    }


def preview(page, ext, barrier):
    row = page.one(".record-file-name", f"benchmark.{ext}").find_element(
        "xpath", "ancestor::*[contains(@class,'record-file-row')][1]"
    )
    button = next(b for b in page.visible("button", row) if "visibility" in b.text)
    barrier.wait(timeout=20)
    # Time inside each independent foreground browser. Count all work after the click.
    start, finish, count = page.driver.execute_async_script(
        """
        const [button, done] = arguments;
        const start = performance.timeOrigin + performance.now();
        button.click();
        function poll() {
            const app = document.querySelector('.q-dialog iframe')?.contentWindow?.PDFViewerApplication;
            if (app?.pdfViewer?.getPageView(0)?.renderingState === 3) {
                done([start, performance.timeOrigin + performance.now(), app.pagesCount]);
            } else setTimeout(poll, 20);
        }
        poll();
    """,
        button,
    )
    assert count == PAGES[ext], (ext, count)
    return {
        "format": ext,
        "start": start,
        "finish": finish,
        "first_ms": round(finish - start),
        "pages": count,
    }


def verify_and_close(page, ext, check_content):
    driver = page.driver
    iframe = page.one(".q-dialog iframe")
    driver.switch_to.frame(iframe)
    try:
        driver.execute_script(
            "PDFViewerApplication.page = PDFViewerApplication.pagesCount"
        )
        WebDriverWait(driver, 30).until(
            lambda _: driver.execute_script(
                "return PDFViewerApplication.pdfViewer.getPageView(PDFViewerApplication.pagesCount-1)?.renderingState === 3"
            )
        )
        if check_content:
            return driver.execute_async_script("""
                const done = arguments[0];
                (async () => {
                    const doc = PDFViewerApplication.pdfDocument, pages = [];
                    for (let n = 1; n <= doc.numPages; n++) {
                        const p = await doc.getPage(n);
                        const text = await p.getTextContent();
                        pages.push([p.view, p.rotate, text.items.map(i => [i.str, i.transform])]);
                    }
                    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(pages)));
                    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,'0')).join('');
                })().then(done);
            """)
    finally:
        driver.switch_to.default_content()
        close = next(
            b
            for b in page.visible("button", page.one(".q-dialog__inner > .q-card"))
            if "close" in b.text
        )
        page.activate(close)
        page.wait.until(lambda _: not page.visible(".q-dialog iframe"))


def check_office_pool(page):
    upload(page)
    record_page(page)
    paths = page.args.output
    state = json.loads((paths / "lifecycle.json").read_text())
    group = [page]
    results = page.report.setdefault("office_samples", [])
    with ExitStack() as cleanup, ThreadPoolExecutor(max_workers=4) as threads:
        for concurrent in (False, True):
            if concurrent:
                for _ in range(2):
                    driver = create_driver("chrome", paths)
                    cleanup.callback(driver.quit)
                    driver.set_window_size(1440, 1000)
                    extra = Acceptance(driver, page.args)
                    cleanup.callback(extra.api.close)
                    driver.get(page.args.url + "/")
                    extra.login()
                    for reader in extra.event_readers.values():
                        cleanup.callback(reader.close)
                    record_page(extra)
                    group.append(extra)
            chromes = [p.driver.capabilities["goog:processID"] for p in group]
            for repeat in range(3):
                formats = FORMATS[repeat:] + FORMATS[:repeat]
                for batch in ([formats] if concurrent else [(ext,) for ext in formats]):
                    with page.check(
                        "office previews " + "+".join(batch) + f" repeat {repeat + 1}"
                    ):
                        jobs_before = len(page.events("office-jobs.jsonl"))
                        baseline = process_memory(
                            state["api_pid"], state["webui_pid"], chromes
                        )
                        samples = [baseline]
                        stop = Event()

                        def sample():
                            while not stop.wait(0.1):
                                samples.append(
                                    process_memory(
                                        state["api_pid"], state["webui_pid"], chromes
                                    )
                                )

                        monitor = threads.submit(sample)
                        try:
                            gate = Barrier(len(batch))
                            futures = [
                                threads.submit(preview, p, ext, gate)
                                for p, ext in zip(group, batch)
                            ]
                            timings = [f.result() for f in futures]
                        finally:
                            stop.set()
                            monitor.result()
                        assert len(samples) > 1, "No memory samples during the open"
                        jobs = page.events("office-jobs.jsonl")[jobs_before:]
                        assert len(jobs) == len(batch) and all(
                            j["status"] == 0 for j in jobs
                        ), jobs
                        assert max(t["start"] for t in timings) < min(
                            t["finish"] for t in timings
                        ), timings
                        for p, ext in zip(group, batch):
                            digest = verify_and_close(
                                p, ext, not concurrent and repeat == 0
                            )
                            if digest:
                                page.report["fixtures"][ext][
                                    "page_text_geometry_sha256"
                                ] = digest
                        results.append(
                            dict(
                                viewers=len(batch),
                                repeat=repeat + 1,
                                first_pages=timings,
                                all_ms=round(
                                    max(t["finish"] for t in timings)
                                    - min(t["start"] for t in timings)
                                ),
                                idle_kib=baseline,
                                peak_kib={
                                    k: max(s[k] for s in samples) for k in baseline
                                },
                                rss_samples=len(samples),
                                conversions=jobs,
                            )
                        )
    # All successful opens verified the last page and closed their dialogs.
    subprocess.run(
        [
            page.args.api_python,
            "-c",
            """
import time, psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url(), autocommit=True) as conn:
    deadline = time.monotonic() + 10
    while conn.execute('SELECT EXISTS(TABLE preview_renditions) OR EXISTS(TABLE preview_rendition_chunks)').fetchone()[0]:
        if time.monotonic() >= deadline: raise RuntimeError('closed viewer retained a rendition')
        time.sleep(.1)
""",
        ],
        check=True,
    )
