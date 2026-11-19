const controllers = new WeakMap();
function frameController(frame) {
  if (!controllers.has(frame)) controllers.set(frame, new AbortController());
  return controllers.get(frame);
}

function decodeBase64(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function printDocument(encoded, mimeType = 'application/pdf') {
  const printWindow = window.__ermsPrintWindow;
  window.__ermsPrintWindow = null;
  if (!printWindow || printWindow.closed) {
    window.alert('The print window was blocked. Allow pop-ups for Wathiq and try again.');
    return;
  }
  const printDocument = printWindow.document;
  printDocument.open();
  printDocument.write(`<!doctype html><html><head><title>Print document</title><style>
    * { box-sizing: border-box; }
    body { margin: 0; padding: 76px 20px 24px; background: #e8eef5; font-family: Arial, sans-serif; }
    #toolbar { position: fixed; inset: 0 0 auto; z-index: 2; height: 60px; padding: 10px 20px;
      display: flex; align-items: center; justify-content: space-between; background: white;
      border-bottom: 1px solid #d9e2ec; color: #334155; }
    #print { border: 0; border-radius: 7px; padding: 10px 18px; background: #1976d2;
      color: white; font-weight: 700; cursor: pointer; }
    #pages canvas, #pages img { display: block; max-width: 100%; height: auto; margin: 0 auto 18px;
      background: white; box-shadow: 0 4px 14px rgba(15, 23, 42, .16); }
    @media print { @page { margin: 0; } body { padding: 0; background: white; }
      #toolbar { display: none; } #pages canvas, #pages img { width: 100% !important; max-width: none;
      margin: 0; box-shadow: none; break-after: page; page-break-after: always; }
      #pages canvas:last-child, #pages img:last-child { break-after: auto; page-break-after: auto; } }
  </style></head><body><div id="toolbar"><strong id="status">Preparing pages…</strong>
  <button id="print" type="button" disabled>Print</button></div><main id="pages"></main></body></html>`);
  printDocument.close();
  const root = printDocument.getElementById('pages');
  const status = printDocument.getElementById('status');
  const printButton = printDocument.getElementById('print');
  let pdfDocument;
  try {
    if (mimeType.startsWith('image/')) {
      const image = printDocument.createElement('img');
      image.alt = 'Printable document image';
      image.src = `data:${mimeType};base64,${encoded}`;
      await image.decode();
      root.appendChild(image);
      status.textContent = '1 page ready';
      printButton.disabled = false;
      printButton.addEventListener('click', () => printWindow.print());
      printWindow.focus();
      window.setTimeout(() => printWindow.print(), 100);
      return;
    }
    const pdfjsLib = await import('./pdf.min.mjs');
    pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdfjs/pdf.worker.min.mjs';
    pdfDocument = await pdfjsLib.getDocument({data: decodeBase64(encoded)}).promise;
    for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
      const page = await pdfDocument.getPage(pageNumber);
      const viewport = page.getViewport({scale: 2});
      const canvas = printDocument.createElement('canvas');
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      root.appendChild(canvas);
      // The new tab backgrounds this module's window. Display rendering waits
      // for requestAnimationFrame there, which can stop while it is hidden.
      // PDF.js print intent renders without that foreground-only scheduler.
      await page.render({canvasContext: canvas.getContext('2d'), viewport, intent: 'print'}).promise;
      status.textContent = `Preparing page ${pageNumber} of ${pdfDocument.numPages}…`;
    }
    status.textContent = `${pdfDocument.numPages} page${pdfDocument.numPages === 1 ? '' : 's'} ready`;
    printButton.disabled = false;
    printButton.addEventListener('click', () => printWindow.print());
    printWindow.focus();
    window.setTimeout(() => printWindow.print(), 100);
  } catch (error) {
    console.error('Could not prepare PDF for printing', error);
    status.textContent = 'The document could not be prepared for printing.';
  }
}

window.ermsPdfViewer = {
  async open(id, encoded, labels) {
    const frame = document.getElementById(id);
    if (!frame) return false;
    const reader = frame.contentWindow;
    const signal = AbortSignal.any([AbortSignal.timeout(29000), frameController(frame).signal]);
    const cancelled = new Promise((_, reject) =>
      signal.addEventListener('abort', () => reject(signal.reason), {once: true}));
    const show = async () => {
      if (!reader.wathiqViewerReady) {
        await Promise.race([new Promise(resolve =>
          frame.addEventListener('load', resolve, {once: true, signal})), cancelled]);
      }
      if (!reader.wathiqViewerReady) throw new Error('PDF viewer failed to initialize');
      await reader.wathiqViewerReady;
      signal.throwIfAborted();
      const app = reader.PDFViewerApplication;
      reader.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !event.defaultPrevented && !app.overlayManager.active) {
          frame.dispatchEvent(new Event('wathiq-close-preview'));
        }
      });
      for (const [id, [name, tooltip]] of Object.entries(labels)) {
        const button = frame.contentDocument.getElementById(id);
        button.removeAttribute('data-l10n-id');
        button.setAttribute('aria-label', name);
        button.title = tooltip;
      }
      await app.open({data: decodeBase64(encoded)});
      signal.throwIfAborted();
      await app.pdfViewer.onePageRendered;
      return true;
    };
    try {
      return await Promise.race([show(), cancelled]);
    } catch {
      return false;
    }
  },
  close(id) {
    const frame = document.getElementById(id);
    if (!frame) return;
    frameController(frame).abort();
    void frame.contentWindow?.PDFViewerApplication?.close();
  },
  print(encoded, mimeType = 'application/pdf') {
    void printDocument(encoded, mimeType);
    return true;
  },
};
