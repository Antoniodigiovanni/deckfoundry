"""Generic temporary projects and in-memory HTTP requests/upstream mocks."""
import io
import email
from types import SimpleNamespace
import importlib.util
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import project
spec = importlib.util.spec_from_file_location('deckweb', ROOT / 'web/app.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
SOURCE = '<html><body><section class="slide"><h1>Title</h1><p>Body &amp; text</p><ul><li>Bullet</li></ul><aside class="speaker-notes">Notes</aside></section><section class="slide"><h1>Other slide</h1></section></body></html>'


@pytest.fixture
def app(tmp_path):
    source = tmp_path / 'input.html'
    source.write_text(SOURCE)
    root = tmp_path / 'projects'
    root.mkdir()
    project.init(root / 'generic', source)
    return web.App(root)



@pytest.fixture
def client(app):
    def call(path, data=None, cookie=None, csrf=None, raw=None, host='localhost:8080', origin='http://localhost:8080'):
        headers = {'Host': host}
        if origin:
            headers['Origin'] = origin
        if cookie:
            headers['Cookie'] = cookie
        if csrf:
            headers['X-CSRF-Token'] = csrf
        body = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            headers['Content-Length'] = str(len(body))
        wire = ((('POST' if body is not None else 'GET') + ' ' + path + ' HTTP/1.0\r\n') + ''.join(k + ': ' + v + '\r\n' for k, v in headers.items()) + '\r\n').encode() + (body or b'')
        handler = web.Handler.__new__(web.Handler)
        handler.rfile = io.BytesIO(wire)
        handler.wfile = io.BytesIO()
        handler.server = SimpleNamespace(app=app)
        handler.client_address = ('127.0.0.1', 1234)
        handler.handle_one_request()
        head, payload = handler.wfile.getvalue().split(b'\r\n\r\n', 1)
        lines = head.decode().split('\r\n', 1)
        return int(lines[0].split()[1]), email.message_from_string(lines[1]), payload
    call.app = app
    return call


def session(client):
    code, headers, raw = client('/api/projects')
    assert code == 200
    return headers['Set-Cookie'].split(';')[0], json.loads(raw)['csrf']


def patch():
    return {'project': 'generic', 'slide': 1, 'base': 'v0001', 'ops': [{'slide': 1, 'old': 'Title', 'new': 'Updated &lt;safe&gt;'}]}


def test_list_view_headers(client):
    code, headers, raw = client('/api/projects')
    assert json.loads(raw)['projects'] == [{'name': 'generic', 'current': 'v0001', 'unsupported': False}]
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['X-Frame-Options'] == 'DENY'
    assert "default-src 'none'" in headers['Content-Security-Policy']
    assert not headers.get('Access-Control-Allow-Origin')
    assert 'HttpOnly' in headers['Set-Cookie'] and 'SameSite=Strict' in headers['Set-Cookie']
    code, _, raw = client('/api/slide?project=generic&slide=1')
    data = json.loads(raw)
    assert [f['kind'] for f in data['fields']] == ['title', 'text', 'bullet', 'notes']
    assert data['fields'][1]['text'] == 'Body & text'
    assert 'html' not in data
    assert client('/')[0] == 200


def test_host_and_origin_rebinding_rejected(client):
    assert client('/api/projects', host='attacker.example', origin='http://attacker.example')[0] == 403
    assert client.app.sessions == {}
    cookie, csrf = session(client)
    assert client('/api/apply', patch(), cookie, csrf, host='localhost:8080', origin='http://attacker.example')[0] == 403
    assert client('/api/apply', patch(), cookie, csrf, origin=None)[0] == 403


def test_session_capacity_evicts_oldest_instead_of_locking_out(app, client):
    now = web.time.monotonic()
    app.sessions = {f'session-{i}': {'csrf': f'token-{i}', 'time': now - 300 + i}
                    for i in range(256)}
    code, headers, raw = client('/api/projects')
    assert code == 200
    assert json.loads(raw)['projects'][0]['name'] == 'generic'
    new_sid = headers['Set-Cookie'].split(';')[0].removeprefix('df=')
    assert new_sid in app.sessions
    assert len(app.sessions) == 256
    assert 'session-0' not in app.sessions


def test_apply_immutable_stale(client, app):
    cookie, csrf = session(client)
    assert client('/api/apply', patch(), cookie, csrf)[0] == 200
    assert (app.root / 'generic/versions/v0001/source.html').read_text() == SOURCE
    assert 'Updated &lt;safe&gt;' in (app.root / 'generic/versions/v0002/source.html').read_text()
    assert client('/api/apply', patch(), cookie, csrf)[0] == 409
    assert not (app.root / 'generic/versions/v0003').exists()


@pytest.mark.parametrize('change', [
    {'ops': []}, {'ops': None}, {'slide': True}, {'slide': 0}, {'extra': 1},
    {'ops': [{'slide': 1, 'old': 'Title', 'new': '<script>alert(1)</script>'}]},
    {'ops': [{'slide': 2, 'old': 'Other slide', 'new': 'Bad'}]},
    {'ops': [{'slide': 1, 'old': 'class="slide"', 'new': 'Bad'}]},
    {'ops': [{'slide': 1, 'old': 'Title', 'new': 'x' * 4001}]},
    {'ops': [{'slide': 1, 'old': [], 'new': 'x'}]},
])
def test_validation(client, app, change):
    cookie, csrf = session(client)
    data = patch(); data.update(change)
    assert client('/api/apply', data, cookie, csrf)[0] == 400
    assert project.revision(app.root / 'generic')[0]['current'] == 'v0001'


def test_csrf_payload_and_errors(client):
    cookie, csrf = session(client)
    assert client('/api/apply', patch(), cookie)[0] == 403
    assert client('/api/apply', cookie=cookie, csrf=csrf, raw=b'{' )[0] == 400
    assert client('/api/apply', cookie=cookie, csrf=csrf, raw=b'x' * 65537)[0] == 400
    code, headers, _ = client('/missing')
    assert code == 404 and headers['Cache-Control'] == 'no-store'


def test_paths_and_downloads(client, app, tmp_path):
    for name in ('..', '%2e%2e', 'generic%2f..', '%2Ftmp', 'generic%5c..'):
        assert client('/api/slide?project=' + name + '&slide=1')[0] == 400
    outside = tmp_path / 'outside'; outside.mkdir()
    (app.root / 'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError): app.load('escape')
    (app.root / 'generic/versions/v0001/deck.pptx').symlink_to(outside / 'secret')
    assert client('/download/generic/v0001/deck/deck.pptx')[0] == 400
    (app.root / 'generic/versions/v0001/deck.pptx').unlink()
    (app.root / 'generic/versions/v0001/deck.pptx').write_bytes(b'generic artifact')
    code, headers, body = client('/download/generic/v0001/deck/deck.pptx')
    assert code == 200 and body == b'generic artifact'
    assert 'attachment' in headers['Content-Disposition']
    assert client('/download/generic/v0000/deck/deck.pptx')[0] == 400
    assert client('/download/generic/v0001/deck/source.html')[0] == 400
    (app.root / 'generic/versions/v0001/source.html').unlink()
    (app.root / 'generic/versions/v0001/source.html').symlink_to(outside / 'secret')
    with pytest.raises(ValueError): app.load('generic')


def test_build_guard_and_call(client, app, monkeypatch):
    cookie, csrf = session(client)
    calls = []
    monkeypatch.setattr(web, 'build_project', lambda root: calls.append(root))
    data = {'project': 'generic', 'base': 'v0001'}
    assert client('/api/build', data, cookie, csrf)[0] == 200
    assert calls[0] == app.root / 'generic'
    state = app.root / 'generic/project.json'
    value = json.loads(state.read_text()); value['brand'] = 'local'; state.write_text(json.dumps(value))
    assert client('/api/build', data, cookie, csrf)[0] == 400
    assert len(calls) == 1


def test_chat_sessions_key_proposals(client, app, monkeypatch):
    calls = []
    key = 'mock-server-only-key'
    class Mock:
        def open(self, req, timeout):
            assert timeout == 30
            body = json.loads(req.data)
            calls.append((web.parse.urlsplit(req.full_url).path, req.headers['Authorization'], body))
            answer = {'message': 'Review this', 'ops': patch()['ops']}
            content = json.dumps({'choices': [{'message': {'content': json.dumps(answer)}}]}).encode()
            return io.BytesIO(content)
    monkeypatch.setattr(web.request, 'build_opener', lambda *a: Mock())
    base = 'http://127.0.0.1:8642'
    monkeypatch.setenv('HERMES_API_BASE_URL', base + '/v1')
    monkeypatch.setenv('HERMES_API_KEY', key)
    cookie, csrf = session(client)
    data = {'project': 'generic', 'slide': 1, 'base': 'v0001', 'message': 'Improve this'}
    code, _, raw = client('/api/chat', data, cookie, csrf)
    assert code == 200 and key.encode() not in raw
    assert project.revision(app.root / 'generic')[0]['current'] == 'v0001'
    assert calls[-1][0] == '/v1/chat/completions'
    assert calls[-1][1] == 'Bearer ' + key
    assert calls[-1][2]['model'] == 'hermes-agent'
    messages = calls[-1][2]['messages']
    assert len(messages) == 2 and 'Other slide' not in json.dumps(messages)
    assert client('/api/chat', data, cookie, csrf)[0] == 200
    assert len(calls[-1][2]['messages']) == 4
    cookie2, csrf2 = session(client)
    assert cookie2 != cookie
    assert client('/api/chat', data, cookie2, csrf2)[0] == 200
    assert len(calls[-1][2]['messages']) == 2
    data['slide'] = 2
    # Mock proposal for slide 1 is rejected against active slide 2.
    assert client('/api/chat', data, cookie, csrf)[0] == 400
    assert len(calls[-1][2]['messages']) == 2
    assert client('/api/apply', patch(), cookie, csrf)[0] == 200


@pytest.mark.parametrize('content', [
    b'x' * 65537,
    b'not json',
    json.dumps({'choices': [{'message': {'content': json.dumps({'message': 'private-key', 'ops': None})}}]}).encode(),
    json.dumps({'choices': [{'message': {'content': json.dumps({'message': 'bad', 'ops': [{'slide': 1, 'old': 'Title', 'new': '<img src=x>'}]})}}]}).encode(),
])
def test_chat_rejects_unsafe_response(client, monkeypatch, content):
    class Mock:
        def open(self, req, timeout): return io.BytesIO(content)
    monkeypatch.setattr(web.request, 'build_opener', lambda *a: Mock())
    monkeypatch.setenv('HERMES_API_BASE_URL', 'http://localhost:8642/v1')
    monkeypatch.setenv('HERMES_API_KEY', 'private-key')
    cookie, csrf = session(client)
    code, _, raw = client('/api/chat', {'project': 'generic', 'slide': 1, 'base': 'v0001', 'message': 'Help'}, cookie, csrf)
    assert code == 400 and b'private-key' not in raw


def test_symlink_root_and_metadata(app, tmp_path):
    alias = tmp_path / 'alias'
    alias.symlink_to(app.root, target_is_directory=True)
    with pytest.raises(ValueError): web.App(alias)
    state = app.root / 'generic/project.json'
    data = json.loads(state.read_text()); data['current'] = '../../elsewhere'
    state.write_text(json.dumps(data))
    with pytest.raises(ValueError): app.load('generic')


def test_build_deadline_kills_group(monkeypatch, tmp_path):
    killed = []
    class Child:
        pid = 12345
        def wait(self, timeout=None):
            if timeout: raise web.subprocess.TimeoutExpired('build', timeout)
            return -9
    monkeypatch.setattr(web.subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(web.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(web.subprocess.TimeoutExpired): web.build_project(tmp_path)
    assert killed == [(12345, web.signal.SIGKILL)]


def test_http_chat_refuses_remote_endpoint(app, monkeypatch):
    calls = []
    monkeypatch.setenv('HERMES_API_BASE_URL', 'http://api.example.test/v1')
    monkeypatch.setenv('HERMES_API_KEY', 'server-only-key')
    monkeypatch.setattr(web.request, 'build_opener', lambda *a: calls.append(a))
    with pytest.raises(ValueError):
        app.chat({'history': []}, {'project': 'generic', 'slide': 1, 'base': 'v0001', 'message': 'Help'})
    assert calls == []


def test_private_hermes_bridge_requires_explicit_opt_in(app, monkeypatch):
    calls = []

    class Mock:
        def open(self, req, timeout):
            calls.append(req.full_url)
            payload = {'choices': [{'message': {'content': json.dumps({'message': 'Ready', 'ops': None})}}]}
            return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(web.request, 'build_opener', lambda *a: Mock())
    monkeypatch.setenv('HERMES_API_BASE_URL', 'http://172.17.0.1:8642/v1')
    monkeypatch.setenv('HERMES_API_KEY', 'mock-server-only-key')
    data = {'project': 'generic', 'slide': 1, 'base': 'v0001', 'message': 'Hello'}
    with pytest.raises(ValueError):
        app.chat({'history': []}, data)
    assert calls == []

    monkeypatch.setenv('HERMES_API_ALLOW_PRIVATE_HTTP', '1')
    answer = app.chat({'history': []}, data)
    assert answer == {'message': 'Ready', 'ops': None}
    assert calls == ['http://172.17.0.1:8642/v1/chat/completions']
