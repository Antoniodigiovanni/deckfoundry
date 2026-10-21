"""Local, serial DeckFoundry HTTP frontend. No third-party web dependencies."""
import html
import ipaddress
import http.cookies
import json
import itertools
import signal
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib import request, parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import project

LIMIT = 65536
SOURCE_LIMIT = 2 * 1024 * 1024
ID = re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
VERSION = re.compile(r'v[0-9]{4,8}\Z')
# Only leaf text elements are editable. Markup, attributes and layout stay intact.
SLOT = re.compile(r'<(h1|h2|h3|p|li|aside|div)\b([^<>]*)>([^<>]+)</\1\s*>', re.I)
STATIC = Path(__file__).parent


def normalize_origin(value):
    parsed = parse.urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Invalid origin')
    parsed.port  # Validate a supplied port.
    return parsed.scheme.lower() + '://' + parsed.netloc.lower()


def allowed_origins():
    configured = os.environ.get('DECKFOUNDRY_ALLOWED_ORIGINS', '').strip()
    if configured:
        values = configured.split(',')
    else:
        port = int(os.environ.get('DECKFOUNDRY_PORT', '8080'))
        values = [f'http://127.0.0.1:{port}', f'http://localhost:{port}']
    return {normalize_origin(value.strip()) for value in values if value.strip()}


def bounded_text(value, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('Invalid text')
    return value


class App:
    def __init__(self, root):
        self.root = Path(root).absolute()
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise ValueError('Projects root must not contain symlinks')
        self.sessions = {}

    def path(self, *parts):
        p = self.root
        for part in parts:
            if not part or part in ('.', '..') or '/' in part or '\\' in part:
                raise ValueError('Invalid path')
            p = p / part
            if p.is_symlink():
                raise ValueError('Symlink rejected')
        if not p.resolve().is_relative_to(self.root):
            raise ValueError('Path escape')
        return p

    def load(self, name):
        if not ID.fullmatch(name):
            raise ValueError('Invalid project')
        root = self.path(name)
        # Reject symlinks anywhere the existing engine could read/write, including old versions.
        count = 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            for item in dirs + files:
                count += 1
                if count > 10000 or (Path(directory) / item).is_symlink():
                    raise ValueError('Unsafe or oversized project tree')
        state_file = self.path(name, 'project.json')
        if state_file.stat().st_size > LIMIT:
            raise ValueError('Oversized metadata')
        state = json.loads(state_file.read_text())
        if not isinstance(state, dict) or state.get('authority') != 'html' or not VERSION.fullmatch(state.get('current', '')):
            raise ValueError('Only existing HTML-source projects supported')
        folder = self.path(name, 'versions', state['current'])
        changes_file = folder / 'changes.json'
        if changes_file.stat().st_size > LIMIT:
            raise ValueError('Oversized revision metadata')
        changes = json.loads(changes_file.read_text())
        parent = changes.get('parent')
        if parent is not None and (not isinstance(parent, str) or not VERSION.fullmatch(parent)):
            raise ValueError('Invalid parent revision')
        if parent:
            self.path(name, 'versions', parent)
        source = folder / 'source.html'
        if source.stat().st_size > SOURCE_LIMIT:
            raise ValueError('Source too large')
        text = source.read_text()
        fragments = project.slides(text)
        if not 1 <= len(fragments) <= 200:
            raise ValueError('Slide limit exceeded')
        return root, state, fragments

    def view(self, name, slide):
        _, state, fragments = self.load(name)
        if type(slide) is not int or not 1 <= slide <= len(fragments):
            raise ValueError('Invalid slide')
        slots = []
        for match in SLOT.finditer(fragments[slide-1].group()):
            tag, attrs, raw = match.groups()
            if tag.lower() in ('aside', 'div') and not re.search(r'\b(?:speaker-notes|notes)\b', attrs):
                continue
            if len(slots) >= 80 or len(raw) > 4000:
                raise ValueError('Slide fields exceed limit')
            slots.append({'kind': 'title' if tag.lower() == 'h1' else 'notes' if 'notes' in attrs else 'bullet' if tag.lower() == 'li' else 'text', 'old': raw, 'text': html.unescape(raw)})
        return {'project': name, 'base': state['current'], 'slide': slide,
                'slides': [x['title'][:200] for x in project.index(''.join(m.group() for m in fragments))],
                'fields': slots, 'unsupported': bool(state.get('brand'))}

    def validate_ops(self, view, ops):
        if not isinstance(ops, list) or not 1 <= len(ops) <= 40:
            raise ValueError('Expected 1–40 operations')
        allowed = {f['old'] for f in view['fields']}
        _, _, fragments = self.load(view['project'])
        fragment = fragments[view['slide'] - 1].group()
        seen = set()
        for op in ops:
            if not isinstance(op, dict) or set(op) != {'slide', 'old', 'new'}:
                raise ValueError('Invalid operation')
            if type(op['slide']) is not int or op['slide'] != view['slide'] or op['old'] not in allowed or op['old'] in seen:
                raise ValueError('Operation must match an active slide text field')
            bounded_text(op['old']); bounded_text(op['new'])
            # Ops contain exact source literals, with new content canonically escaped.
            if html.escape(html.unescape(op['new']), quote=False) != op['new']:
                raise ValueError('New text must be HTML escaped')
            if fragment.count(op['old']) != 1:
                raise ValueError('Old literal must match exactly once')
            fragment = fragment.replace(op['old'], op['new'], 1)
            seen.add(op['old'])
        return ops

    def apply(self, data):
        if set(data) != {'project', 'slide', 'base', 'ops'}:
            raise ValueError('Invalid apply payload')
        view = self.view(data['project'], data['slide'])
        if data['base'] != view['base']:
            raise Conflict()
        ops = self.validate_ops(view, data['ops'])
        root, _, _ = self.load(data['project'])
        result = project.patch_revision(root, {'base': data['base'], 'message': 'Web slide edit', 'ops': ops})
        return {'current': result['current']}

    def chat(self, session, data):
        if set(data) != {'project', 'slide', 'base', 'message'}:
            raise ValueError('Invalid chat payload')
        bounded_text(data['message'], 2000)
        view = self.view(data['project'], data['slide'])
        if data['base'] != view['base']:
            raise Conflict()
        base = os.environ.get('HERMES_API_BASE_URL', '')
        key = os.environ.get('HERMES_API_KEY', '')
        url = parse.urlsplit(base)
        if url.scheme not in ('http', 'https') or not url.netloc or not url.hostname or url.username or url.password or url.query or url.fragment or not key:
            raise ValueError('Hermes is not configured')
        if url.scheme == 'http':
            try:
                address = ipaddress.ip_address(url.hostname)
                local = address.is_loopback
                private = address.is_private
            except ValueError:
                local = url.hostname.lower() == 'localhost'
                private = False
            if not local and not (private and os.environ.get('HERMES_API_ALLOW_PRIVATE_HTTP') == '1'):
                raise ValueError('Non-loopback Hermes endpoints require HTTPS unless private HTTP is explicitly enabled')
        model = bounded_text(os.environ.get('HERMES_API_MODEL', 'hermes-agent'), 120)
        if not model.strip():
            raise ValueError('Hermes model is not configured')
        context = (data['project'], data['slide'], data['base'])
        if session.get('context') != context:
            session['history'] = []
            session['context'] = context
        active_context = {k: view[k] for k in ('project', 'base', 'slide', 'fields')}
        prompt = ('Return JSON only: {"message":string,"ops":null or [{"slide":integer,"old":exact field old literal,"new":HTML escaped text}]}. '
                  'At most 40 ops, 4000 characters per string, message <=4000 characters. Edit only provided fields. No tools needed. Active slide: ' + json.dumps(active_context))
        messages = [{'role': 'system', 'content': prompt}] + session.get('history', []) + [{'role': 'user', 'content': data['message']}]
        encoded = json.dumps({'model': model, 'messages': messages, 'max_tokens': 3000, 'stream': False}).encode()
        if len(encoded) > LIMIT:
            raise ValueError('Conversation context too large; select another slide to reset')
        req = request.Request(base.rstrip('/') + '/chat/completions', data=encoded,
                              headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        # Never forward redirects with credentials.
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with request.build_opener(request.ProxyHandler({}), NoRedirect).open(req, timeout=30) as response:
            raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Hermes response too large')
        answer = json.loads(json.loads(raw)['choices'][0]['message']['content'])
        if not isinstance(answer, dict) or set(answer) != {'message', 'ops'}:
            raise ValueError('Invalid proposal')
        bounded_text(answer['message'])
        strings = [answer['message']]
        if isinstance(answer['ops'], list):
            strings += [v for op in answer['ops'] if isinstance(op, dict) for v in op.values() if isinstance(v, str)]
        if any(key in value for value in strings):
            raise ValueError('Invalid proposal')
        if answer['ops'] is not None:
            self.validate_ops(view, answer['ops'])
        session['history'] = (session.get('history', []) + [{'role': 'user', 'content': data['message']}, {'role': 'assistant', 'content': json.dumps(answer)}])[-8:]
        return answer


def build_project(root):
    child = subprocess.Popen([sys.executable, str(Path(project.__file__)), 'build', str(root)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        code = child.wait(timeout=450)
        if code:
            raise subprocess.CalledProcessError(code, 'project build')
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        raise


class Conflict(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # Do not log project content, cookies, prompts or upstream errors.

    def send(self, status, body, content_type='application/json', cookie=None, attachment=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for k, v in {'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'", 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'}.items():
            self.send_header(k, v)
        if cookie:
            self.send_header('Set-Cookie', cookie)
        if attachment:
            self.send_header('Content-Disposition', 'attachment; filename="' + attachment + '"')
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        now = time.monotonic()
        app = self.server.app
        app.sessions = {k: v for k, v in app.sessions.items() if now - v['time'] < 3600}
        cookies = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
        sid = cookies['df'].value if 'df' in cookies else ''
        if sid not in app.sessions:
            if len(app.sessions) >= 256:
                oldest = min(app.sessions, key=lambda key: app.sessions[key]['time'])
                del app.sessions[oldest]
            sid = secrets.token_urlsafe(32)
            app.sessions[sid] = {'csrf': secrets.token_urlsafe(32), 'time': now}
        session = app.sessions[sid]
        session['time'] = now
        return session, 'df=' + sid + '; HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if os.environ.get('DECKFOUNDRY_SECURE_COOKIE') == '1' else '')

    def send_error(self, code, message=None, explain=None):
        self.send(code, {'error': 'Request rejected'})

    def do_GET(self):
        self.handle_request(False)

    def do_POST(self):
        self.handle_request(True)

    def handle_request(self, post):
        try:
            if not self.request_origin_ok(post):
                return self.send(403, {'error': 'Host or Origin rejected'})
            session, cookie = self.session()
            url = parse.urlsplit(self.path)
            path = url.path
            app = self.server.app
            if post:
                if self.headers.get('X-CSRF-Token') != session['csrf']:
                    return self.send(403, {'error': 'CSRF token required'})
                if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
                    raise ValueError('JSON required')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= LIMIT:
                    raise ValueError('Payload limit exceeded')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Object required')
                if path == '/api/apply':
                    result = app.apply(data)
                elif path == '/api/chat':
                    result = app.chat(session, data)
                elif path == '/api/build':
                    if set(data) != {'project', 'base'}:
                        raise ValueError('Invalid build payload')
                    root, state, _ = app.load(data['project'])
                    if state['current'] != data['base']:
                        raise Conflict()
                    if state.get('brand'):
                        raise ValueError('Branded projects are unsupported by the generic build engine')
                    try:
                        build_project(root)
                    except (subprocess.SubprocessError, OSError):
                        return self.send(422, {'error': 'Build failed; inspect locally and rebuild. Visual review required.'})
                    result = {'message': 'Build complete. Visual review required.'}
                else:
                    return self.send(404, {'error': 'Not found'})
            elif path in ('/', '/app.js', '/style.css'):
                file, mime = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}[path]
                return self.send(200, (STATIC / file).read_bytes(), mime, cookie)
            elif path == '/api/projects':
                names = []
                for entry in itertools.islice(app.root.iterdir(), 1000):
                    try:
                        _, state, _ = app.load(entry.name)
                        names.append({'name': entry.name, 'current': state['current'], 'unsupported': bool(state.get('brand'))})
                    except (ValueError, OSError, KeyError, TypeError):
                        continue
                result = {'projects': names, 'csrf': session['csrf']}
            elif path == '/api/slide':
                q = parse.parse_qs(url.query, strict_parsing=True)
                result = app.view(q['project'][0], int(q['slide'][0]))
            elif path.startswith('/download/'):
                pieces = path.split('/')
                if len(pieces) != 6:
                    raise ValueError('Invalid download')
                _, _, name, version, kind, filename = pieces
                _, state, _ = app.load(name)
                if version != state['current'] or kind not in ('deck', 'render', 'html-source'):
                    raise ValueError('Only current output supported')
                if (kind == 'deck' and filename == 'deck.pptx'):
                    parts, mime = [], 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                elif kind == 'render' and filename == 'deck.pdf':
                    parts, mime = ['render'], 'application/pdf'
                elif kind in ('render', 'html-source') and re.fullmatch(r'slide-[0-9]{1,3}\.png', filename):
                    parts, mime = [kind], 'image/png'
                else:
                    raise ValueError('Invalid artifact')
                p = app.path(name, 'versions', version, *parts, filename)
                if p.stat().st_size > 64 * 1024 * 1024:
                    raise ValueError('Artifact too large')
                return self.send(200, p.read_bytes(), mime, cookie, filename)
            else:
                return self.send(404, {'error': 'Not found'})
            self.send(200, result, cookie=cookie)
        except Conflict:
            self.send(409, {'error': 'Stale revision; reload before applying'})
        except (ValueError, KeyError, TypeError, OSError, IndexError):
            self.send(400, {'error': 'Invalid request or unavailable resource'})
        except Exception:
            self.send(502, {'error': 'Operation failed'})

    def request_origin_ok(self, post):
        host = self.headers.get('Host', '').strip().lower()
        if not host:
            return False
        allowed = allowed_origins()
        if not any(parse.urlsplit(origin).netloc == host for origin in allowed):
            return False
        origin = self.headers.get('Origin')
        if post and not origin:
            return False
        if origin:
            try:
                normalized = normalize_origin(origin)
            except ValueError:
                return False
            if normalized not in allowed or parse.urlsplit(normalized).netloc != host:
                return False
        return True


def main():
    server = HTTPServer((os.environ.get('DECKFOUNDRY_BIND', '127.0.0.1'), int(os.environ.get('DECKFOUNDRY_PORT', '8080'))), Handler)
    server.app = App(os.environ.get('DECKFOUNDRY_PROJECTS_DIR', 'projects'))
    server.serve_forever()


if __name__ == '__main__':
    main()
