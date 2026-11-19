# Bundled PDF.js viewer

The library, worker, and generic viewer use Mozilla PDF.js 4.10.38. The source archive is [pdfjs-4.10.38-dist.zip](https://github.com/mozilla/pdf.js/releases/download/v4.10.38/pdfjs-4.10.38-dist.zip), SHA-256 `32bdd9c5198b77dbaa8f02de81f34476888b3abdd64b9fb5f607f81f01487e6a`. The WebUI serves these assets locally. The iframe loads the viewer and its Fluent translations on demand.

For an upgrade, update the library and worker together with the generic viewer HTML, CSS, module, images, character maps, standard fonts, and English and Arabic locale files. Retain upstream notices. The HTML loads the existing minified library and Wathiq stylesheet. The generic module calls the Wathiq configuration before startup, accepts the component supplied by the host, omits generic file opening and keeps document view history in memory. Preserve these adaptations when updating the bundle.

Wathiq’s outer dialog owns component switching, authorized Print and Download Original. The reader displays existing annotations. The component browser checks exercise the reader in English and Arabic.
