import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from project import init, inspect, patch_revision, build

SOURCE='''<html><head><style>.slide{position:absolute;inset:0;background:#06142c;color:white}.slide h1{font:40px Arial}</style></head><body><div class="stage"><section class="slide"><h1>First slide</h1></section><section class="slide"><h1>Second slide</h1></section></div></body></html>'''


def test_versioned_patch(tmp_path):
    src=tmp_path/'in.html';src.write_text(SOURCE);root=tmp_path/'project'
    init(root,src)
    before=inspect(root,2)['sha256']
    patch_revision(root,{'base':'v0001','ops':[{'slide':1,'old':'First slide','new':'Updated slide'}]})
    assert inspect(root,2)['sha256']==before
    assert 'Updated slide' in inspect(root,1)['html']
    assert 'First slide' in (root/'versions/v0001/source.html').read_text()
    with pytest.raises(ValueError):patch_revision(root,{'base':'v0001','ops':[]})
    with pytest.raises(ValueError):patch_revision(root,{'base':'v0002','ops':[{'slide':1,'old':'absent','new':'x'}]})
    assert inspect(root)['current']=='v0002'


def test_build_regression(tmp_path):
    src=tmp_path/'in.html';src.write_text(SOURCE);root=tmp_path/'project'
    init(root,src);baseline=build(root)
    assert Path(baseline['pdf']).exists()
    patch_revision(root,{'base':'v0001','ops':[{'slide':1,'old':'First slide','new':'Updated slide'}]})
    result=build(root)
    assert result['regression']['baseline_available']
    assert result['regression']['unchanged_slides_checked']==[2]
    assert result['regression']['mismatches']==[]
    assert Path(result['pptx']).exists()


def test_structural_revision_immutable_and_stale(tmp_path):
    from project import source_revision
    src=tmp_path/'in.html';src.write_text(SOURCE);root=tmp_path/'project';init(root,src)
    source_revision(root,'v0001',SOURCE.replace('First slide','New title'))
    assert (root/'versions/v0001/source.html').read_text()==SOURCE
    assert inspect(root)['current']=='v0002'
    with pytest.raises(ValueError):source_revision(root,'v0001',SOURCE)
    with pytest.raises(ValueError):source_revision(root,'v0002','<html></html>')
