// Configure the generic viewer before it binds its event handlers.
export function configurePreview(app, options) {
  const language = new URLSearchParams(location.search).get('lang') === 'ar' ? 'ar' : 'en-US';
  document.documentElement.lang = language;
  options.setAll({
    localeProperties: {lang: language},
    disablePreferences: true,
    workerSrc: '../pdf.worker.min.mjs',
    annotationEditorMode: -1, // AnnotationEditorType.DISABLE
    annotationMode: 1,        // Render embedded annotations, without interactive forms.
    enableXfa: false,
    enableScripting: false,
    isEvalSupported: false,
    enableHighlightFloatingButton: false,
    disableHistory: true,
    defaultZoomValue: '120',
    sidebarViewOnLoad: 0,
    externalLinkTarget: 2,    // Open links separately from the record.
    viewerCssTheme: 1,
  });

  // All supported file operations live in Wathiq's capability-aware outer
  // toolbar. This also covers document actions and PDF.js keyboard commands.
  const disabled = () => {};
  for (const operation of ['downloadOrSave', 'download', 'save', 'triggerPrinting']) {
    app[operation] = disabled;
  }
  window.print = disabled;
  for (const type of ['dragover', 'drop']) {
    window.addEventListener(type, event => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
    });
  }
  app.initializedPromise.then(() => {
    Object.assign(app.downloadManager, {
      download() {},
      downloadData() {},
      openOrDownloadData() { return false; },
    });
  });
}
