#!/usr/bin/env python3
"""Local PowerPoint analysis, template generation, package checks and rendering."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from PIL import Image, ImageDraw

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/package/2006/relationships',
      'c': 'http://schemas.openxmlformats.org/package/2006/content-types'}
EMU = 914400


def save_json(data, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def shape_data(shape, width, height):
    obj = {'name': shape.name, 'type': str(shape.shape_type), 'box': [round(v / EMU, 3) for v in (shape.left, shape.top, shape.width, shape.height)]}
    if shape.has_text_frame:
        obj['text'] = shape.text[:1200]
        runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
        obj['font_sizes'] = sorted(set(round(r.font.size.pt, 1) for r in runs if r.font.size))
        obj['fonts'] = sorted(set(r.font.name for r in runs if r.font.name))
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        obj['image_sha256'] = hashlib.sha256(shape.image.blob).hexdigest()
    if shape.is_placeholder:
        obj['placeholder'] = str(shape.placeholder_format.type)
    return obj


def analyze(source, out, brand=None):
    source = Path(source).resolve()
    prs = Presentation(source)
    width, height = prs.slide_width / EMU, prs.slide_height / EMU
    layouts = [{'index': i, 'name': lay.name, 'master': lay.slide_master.name,
                'placeholders': [{'name': s.name, 'type': str(s.placeholder_format.type),
                                  'box': [round(v / EMU, 3) for v in (s.left, s.top, s.width, s.height)]}
                                 for s in lay.placeholders]} for i, lay in enumerate(prs.slide_layouts)]
    font_count, size_count = Counter(), Counter()
    slides = []
    for i, slide in enumerate(prs.slides):
        shapes = [shape_data(s, width, height) for s in slide.shapes]
        for s in shapes:
            font_count.update(s.get('fonts', []))
            size_count.update(s.get('font_sizes', []))
        slides.append({'index': i + 1, 'layout': slide.slide_layout.name,
                       'layout_index': list(prs.slide_layouts).index(slide.slide_layout),
                       'shapes': shapes,
                       'background_mode': 'slide-override' if slide.background.fill.type is not None else 'master',
                       'notes': slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ''})
    with zipfile.ZipFile(source) as z:
        theme_files = [n for n in z.namelist() if re.fullmatch(r'ppt/theme/theme\d+\.xml', n)]
        themes = []
        for name in theme_files:
            root = ET.fromstring(z.read(name))
            clr = root.find('.//a:clrScheme', NS)
            fonts = root.find('.//a:fontScheme', NS)
            themes.append({'part': name,
                           'colors': {k.tag.split('}')[-1]: (next(iter(k)).attrib.get('val') or next(iter(k)).attrib.get('lastClr')) for k in clr} if clr is not None else {},
                           'major_font': fonts.find('a:majorFont/a:latin', NS).attrib.get('typeface') if fonts is not None and fonts.find('a:majorFont/a:latin', NS) is not None else None,
                           'minor_font': fonts.find('a:minorFont/a:latin', NS).attrib.get('typeface') if fonts is not None and fonts.find('a:minorFont/a:latin', NS) is not None else None})
        masters = [n for n in z.namelist() if re.fullmatch(r'ppt/slideMasters/slideMaster\d+\.xml', n)]
    profile = {'source': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'size_inches': [round(width, 4), round(height, 4)], 'aspect_ratio': round(width / height, 4),
               'masters': masters, 'themes': themes, 'layouts': layouts,
               'archetypes': [{'name': x['name'], 'layout_index': x['index'], 'placeholder_types': [p['type'] for p in x['placeholders']]} for x in layouts],
               'frequent_fonts': font_count.most_common(8), 'frequent_sizes_pt': size_count.most_common(8),
               'slides': slides}
    out = Path(out)
    save_json(profile, out)
    if brand:
        folder = Path(brand)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, folder / 'template.pptx')
        profile['source'] = 'template.pptx'
        save_json(profile, folder / 'profile.json')
        content_layout = next((l['index'] for l in layouts if any('BODY' in p['type'] or 'OBJECT' in p['type'] for p in l['placeholders']) and any('TITLE' in p['type'] for p in l['placeholders'])), 0)
        save_json({'name': folder.name, 'template': 'template.pptx', 'default_layout': content_layout,
                   'rules': ['Respect the inherited master and template typography.']}, folder / 'brand.json')
    return profile


def textbox(slide, text, x, y, w, h, size=20, bold=False, color=None):
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(.02)
    tf.margin_top = tf.margin_bottom = Inches(.01)
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(size)
    p.font.bold = bold
    if color:
        p.font.color.rgb = RGBColor.from_string(color.lstrip('#'))
    return shape


def load_spec(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(spec.get('slides'), list) or not spec['slides']:
        raise ValueError('Specification needs a nonempty slides array')
    for i, s in enumerate(spec['slides'], 1):
        if not isinstance(s.get('title'), str) or not s['title'].strip():
            raise ValueError(f'Slide {i}: nonempty title required')
        if len(s.get('bullets', [])) > 6:
            raise ValueError(f'Slide {i}: at most six bullets')
    return spec


def template_generate(spec_path, brand_path, out):
    spec = load_spec(spec_path)
    brand = Path(brand_path)
    cfg = json.loads((brand / 'brand.json').read_text())
    prs = Presentation(brand / cfg['template'])
    # Remove example slides while retaining all original layouts, masters, themes and media.
    for sid in list(prs.slides._sldIdLst):
        prs.part.drop_rel(sid.rId)
        prs.slides._sldIdLst.remove(sid)
    W, H = prs.slide_width / EMU, prs.slide_height / EMU
    for i, item in enumerate(spec['slides']):
        ix = item.get('layout_index', cfg.get('default_layout', 0))
        if not isinstance(ix, int) or ix < 0 or ix >= len(prs.slide_layouts):
            raise ValueError(f'Slide {i+1}: invalid layout_index {ix}')
        slide = prs.slides.add_slide(prs.slide_layouts[ix])
        if slide.shapes.title is not None:
            slide.shapes.title.text = item['title']
        else:
            textbox(slide, item['title'], .7, .45, W - 1.4, .7, size=28, bold=True)
        body = '\n'.join(item.get('bullets', []))
        body_ph = next((s for s in slide.placeholders if s.has_text_frame and s != slide.shapes.title and not s.text.strip()), None)
        if body and body_ph is not None:
            body_ph.text = body
        elif body:
            textbox(slide, body, .75, 1.75, W - 1.5, min(H - 2.25, 4.6), size=20)
        if item.get('notes'):
            slide.notes_slide.notes_text_frame.text = item['notes']
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)
    return str(out)


def part_path(rels_name):
    folder, filename = rels_name.rsplit('/_rels/', 1)
    return str(PurePosixPath(folder) / filename.removesuffix('.rels'))


def validate(path, original=None):
    errors, warnings = [], []
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if z.testzip() is not None:
            errors.append('ZIP CRC failure')
        if '[Content_Types].xml' not in names or 'ppt/presentation.xml' not in names:
            errors.append('Missing core PowerPoint part')
        for name in names:
            if name.endswith(('.xml', '.rels')):
                try:
                    root = ET.fromstring(z.read(name))
                except ET.ParseError as e:
                    errors.append(f'{name}: invalid XML: {e}')
                    continue
                if name.endswith('.rels'):
                    source = part_path(name) if '/_rels/' in name else ''
                    base = PurePosixPath(source).parent
                    for rel in root:
                        if rel.attrib.get('TargetMode') == 'External':
                            continue
                        target = rel.attrib.get('Target', '')
                        if target.startswith('/'):
                            dest = target.lstrip('/')
                        else:
                            import posixpath
                            dest = posixpath.normpath(str(base / target))
                        if dest not in names:
                            errors.append(f'{name}: missing target {dest}')
                for ext in root.findall('.//a:ext', NS):
                    if any(int(ext.attrib.get(k, '0')) < 0 for k in ('cx', 'cy')):
                        errors.append(f'{name}: negative extent')
                if name.startswith('ppt/charts/') and name.endswith('.xml'):
                    if not root.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/chart}plotArea'):
                        warnings.append(f'{name}: chart has no plot area')
        slide_parts = sorted(n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', n))
    prs = Presentation(path)
    if len(slide_parts) != len(prs.slides):
        errors.append('Slide part count differs from presentation slide count')
    texts = []
    for i, slide in enumerate(prs.slides, 1):
        for s in slide.shapes:
            if s.has_text_frame and s.text:
                texts.append({'slide': i, 'text': s.text})
                if re.search(r'\{\{[^}]+\}\}|\b(?:lorem ipsum|insert (?:title|text|content) here)\b', s.text, re.I):
                    warnings.append(f'Slide {i}: possible leftover placeholder: {s.text[:70]}')
            if s.left < 0 or s.top < 0 or s.left + s.width > prs.slide_width + EMU * .02 or s.top + s.height > prs.slide_height + EMU * .02:
                warnings.append(f'Slide {i}: {s.name} extends outside slide')
    if original:
        prior = validate(original)
        inherited = set(prior['errors'])
        # errors with part names may refer to inherited template parts; expose, never silently forgive.
        warnings.append(f'Original template had {len(inherited)} package errors (compare report separately)')
    return {'file': str(path.resolve()), 'slide_count': len(prs.slides), 'errors': errors,
            'warnings': warnings, 'texts': texts, 'passed': not errors}


def render(path, out):
    if not shutil.which('soffice') or not shutil.which('pdftoppm'):
        raise RuntimeError('Rendering requires soffice and pdftoppm (LibreOffice Impress + poppler-utils)')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = Path(path).resolve()
    profile_dir = out / '.lo-profile'
    subprocess.run(['soffice', '-env:UserInstallation=file://' + str(profile_dir), '--headless',
                    '--convert-to', 'pdf', '--outdir', str(out), str(source)], check=True, timeout=120)
    pdf = out / (source.stem + '.pdf')
    if not pdf.exists():
        raise RuntimeError('LibreOffice exited without producing a PDF')
    prefix = out / 'slide'
    subprocess.run(['pdftoppm', '-f', '1', '-png', '-r', '110', str(pdf), str(prefix)], check=True, timeout=120)
    imgs = sorted(out.glob('slide-*.png'))
    if not imgs:
        raise RuntimeError('PDF converted but no slide previews produced')
    from math import ceil
    thumbs = []
    for image in imgs:
        with Image.open(image) as im:
            cp = im.copy().convert('RGB')
            cp.thumbnail((520, 300))
            thumbs.append(cp)
    sheet = Image.new('RGB', (550 * min(3, len(thumbs)), 340 * ceil(len(thumbs) / 3)), 'white')
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(thumbs):
        x, y = (i % 3) * 550, (i // 3) * 340
        sheet.paste(im, (x + 12, y + 25))
        d.text((x + 12, y + 5), f'Slide {i+1}', fill='black')
    sheet.save(out / 'contact-sheet.png')
    return {'pdf': str(pdf), 'slides': [str(x) for x in imgs], 'contact_sheet': str(out / 'contact-sheet.png')}


def main():
    p = argparse.ArgumentParser(description='DeckFoundry independent local PPTX engine')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('analyze'); a.add_argument('pptx'); a.add_argument('--out', required=True); a.add_argument('--brand')
    g = sub.add_parser('generate'); g.add_argument('spec'); g.add_argument('--out', required=True); g.add_argument('--brand')
    v = sub.add_parser('validate'); v.add_argument('pptx'); v.add_argument('--out'); v.add_argument('--original')
    r = sub.add_parser('render'); r.add_argument('pptx'); r.add_argument('--out', required=True)
    h = sub.add_parser('html'); h.add_argument('source'); h.add_argument('--out', required=True); h.add_argument('--slides', type=int, default=5)
    args = p.parse_args()
    if args.command == 'html':
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['node', str(Path(__file__).with_name('html-convert.js')), args.source, args.out, str(args.slides)], check=True, timeout=120)
        result = validate(args.out)
        print(json.dumps(result))
        if not result['passed']: sys.exit(1)
    elif args.command == 'analyze':
        result = analyze(args.pptx, args.out, args.brand)
        print(json.dumps({'slides': len(result['slides']), 'layouts': len(result['layouts']), 'profile': args.out, 'brand': args.brand}))
    elif args.command == 'generate':
        if args.brand:
            template_generate(args.spec, args.brand, args.out)
        else:
            load_spec(args.spec)
            subprocess.run(['node', str(Path(__file__).with_name('generate.js')), args.spec, args.out], check=True)
        print(json.dumps({'pptx': args.out, 'validation': validate(args.out)}))
    elif args.command == 'validate':
        result = validate(args.pptx, args.original)
        if args.out: save_json(result, args.out)
        print(json.dumps(result))
        if not result['passed']: sys.exit(1)
    else:
        print(json.dumps(render(args.pptx, args.out)))


if __name__ == '__main__':
    main()
