"""Comic pages: panel layouts, page numbers and cover templates."""
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPen)

from document import Document, Layer

# Each row is (relative height, [relative widths]) and is listed top to bottom.
LAYOUTS = {
    'Página inteira (splash)': [(1, [1])],
    '2 faixas': [(1, [1]), (1, [1])],
    '3 faixas': [(1, [1])] * 3,
    '2 × 2': [(1, [1, 1])] * 2,
    'Clássico · 6 quadros': [(1, [1, 1])] * 3,
    '9 quadros': [(1, [1, 1, 1])] * 3,
    'Destaque no topo': [(1.5, [1]), (1, [1, 1]), (1, [1, 1, 1])],
    'Destaque embaixo': [(1, [1, 1]), (1, [1, 1]), (1.6, [1])],
    'Mangá dinâmico': [(1, [1, 2]), (1.3, [1]), (1, [2, 1, 1])],
    'Ação · grande central': [(.8, [1, 1, 1]), (1.6, [1]), (.8, [1, 1])],
    'Tirinha · 3 quadros': [(1, [1, 1, 1])],
    'Tirinha · 4 quadros': [(1, [1, 1, 1, 1])],
    'Yonkoma (4 verticais)': [(1, [1])] * 4,
}

COMIC_FORMATS = [
    ('Comic americano', 1988, 3075, 300, 38, 75),
    ('Mangá · B6 (tankōbon)', 1512, 2150, 300, 35, 70),
    ('Mangá · B5 (revista)', 2150, 3035, 300, 35, 75),
    ('Formatinho (13,5 × 19 cm)', 1594, 2244, 300, 35, 60),
    ('Graphic novel · A4', 2480, 3508, 300, 35, 90),
    ('Webtoon (tira vertical)', 800, 6000, 72, 0, 40),
    ('Tirinha horizontal', 3000, 1000, 300, 0, 40),
]

POSITIONS = [('Rodapé · lado externo', 'outer'), ('Rodapé · centro', 'bottom'),
             ('Rodapé · esquerda', 'bottom-left'), ('Rodapé · direita', 'bottom-right'),
             ('Topo · lado externo', 'top-outer'), ('Topo · centro', 'top')]


def panel_rects(width, height, rows, margin, gutter_x, gutter_y, rtl=False):
    """Rectangles in reading order. `rtl` numbers each row right to left (mangá)."""
    inner = QRectF(margin, margin, width - 2 * margin, height - 2 * margin)
    if inner.width() <= 0 or inner.height() <= 0:
        raise ValueError('A margem é maior que a página.')
    available = inner.height() - gutter_y * (len(rows) - 1)
    total = sum(weight for weight, _ in rows)
    y = inner.top()
    result = []
    for weight, columns in rows:
        row_height = available * weight / total
        space = inner.width() - gutter_x * (len(columns) - 1)
        x = inner.left()
        row = []
        for share in columns:
            panel_width = space * share / sum(columns)
            row.append(QRectF(x, y, panel_width, row_height))
            x += panel_width + gutter_x
        result += row[::-1] if rtl else row
        y += row_height + gutter_y
    if any(r.width() < 4 or r.height() < 4 for r in result):
        raise ValueError('Os quadros ficaram pequenos demais. Reduza margem ou espaçamento.')
    return result


def render_panels(width, height, rects, border, color, gutter=None, radius=0.):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if gutter is not None:
        painter.fillRect(image.rect(), gutter)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('black'))
        for rect in rects:
            painter.drawRoundedRect(rect, radius, radius)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    if border > 0:
        painter.setPen(QPen(color, border, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for rect in rects:
            painter.drawRoundedRect(rect.adjusted(border / 2, border / 2, -border / 2, -border / 2), radius, radius)
    painter.end()
    return image


def render_shapes(width, height, shapes, border, color, gutter=None):
    """Panel layer for any panel shapes: gutters filled, panels cleared, borders inked.

    Inset panels sit over their parent: they get a gutter-coloured halo so they read as separate.
    """
    from comic_layouts import panel_path
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paths = [(item, panel_path(item)) for item in shapes]
    if gutter is not None:
        painter.fillRect(image.rect(), gutter)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        for _, path in paths:
            painter.fillPath(path, QColor('black'))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    halo = QColor(gutter) if gutter is not None else QColor('white')
    for inset in (False, True):
        for item, path in paths:
            if bool(item.get('inset')) != inset:
                continue
            width_factor = 1.6 if item.get('style') == 'jagged' else 1.
            if inset:
                painter.strokePath(path, QPen(halo, max(border * 4, min(width, height) * .008), Qt.PenStyle.SolidLine,
                                              Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin))
                clear = painter.compositionMode()
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillPath(path, QColor('black'))
                painter.setCompositionMode(clear)
            if border > 0:
                join = Qt.PenJoinStyle.MiterJoin if item.get('style', 'straight') in ('straight', 'jagged')                     else Qt.PenJoinStyle.RoundJoin
                painter.strokePath(path, QPen(color, border * width_factor, Qt.PenStyle.SolidLine,
                                              Qt.PenCapStyle.SquareCap, join))
    painter.end()
    return image


def number_alignment(position, number, rtl):
    """Horizontal alignment and whether the number sits at the top."""
    top = position.startswith('top')
    if position in ('outer', 'top-outer'):
        right = (number % 2 == 1) != rtl
        return (Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft), top
    if position.endswith('left'):
        return Qt.AlignmentFlag.AlignLeft, top
    if position.endswith('right'):
        return Qt.AlignmentFlag.AlignRight, top
    return Qt.AlignmentFlag.AlignHCenter, top


def number_patch(width, height, number, style):
    """The page number drawn on a small image, and where it goes on the page."""
    text = f"{style.get('prefix', '')}{number}"
    font = QFont(style.get('font', 'Segoe UI'))
    font.setPixelSize(max(6, int(style.get('size', 48))))
    font.setBold(style.get('bold', True))
    horizontal, top = number_alignment(style.get('position', 'outer'), number, style.get('rtl', False))
    margin = style.get('margin', 80)
    metrics = QFontMetricsF(font)
    box = QRectF(margin, margin if top else height - margin - metrics.height(), width - 2 * margin, metrics.height())
    box = box.toAlignedRect().intersected(QRectF(0, 0, width, height).toAlignedRect())
    patch = QImage(max(1, box.width()), max(1, box.height()), QImage.Format.Format_ARGB32_Premultiplied)
    patch.fill(0)
    painter = QPainter(patch)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor(style.get('color', '#202020')))
    painter.drawText(QRectF(0, 0, box.width(), box.height()), horizontal | Qt.AlignmentFlag.AlignVCenter, text)
    painter.end()
    return patch, box.topLeft()


def place_patch(width, height, patch):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.drawImage(patch[1], patch[0])
    painter.end()
    return image


def page_number_image(width, height, number, style):
    return place_patch(width, height, number_patch(width, height, number, style))


NUMBER_LAYER = 'Número da página'


def apply_page_number(document, number, style, patch=None):
    """Create or replace the page number layer on every frame of the document."""
    if patch is None:
        patch = number_patch(document.width, document.height, number, style)
    image = place_patch(document.width, document.height, patch)
    comic = document.scene.setdefault('comic', {})
    layer_id = comic.get('number_layer')
    index = next((i for i, layer in enumerate(document.layers) if layer.id == layer_id), None)
    if index is None:
        index = next((i for i, layer in enumerate(document.layers) if layer.name == NUMBER_LAYER), None)
    if index is None:
        if len(document.layers) >= 64:
            raise ValueError('Limite de 64 camadas atingido.')
        layer = Layer(NUMBER_LAYER, image, content=True)
        document.layers.append(layer)
        document.sync_layers()
    else:
        layer = document.layers[index]
    comic['number_layer'] = layer.id
    comic['page'] = number
    comic['number_style'] = dict(style)
    for frame in document.frames:
        for item in frame.layers:
            if item.id == layer.id:
                item.image, item.content = QImage(image), True


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', Path(path).name)]


def project_size(path):
    with zipfile.ZipFile(path) as archive:
        value = json.loads(archive.read('document.json'))
    return int(value['width']), int(value['height'])


def batch_number(paths, start, style, step=1):
    """Number several saved pages in natural file-name order. Returns [(path, number)].

    Numbers are drawn first (text drawing stays on this thread); loading, numbering and saving
    then run for two pages at a time, and each page only re-compresses its number layer.
    """
    jobs = []
    for offset, path in enumerate(sorted(paths, key=natural_key)):
        number = start + offset * step
        width, height = project_size(path)
        jobs.append((path, number, number_patch(width, height, number, style)))

    def work(job):
        path, number, patch = job
        document = Document.load(path)
        apply_page_number(document, number, style, patch)
        document.changed()
        document.save(path)
        return path, number

    if len(jobs) < 2:
        return [work(job) for job in jobs]
    with ThreadPoolExecutor(2) as pool:
        return list(pool.map(work, jobs))


def fitted_font(family, text, max_width, max_size, bold=True):
    font = QFont(family)
    font.setBold(bold)
    size = max(8, int(max_size))
    while size > 8:
        font.setPixelSize(size)
        if QFontMetricsF(font).horizontalAdvance(text) <= max_width:
            break
        size = int(size * .92)
    font.setPixelSize(size)
    return font


def text_layer(width, height, draw):
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    draw(painter)
    painter.end()
    return image


def outlined_text(painter, font, text, baseline, rect, fill, outline, align=Qt.AlignmentFlag.AlignHCenter):
    metrics = QFontMetricsF(font)
    advance = metrics.horizontalAdvance(text)
    if align == Qt.AlignmentFlag.AlignLeft:
        x = rect.left()
    elif align == Qt.AlignmentFlag.AlignRight:
        x = rect.right() - advance
    else:
        x = rect.center().x() - advance / 2
    path = QPainterPath()
    path.addText(QPointF(x, baseline), font, text)
    size = font.pixelSize()
    shadow = QPainterPath(path)
    shadow.translate(size * .05, size * .06)
    painter.fillPath(shadow, QColor(0, 0, 0, 110))
    if outline is not None:
        painter.strokePath(path, QPen(outline, max(2., size * .09), Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.fillPath(path, fill)
    return metrics


def cover_document(options):
    """New document laid out as a comic cover with editable raster layers."""
    width, height = options['width'], options['height']
    bleed, safe = options.get('bleed', 0), options.get('safe', 0)
    document = Document(width, height)
    document.name = options.get('title') or 'Capa'
    document.dpi = options.get('dpi', 300)
    document.guides['bleed'], document.guides['safe'] = bleed, safe
    area = QRectF(bleed + safe, bleed + safe, width - 2 * (bleed + safe), height - 2 * (bleed + safe))
    top_color, bottom_color = QColor(options.get('top', '#1d3557')), QColor(options.get('bottom', '#e63946'))
    title_color, outline = QColor(options.get('title_color', '#ffd23f')), QColor(options.get('outline', '#111111'))

    def background(painter):
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, top_color)
        gradient.setColorAt(1, bottom_color)
        painter.fillRect(0, 0, width, height, QBrush(gradient))

    def title(painter):
        family = options.get('font', 'Impact')
        text = (options.get('title') or 'TÍTULO').upper()
        font = fitted_font(family, text, area.width(), height * .13)
        metrics = QFontMetricsF(font)
        top = options.get('title_position', 'top') == 'top'
        baseline = area.top() + height * .075 + metrics.ascent() if top else area.bottom() - height * .12
        outlined_text(painter, font, text, baseline, area, title_color, outline)
        subtitle = options.get('subtitle', '').strip()
        if subtitle:
            small = fitted_font('Segoe UI', subtitle, area.width(), height * .035)
            sub_metrics = QFontMetricsF(small)
            outlined_text(painter, small, subtitle, baseline + metrics.descent() + sub_metrics.ascent() + height * .01,
                          area, QColor('white'), outline)

    def info(painter):
        size = max(10, int(height * .028))
        issue = str(options.get('issue', '')).strip()
        if issue:
            font = QFont('Segoe UI')
            font.setBold(True)
            font.setPixelSize(size)
            label = f'Nº {issue}'
            box_width = QFontMetricsF(font).horizontalAdvance(label) + size * 1.2
            box = QRectF(area.left(), area.top(), box_width, size * 2)
            painter.fillRect(box, QColor('white'))
            painter.setPen(QPen(outline, max(2, size // 8)))
            painter.drawRect(box)
            painter.setFont(font)
            painter.setPen(QColor('#111'))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            extra = options.get('info', '').strip()
            if extra:
                font.setPixelSize(int(size * .6))
                font.setBold(False)
                painter.setFont(font)
                painter.setPen(QColor('white'))
                painter.drawText(QRectF(box.left(), box.bottom() + size * .2, area.width() / 2, size),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, extra)
        publisher = options.get('publisher', '').strip()
        if publisher:
            font = fitted_font('Segoe UI', publisher.upper(), area.width() * .35, size * .8)
            painter.setFont(font)
            box = QRectF(area.right() - area.width() * .35, area.top(), area.width() * .35, size * 2)
            painter.setPen(QColor('white'))
            painter.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, publisher.upper())
        author = options.get('author', '').strip()
        if author:
            font = fitted_font('Segoe UI', author, area.width() * .6, size)
            outlined_text(painter, font, author, area.bottom() - size * .4, area, QColor('white'), outline,
                          Qt.AlignmentFlag.AlignRight)

    def barcode(painter):
        box = QRectF(area.left(), area.bottom() - height * .085, width * .17, height * .085)
        painter.fillRect(box, QColor('white'))
        painter.setPen(QPen(QColor('#333'), max(1, width // 900)))
        painter.drawRect(box)
        font = QFont('Segoe UI')
        font.setPixelSize(max(8, int(box.height() * .14)))
        painter.setFont(font)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, 'Espaço para código de barras')

    layers = [('Fundo', background), ('Arte da capa', None), ('Título', title), ('Informações', info)]
    if options.get('barcode', True):
        layers.append(('Código de barras', barcode))
    document.layers = []
    for name, draw in layers:
        if draw is None:
            document.layers.append(document.blank_layer(name))
        else:
            document.layers.append(Layer(name, text_layer(width, height, draw), content=True))
    document.active = 1
    return document


# ------------------------------------------------------------ panel shapes

def page_shapes(document):
    """Panel shapes of a page in reading order (older projects only stored rectangles)."""
    from comic_layouts import shapes_from_rects
    comic = document.scene.get('comic', {})
    shapes = comic.get('shapes')
    if shapes:
        return shapes
    return shapes_from_rects([QRectF(*rect) for rect in comic.get('panels') or []])


def spacing(document):
    """Margin, gutter and border that suit the page size (margins respect bleed + safe area)."""
    short = min(document.width, document.height)
    inset = document.guides.get('bleed', 0) + document.guides.get('safe', 0)
    return max(inset, round(short * .05)), max(4, round(short * .022)), max(1, round(short * .0045))


def apply_panels(document, shapes, image, direction='ltr', style='grid', replace=True):
    """Put the panel layer on top (every frame) and remember the shapes for selection and numbers."""
    from comic_layouts import shape_bounds
    comic = document.scene.setdefault('comic', {})
    layer_id = comic.get('panel_layer') if replace else None
    existing = next((layer for layer in document.layers if layer.id == layer_id), None)
    if existing is None:
        if len(document.layers) >= 64:
            raise ValueError('Limite de 64 camadas atingido.')
        existing = Layer('Quadros', image, locked=True, content=True)
        document.layers.append(existing)
        document.sync_layers()
    for frame in document.frames:
        for layer in frame.layers:
            if layer.id == existing.id:
                layer.image, layer.content = QImage(image), True
    boxes = [shape_bounds(item) for item in shapes]
    comic.update(shapes=shapes, panels=[[b.x(), b.y(), b.width(), b.height()] for b in boxes],
                 panel_layer=existing.id, direction=direction, panel_style=style)
    return existing


def stylized_page(document, style='random', seed=None, direction='ltr', count=0, border_color='#111111',
                  gutter_color='#ffffff'):
    """One-click page: a stylized layout sized for the page, rendered as the panel layer image."""
    from comic_layouts import stylized_layout
    margin, gutter, border = spacing(document)
    used, shapes = stylized_layout(document.width, document.height, style, seed, margin, gutter,
                                   direction == 'rtl', count, page_margin=0)
    image = render_shapes(document.width, document.height, shapes, border, QColor(border_color),
                          QColor(gutter_color) if gutter_color else None)
    return used, shapes, image


def panel_at(document, point):
    """Index of the panel under a document point (insets win over the panel they sit on)."""
    from comic_layouts import panel_path
    shapes = page_shapes(document)
    hits = [index for index, item in enumerate(shapes) if panel_path(item).contains(point)]
    if not hits:
        return None
    insets = [index for index in hits if shapes[index].get('inset')]
    return (insets or hits)[-1]


def panel_selection_path(document, index):
    """Selectable area of a panel: its shape minus the inset panels drawn over it."""
    from comic_layouts import panel_path
    shapes = page_shapes(document)
    path = panel_path(shapes[index])
    if not shapes[index].get('inset'):
        for item in shapes:
            if item.get('inset') and item is not shapes[index]:
                path = path.subtracted(panel_path(item))
    return path


# ---------------------------------------------------------------- chapters

def chapter(folder, pages, width, height, dpi=300, style='random', direction='ltr', start=1, number_style=None,
            prefix='pagina', bleed=0, safe=0, seed=None, progress=None):
    """Create a folder of numbered pages, each with its own stylized layout. Returns the paths."""
    import random
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    digits = max(2, len(str(start + pages - 1)))
    names = [folder / f'{prefix} {start + offset:0{digits}d}.sdp' for offset in range(pages)]
    clash = next((path for path in names if path.exists()), None)
    if clash is not None:
        raise ValueError(f'Já existe um arquivo chamado “{clash.name}”. Escolha outra pasta ou nome.')
    from collections import deque
    paths, waiting, saved = [], deque(), 0
    # Pages are laid out here (text drawing stays on this thread) and saved in the background while
    # the next one is prepared; at most two wait, to keep memory low.
    with ThreadPoolExecutor(2) as pool:
        for offset, path in enumerate(names):
            document = Document(width, height)
            document.dpi = dpi
            document.guides['bleed'], document.guides['safe'] = bleed, safe
            number = start + offset
            document.name = path.stem
            document.layers[0].name = 'Arte'
            document.layers.insert(0, document.blank_layer('Rascunho'))
            document.active = 1
            _, shapes, image = stylized_page(document, style, rng.random(), direction)
            apply_panels(document, shapes, image, direction, style)
            if number_style is not None:
                apply_page_number(document, number, dict(number_style, rtl=direction == 'rtl'))
            waiting.append(pool.submit(document.save, path))
            paths.append(str(path))
            while len(waiting) > 2 or (offset == pages - 1 and waiting):
                waiting.popleft().result()
                saved += 1
                if progress is not None:
                    progress(saved, pages)
    return paths


def export_pdf(paths, output, progress=None):
    """One PDF page per project, at the project's size and resolution (natural file-name order)."""
    from PyQt6.QtCore import QMarginsF, QSizeF
    from PyQt6.QtGui import QPageLayout, QPageSize, QPdfWriter
    ordered = sorted(paths, key=natural_key)
    if not ordered:
        raise ValueError('Nenhuma página escolhida.')
    def flatten(path):  # runs ahead on a worker thread while the previous page is written
        document = Document.load(path)
        return document, document.composite(paper=True, subtitles=False)

    writer = painter = None
    pool = ThreadPoolExecutor(2)
    try:
        for index, (document, image) in enumerate(pool.map(flatten, ordered)):
            dpi = max(36, int(document.dpi or 300))
            size = QPageSize(QSizeF(document.width / dpi * 25.4, document.height / dpi * 25.4),
                             QPageSize.Unit.Millimeter, 'Página')
            layout = QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
            if writer is None:
                writer = QPdfWriter(str(output))
                writer.setResolution(dpi)
                writer.setPageLayout(layout)
                writer.setTitle(Path(output).stem)
                writer.setCreator('Lumira')
                painter = QPainter(writer)
            else:
                writer.setPageLayout(layout)
                writer.newPage()
            target = painter.viewport()
            painter.drawImage(QRectF(0, 0, target.width(), target.height()), image)
            if progress is not None:
                progress(index + 1, len(ordered))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if painter is not None:
            painter.end()
    return len(ordered)
