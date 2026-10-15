# Capture PDF assets

These Changa fonts are derived from the existing Wathiq web fonts in
`frontend/webui/static/fonts`. The variable WOFF2 files were converted with
fontTools 4.66.1, instantiated at `wght=400`, and saved as static TrueType fonts
(`TTFont.flavor = None`). The Arabic, Latin, and Latin Extended subsets remain
separate; the renderer uses distinct CSS family aliases so font caches cannot
confuse their overlapping internal family names. The original SIL Open Font
License is retained in `OFL.txt`.

These are offline build artifacts. Rendering does not download or transform fonts.
WeasyPrint subsets and embeds the glyphs used by each PDF. Independent acceptance
checks verify embedding, subset flags, Unicode extraction, PDF/A-2u and PDF/UA-1.

`pdfua-extension.xml` declares the PDF/UA identification namespace in PDF/A's
extension metadata. The renderer adds the PDF/UA identification to the existing
PDF/A XMP metadata without discarding its RDF structure. A declaration alone is
not treated as conformance: both veraPDF profiles must pass before commit.

The pinned renderer also needs a narrow structure-tree correction for list items
containing paragraphs or nested lists: WeasyPrint 68.1 places those block tags
directly under `LI`, whereas PDF/UA-1 requires `Lbl`/`LBody` children. The PDF
finisher reparents the existing block tags into `LBody`, preserving marked content,
parent pointers, and reading order. Nested English/Arabic lists and real amendment
histories are independently validated to cover this renderer-specific correction.

`disposition/Changa.ttf` is the static regular Changa face with the three
existing subsets merged using `fontTools.merge.Merger` 4.66.1 (Latin, Latin
Extended, then Arabic). It contains 644 Unicode code points. It retains the
same Changa family/PostScript name and SIL OFL license above. This offline
artifact avoids selecting one of several partial faces with the same name in
LibreOffice. The disposition converter gives its child process a private
Fontconfig file containing this directory and a temporary cache directory;
no host font installation, font download or new deployment variable is used.
Every output PDF is checked for embedded Changa, including descendant fonts
and form resources; substitution fails generation. On native platforms whose
LibreOffice uses a different font backend, install this licensed face for the
API account if necessary; output validation still fails closed.
