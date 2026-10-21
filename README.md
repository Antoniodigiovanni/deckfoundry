# DeckFoundry

A private, single-user presentation studio with a project library, editable slide canvas, compact inspector, and an overlay conversation pane. Start blank, import UTF-8 HTML or PowerPoint, or select a reusable local template. Click text to edit, change basic typography and background in the inspector, and save a new revision. Add, duplicate, remove, and move slides using the toolbar. Alt+Left/Right navigates slides; Ctrl/Cmd+S saves. Navigation saves pending edits first. A failed save preserves local edits for review; a stale revision must be reloaded before saving again.

## Local setup

Requires Python 3.10+, Node 20+, and the existing dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci
# Provision Playwright Chromium, LibreOffice Impress, Poppler, and suitable fonts.
DECKFOUNDRY_PROJECTS_DIR=/var/lib/deckfoundry/projects .venv/bin/python web/app.py
```

The private data directory must already exist. Open http://127.0.0.1:8080. Run one process only: the server serializes writes and builds. Do not run CLI writers concurrently. No deployment configuration is changed by the studio.

## Imports and templates

HTML must contain 1–200 `section.slide` elements. Import reconstructs text from headings, paragraphs and list items, retaining supported inline font sizes, colors, alignment and position. Scripts, embedded documents, arbitrary stylesheets, SVG, forms, external resources and unsupported markup are discarded. Embedded PNG/JPEG data images are retained; linked HTML images are omitted. This is a simplified editable import, not a faithful browser snapshot. Source uploads must be valid UTF-8 and fit within 2 MiB.

PPTX import uses the existing Python presentation parser. It retains slide order, text boxes, basic positions, explicit font size/color/alignment, and common PNG/JPEG pictures. It does not reproduce masters, theme inheritance, charts, tables, grouped shapes, animations, advanced effects, rich text runs or uncommon fonts. Backgrounds default to white. Inspect the result before exporting; full PowerPoint fidelity is not supported. Embedded packages are never extracted or executed. Upload limit is 8 MiB; ZIP packages are bounded to 2,000 entries and 32 MiB expanded data. Each slide permits 80 elements and each text field 4,000 characters. Imports that exceed the editable 2 MiB source limit are rejected. Picture data increases that size.

Choose “Add to reusable templates” when importing a user-owned file. Templates are normalized HTML in `_templates/` inside the configured private data root and are excluded from presentation listings. An absent directory is an empty library; no example templates are supplied. Template selection creates an independent project. Use simple local filenames and project names containing letters, digits, underscores or hyphens. Symlinks and path escapes are rejected. Imported projects preserve the original upload alongside the normalized source. Templates store only the normalized reusable source.

All uploads, templates, sources, revisions and exports are private runtime data. Keep the data directory outside application source control. Never stage user decks or templates.

## Editing, preview and export

The canvas renders structured text and supported images using DOM text nodes and a small validated CSS property set. Imported markup never becomes executable browser HTML. The inspector edits text, font size, text color, alignment and slide background. Save writes all pending fields into one new source revision; old source versions remain intact. Slide actions also create revisions. There is no whole-document undo/redo; browser text editing supports its native local undo before saving.

Existing HTML-source projects retain their document shell and unsupported styles in source. Their canvas shows a simplified representation because arbitrary CSS/layout is deliberately not executed. The complete deck preview uses the same safe representation. Build runs the existing conversion/validation/rendering pipeline and creates current-version PowerPoint, PDF and source previews. Downloads are available after a successful build. Builds can take several minutes. Review output visually; package validation cannot certify layout fidelity. Branded projects retain their build guard and require their existing custom adapter.

Conversation requests contain only the active project name, revision, slide fields and bounded session history. The configured server-side chat connection and key handling are unchanged; secrets never reach the browser. The API currently returns a complete response rather than a stream. The pane shows progress, errors and retry. Proposed edits are text-only, validated against active fields and displayed for explicit apply or reject. Applying saves a revision and refreshes the canvas. Editing or navigating invalidates pending proposals. Nothing is applied automatically. Conversation history resets with project, slide or revision; the pane may retain readable earlier messages during the browser session.

## Security and operation

Keep the backend bound to loopback behind the separately managed authenticated HTTPS reverse proxy. The backend is not an authentication service. Preserve existing host/origin allowlisting, secure cookies and proxy authentication. `DECKFOUNDRY_ALLOWED_ORIGINS` accepts exact comma-separated origins; `DECKFOUNDRY_SECURE_COOKIE=1` enables secure cookies behind HTTPS. Every mutation requires a valid session CSRF token and matching Origin/Host. Read requests also enforce Host and any supplied Origin. Responses are no-store with strict CSP and security headers; no source HTML route is exposed.

Sessions expire after one idle hour, are bounded to 256, and vanish on restart. Chat prompts are limited to 2,000 characters, responses to 64 KiB and history to eight messages. Ordinary JSON writes are limited to 64 KiB; import JSON is limited to 12 MiB to accommodate base64. There are at most 200 slides, 1,000 library candidates, 10,000 entries per project and 64 MiB per download. Keep the private data root and its parents stable and inaccessible to other writers.

The converter disables page JavaScript and denies network requests. Existing locally provisioned source still runs through a browser layout engine and native document renderer during builds; retain OS account isolation. The connected chat server's independent tool privileges are not controlled by this app. Keep its existing configuration and access boundaries under separate administration.

## Verification

```sh
.venv/bin/python -m pytest tests -q
npm test
node --check web/app.js
node --check src/html-convert.js
git diff --check
```

Tests create generic temporary fixtures and mock chat responses; they do not need private project data or live model requests. Renderer integration tests require a functioning Chromium installation and LibreOffice/Poppler. A restricted execution environment may prevent Chromium startup even when installed.
