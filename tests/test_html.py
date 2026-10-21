import json
import subprocess
import sys
from pathlib import Path
import zipfile
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]


def test_html_editable_offline(tmp_path):
    src = tmp_path / 'input.html'
    src.write_text('''<html><head><style>.stage{width:1440px;height:810px}.slide{position:absolute;inset:0;background:#06142c;color:white}h1{font:40px Arial}</style></head><body><div class="stage"><section class="slide"><h1>Editable title</h1><svg width="300" height="120"><rect x="10" y="10" width="100" height="70" fill="#20e0c0"/><text x="20" y="40" font-size="15">Node label</text><path d="M110 40 C 130 40 150 60 190 60" fill="none" stroke="#20e0c0"/></svg></section></div><script>throw Error("Must never run")</script><img src="https://example.invalid/private"></body></html>''')
    out = tmp_path / 'result.pptx'
    subprocess.run([sys.executable, str(ROOT / 'src/engine.py'), 'html', str(src), '--out', str(out), '--slides', '1'], check=True, timeout=90)
    prs = Presentation(out)
    assert len(prs.slides) == 1
    texts = [s.text for s in prs.slides[0].shapes if s.has_text_frame]
    assert 'Editable title' in texts
    assert 'Node label' in texts
    assert len(prs.slides[0].shapes) > 5
    with zipfile.ZipFile(out) as z:
        assert not any(n.startswith('ppt/media/') and not n.endswith('/') for n in z.namelist())
    spec = json.loads((tmp_path / 'html-source/spec.json').read_text())
    assert spec['network'] == 'denied'
    assert (tmp_path / 'html-source/slide-1.png').exists()


def test_html_invalid_slide_count(tmp_path):
    src = tmp_path / 'empty.html'
    src.write_text('<html><body></body></html>')
    proc = subprocess.run(['node', str(ROOT / 'src/html-convert.js'), str(src), str(tmp_path / 'bad.pptx'), '5'], capture_output=True, text=True, timeout=60)
    assert proc.returncode != 0
    assert not (tmp_path / 'bad.pptx').exists()
