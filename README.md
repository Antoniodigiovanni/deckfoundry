# DeckFoundry

Local presentation engine and a deployable v0 web frontend for existing HTML-source projects. The frontend lists projects, navigates slides, provides a safe text preview, edits existing title/text/bullet/notes fields, and creates immutable source revisions through `src/project.py patch_revision`. It does not import or edit arbitrary PPTX files. Simple leaf `h1`, `h2`, `h3`, `p`, `li`, and notes elements are editable; nested markup and missing fields need an offline source workflow.

## Setup and local use

Requires Python 3.10+, Node 20+, and the existing engine dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci
PLAYWRIGHT_BROWSERS_PATH=/opt/deckfoundry/.cache/ms-playwright npx playwright install chromium
# Install LibreOffice Impress, Poppler and suitable fonts using your OS package manager.
DECKFOUNDRY_PROJECTS_DIR=/var/lib/deckfoundry/projects .venv/bin/python web/app.py
```

Open http://127.0.0.1:8080. The projects directory must already exist. Only direct child directories with HTML-authority `project.json` metadata and a current `versions/vNNNN/source.html` are listed. The app does not create or import projects. For trusted local source, the CLI supports:

```sh
.venv/bin/python src/project.py init projects/NAME input.html
.venv/bin/python src/project.py inspect projects/NAME --slide 1
.venv/bin/python src/project.py build projects/NAME
```

Apply explicitly creates a new source version; old versions remain intact. Stale edits fail with HTTP 409; reload and review again. Downloads refer only to the current version, and return an error until the artifact exists. Build/rebuild calls the existing project CLI, may refresh current-version build artifacts, and requires visual review. Text previews deliberately do not execute source HTML or reproduce layout. Branded projects remain visible with an unsupported build warning; the engine's brand guard is never bypassed. Arbitrary slide insertion, layout editing, and PPTX-authority editing are unsupported.

## Hermes

Set `HERMES_API_BASE_URL` to the API's OpenAI-compatible base URL (including `/v1` if required), `HERMES_API_MODEL` to a model listed by that endpoint (default `hermes-agent`), and `HERMES_API_KEY` in the server environment. Requests go server to server to `/chat/completions`; the browser never receives the configured key. Plain HTTP is accepted only for loopback endpoints by default. For a trusted private-network Hermes endpoint, explicitly set `HERMES_API_ALLOW_PRIVATE_HTTP=1`; use HTTPS for public/remote endpoints. Validate this endpoint against your Hermes installation. Responses must contain JSON content with a bounded `message` and nullable `ops` array. Each operation is `{slide, old, new}` using an exact active field source literal and HTML-escaped replacement text. Proposals appear pending until explicitly applied through the same validation and revision path as direct edits.

Configure the **Hermes API server** toolsets deliberately. The default API-server toolset can access the host, including files and terminal execution. This app does not enforce or reduce those privileges: Cloudflare Access controls who may reach the app, but any authorized user can send requests to the connected Hermes agent. Use the existing full-tool API only if that capability is intended for the protected users; otherwise configure a restricted `platform_toolsets.api_server` (for example `[web]`) and verify it before connecting. A prompt asking the agent not to use tools is not a security boundary.

Only the selected project name, revision, active slide fields and bounded session conversation are sent, not other slides or project files. Context resets when project, slide or revision changes. Prompts and slide content may be processed by Hermes's configured model provider. Sessions are in memory, expire after an hour of inactivity, and disappear on restart. Authenticate each user separately at the reverse proxy; do not share browser sessions.

## Deployment

Use a dedicated unprivileged account and a separately configured authenticated HTTPS reverse proxy. Bind defaults to `127.0.0.1`; do not expose this unauthenticated backend publicly. Have the proxy enforce authentication, request size limits, rate limits, connection limits, and an upstream timeout of at least 460 seconds for builds. Keep it on loopback and strip untrusted forwarding headers. The app validates `Host` and `Origin`; set `DECKFOUNDRY_ALLOWED_ORIGINS` to the exact external origin(s), comma-separated, when using a reverse proxy. No CORS access is enabled. Use `DECKFOUNDRY_SECURE_COOKIE=1` behind HTTPS (leave unset for direct local HTTP).

`deploy/deckfoundry.env.example` documents environment settings without credentials. Store the real environment file outside the repository with mode 0600; supply the key there. Adapt `deploy/deckfoundry.service` paths and account to your installation, install Chromium into the configured `/opt/deckfoundry/.cache/ms-playwright` path before enabling the service, then install/enable it yourself. Provision engine browser/system dependencies for that account. The service template limits write access to the projects directory; validate the sandbox with your renderer. This repository does not install services.

The v0 server is intentionally serial, providing one app writer and one build at a time. Run **one process only**, and do not run CLI writers or change project files while it runs. Treat projects and their HTML/CSS as trusted local input to the build engine; OS account isolation is still needed for rendering. Symlinks anywhere in a managed project are rejected. Administrators must keep the root and its parents stable and deny other users write access. This is not a sandbox for hostile project owners.

Limits: 64 KiB JSON requests/upstream responses; 2 MiB source; 200 slides; 80 fields per active slide; 40 edits per apply; 4,000 characters per field; 2,000 per chat prompt; eight conversation messages; 256 sessions; 1,000 project candidates; 10,000 filesystem entries per project; 64 MiB downloads. Socket idle timeout is 10 seconds, Hermes timeout 30 seconds, and build deadline 450 seconds. The frontend serves strict CSP and other security headers and requires a session CSRF token for writes. Source HTML is never served.

## Engine and tests

The engine retains scratch generation, template inheritance, validation, HTML conversion, and PDF/PNG rendering via its CLI. Build output remains editable in PowerPoint, with converter limitations and visual review requirements. Package checks do not certify layout fidelity or factual correctness. Renderer installation is required for integration tests.

```sh
.venv/bin/python -m pytest tests -q
npm test
node --check src/html-convert.js
node --check web/app.js
```

Tests use temporary generic fixtures. Keep templates, presentation sources/specs, project data, generated artifacts, credentials, and caches out of public Git history. Ignore rules do not remove already tracked files; review an explicit allowlist of changes before staging. Do not commit sensitive pre-existing tracked data.
