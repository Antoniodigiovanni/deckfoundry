"""Versioned local presentation projects. Exact patches, bounded context, regression gates."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from lxml import html
from engine import save_json, validate, render
import subprocess

PATTERN = re.compile(r'<section\b[^>]*\bclass=["\'][^"\']*\bslide\b[^"\']*["\'][^>]*>.*?</section>', re.S | re.I)


def digest(data):
    return hashlib.sha256(data.encode()).hexdigest()


def slides(source):
    return list(PATTERN.finditer(source))


def revision(root):
    state = json.loads((Path(root) / 'project.json').read_text())
    folder = Path(root) / 'versions' / state['current']
    return state, folder


def index(source):
    result = []
    for i, match in enumerate(slides(source), 1):
        node = html.fromstring(match.group())
        title = ' '.join(node.xpath('.//h1//text()'))
        result.append({'slide': i, 'id': node.get('data-num', str(i)), 'title': title,
                       'source_sha256': digest(match.group())})
    return result


def init(root, source, deck=None):
    root = Path(root)
    if (root / 'project.json').exists():
        raise ValueError('Project already exists')
    text = Path(source).read_text()
    if not slides(text):
        raise ValueError('Expected section.slide HTML source')
    folder = root / 'versions/v0001'
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'source.html').write_text(text)
    save_json(index(text), folder / 'index.json')
    if deck:
        check = validate(deck)
        if not check['passed'] or check['slide_count'] != len(slides(text)):
            raise ValueError('Baseline deck does not match source slide count or fails validation')
        shutil.copy2(deck, folder / 'deck.pptx')
    save_json({'version': 'v0001', 'parent': None, 'changed_slides': [], 'message': 'Imported baseline'}, folder / 'changes.json')
    save_json({'name': root.name, 'current': 'v0001', 'authority': 'html', 'schema': 1}, root / 'project.json')
    return {'project': str(root), 'current': 'v0001', 'slides': len(slides(text))}


def inspect(root, slide=None):
    state, folder = revision(root)
    text = (folder / 'source.html').read_text()
    if slide is None:
        return {'current': state['current'], 'slides': index(text)}
    entries = slides(text)
    if not 1 <= slide <= len(entries):
        raise ValueError('Invalid slide number')
    fragment = entries[slide-1].group()
    node = html.fromstring(fragment)
    return {'current': state['current'], 'slide': slide, 'sha256': digest(fragment),
            'text': ' '.join(node.itertext()), 'html': fragment}


def patch_revision(root, payload):
    state, old = revision(root)
    if payload.get('base') != state['current']:
        raise ValueError('Stale base revision; inspect latest before patching')
    text = (old / 'source.html').read_text()
    original = text
    entries = slides(text)
    parts = [m.group() for m in entries]
    changed = set()
    ops = payload.get('ops', [])
    if not ops:
        raise ValueError('Empty patch')
    for op in ops:
        n = op['slide']
        if not isinstance(n, int) or not 1 <= n <= len(parts):
            raise ValueError('Invalid slide number')
        if not op.get('old') or not isinstance(op.get('new'), str):
            raise ValueError('Each operation needs exact old and new strings')
        if parts[n-1].count(op['old']) != 1:
            raise ValueError(f'Slide {n}: old string must match exactly once')
        parts[n-1] = parts[n-1].replace(op['old'], op['new'], 1)
        changed.add(n)
    for m, part in reversed(list(zip(entries, parts))):
        text = text[:m.start()] + part + text[m.end():]
    if len(slides(text)) != len(entries):
        raise ValueError('Slide insertion/deletion needs a separate migration, not a text patch')
    for i,(before,after) in enumerate(zip(slides(original), slides(text)),1):
        if i not in changed and before.group() != after.group():
            raise ValueError('Untouched source slide changed')
    next_id = f"v{int(state['current'][1:])+1:04d}"
    dest = Path(root) / 'versions' / next_id
    dest.mkdir(parents=True, exist_ok=False)
    (dest / 'source.html').write_text(text)
    save_json(index(text), dest / 'index.json')
    save_json(payload, dest / 'patch.json')
    save_json({'version': next_id, 'parent': state['current'], 'changed_slides': sorted(changed),
               'message': payload.get('message', 'Slide update')}, dest / 'changes.json')
    state['current'] = next_id
    save_json(state, Path(root) / 'project.json')
    return {'current': next_id, 'changed_slides': sorted(changed), 'source': str(dest / 'source.html')}


def build(root):
    state, folder = revision(root)
    if state.get('brand'):
        raise ValueError('Branded project: generic HTML build would discard corporate styling. Generate content separately and apply the recorded brand adapter.')
    changes = json.loads((folder / 'changes.json').read_text())
    count = len(slides((folder / 'source.html').read_text()))
    subprocess.run(['node', str(Path(__file__).with_name('html-convert.js')), str(folder / 'source.html'),
                    str(folder / 'deck.pptx'), str(count)], check=True, timeout=180, capture_output=True)
    result = validate(folder / 'deck.pptx')
    save_json(result, folder / 'validation.json')
    if not result['passed']:
        raise ValueError('Package validation failed')
    regression = {'unchanged_slides_checked': [], 'mismatches': [], 'baseline_available': False}
    if changes['parent']:
        prior = folder.parent / changes['parent'] / 'html-source/spec.json'
        current = json.loads((folder / 'html-source/spec.json').read_text())
        if prior.exists():
            baseline = json.loads(prior.read_text())
            regression['baseline_available'] = True
            for i,(a,b) in enumerate(zip(baseline['slides'],current['slides']),1):
                if i not in changes['changed_slides']:
                    regression['unchanged_slides_checked'].append(i)
                    if a != b:
                        regression['mismatches'].append(i)
    save_json(regression, folder / 'regression.json')
    if regression['mismatches']:
        raise ValueError('Untouched slide geometry/text changed: ' + str(regression['mismatches']))
    rendered = render(folder / 'deck.pptx', folder / 'render')
    save_json({'status': 'visual_review_required', 'slides_to_review': changes['changed_slides'] or list(range(1,count+1)),
               'reason': 'Review all slides if baseline unavailable; otherwise review changed slides and contact sheet',
               'baseline_available': regression['baseline_available']}, folder / 'review.json')
    return {'version': state['current'], 'pptx': str(folder / 'deck.pptx'), 'pdf': rendered['pdf'],
            'changed_slides': changes['changed_slides'], 'regression': regression,
            'visual_review_required': True}


def main():
    p=argparse.ArgumentParser(description='Local versioned slide revisions')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('init');a.add_argument('project');a.add_argument('source');a.add_argument('--deck')
    a=sub.add_parser('inspect');a.add_argument('project');a.add_argument('--slide',type=int)
    a=sub.add_parser('patch');a.add_argument('project');a.add_argument('patch_file')
    a=sub.add_parser('build');a.add_argument('project')
    args=p.parse_args()
    if args.command=='init':result=init(args.project,args.source,args.deck)
    elif args.command=='inspect':result=inspect(args.project,args.slide)
    elif args.command=='patch':result=patch_revision(args.project,json.loads(Path(args.patch_file).read_text()))
    else:result=build(args.project)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
