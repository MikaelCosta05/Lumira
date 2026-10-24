"""Selection masks: shapes, magic wand, boolean modes and outlines.

A mask is an ARGB32 premultiplied image whose alpha channel is the selection
coverage, so it can be used directly with QPainter composition modes.
"""
import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath

FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def pixels(image):
    """Copy of an image as an (height, width, 4) BGRA uint8 array."""
    image = image.convertToFormat(FORMAT)
    data = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), dtype=np.uint8)
    return data.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width()].copy()


def alpha(image):
    return pixels(image)[..., 3]


def mask_from_alpha(values):
    height, width = values.shape
    data = np.zeros((height, width, 4), dtype=np.uint8)
    data[..., 3] = values
    buffer = data.tobytes()
    return QImage(buffer, width, height, width * 4, FORMAT).copy()


def blank_mask(width, height):
    mask = QImage(width, height, FORMAT)
    mask.fill(0)
    return mask


def path_mask(path, width, height, antialias=True):
    mask = blank_mask(width, height)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, antialias)
    painter.fillPath(path, QColor('black'))
    painter.end()
    return mask


def similar_region(image, x, y, tolerance=32, contiguous=True):
    """Boolean region of pixels whose channels differ at most `tolerance` from (x, y)."""
    values = pixels(image).astype(np.int16)
    region = np.abs(values - values[y, x]).max(axis=2) <= tolerance
    if contiguous:
        from scipy import ndimage
        labels, _ = ndimage.label(region)
        region = labels == labels[y, x]
    return region


def grow(region, amount):
    if amount <= 0:
        return region
    from scipy import ndimage
    return ndimage.binary_dilation(region, ndimage.generate_binary_structure(2, 2), iterations=int(amount))


def combine(old, new, mode):
    """Boolean selection modes on alpha arrays."""
    if old is None or mode == 'replace':
        return new
    if mode == 'add':
        return np.maximum(old, new)
    if mode == 'subtract':
        return np.minimum(old, 255 - new)
    return np.minimum(old, new)


def bounds(values):
    rows = np.flatnonzero(values.any(axis=1))
    if not len(rows):
        return QRect()
    cols = np.flatnonzero(values.any(axis=0))
    return QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


def _runs(edges):
    padded = np.zeros((edges.shape[0], edges.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = edges
    change = np.diff(padded, axis=1)
    rows, starts = np.nonzero(change == 1)
    _, ends = np.nonzero(change == -1)
    return rows, starts, ends


def outline(values, limit=250_000):
    """Pixel-edge outline of a mask, merged into horizontal/vertical runs."""
    inside = np.pad(values >= 128, 1)
    path = QPainterPath()
    horizontal = inside[1:, 1:-1] != inside[:-1, 1:-1]
    vertical = (inside[1:-1, 1:] != inside[1:-1, :-1]).T
    count = 0
    for edges, flip in ((horizontal, False), (vertical, True)):
        rows, starts, ends = _runs(edges)
        count += len(rows)
        if count > limit:
            return None
        for row, start, end in zip(rows.tolist(), starts.tolist(), ends.tolist()):
            if flip:
                path.moveTo(row, start)
                path.lineTo(row, end)
            else:
                path.moveTo(start, row)
                path.lineTo(end, row)
    return path


def transformed(mask, transform, width, height):
    """Map a mask through a transform onto a canvas of the given size."""
    result = blank_mask(width, height)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setTransform(transform)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result


def clip_to_mask(image, mask):
    """Copy of `image` keeping only the selected coverage."""
    result = QImage(image)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result


def remove_mask(image, mask):
    """Copy of `image` with the selected coverage erased."""
    result = QImage(image)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result


def colored(mask, color):
    """Solid color image with the mask's coverage as alpha."""
    result = QImage(mask.size(), FORMAT)
    result.fill(color)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result
