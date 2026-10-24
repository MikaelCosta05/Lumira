"""Time-based, buffered stroke smoothing, independent of Qt and pen pressure.

Levels are inspired by SAI's simple selector, not its proprietary algorithm.
Uniform sampling avoids making smoothing strength depend on tablet report rate. The
samples follow a Catmull-Rom curve through the pen reports rather than straight lines,
so fast curves stay round instead of turning into polygons.
On release, the buffered trajectory is drained instead of drawing one shortcut.
"""
from bisect import bisect_left
from dataclasses import dataclass
from math import exp, hypot


@dataclass(frozen=True)
class Sample:
    x: float
    y: float
    pressure: float
    time: float


class Stabilizer:
    STEP = 1 / 240
    IDLE = .025  # without reports for this long, the pen is taken to be resting
    LEVELS = ['0'] + [str(n) for n in range(1, 16)] + [f'S-{n}' for n in range(1, 8)]

    def __init__(self, level='S-4'):
        self.set_level(level)
        self.active = False

    def set_level(self, level):
        if str(level) not in self.LEVELS:
            raise ValueError('Unknown stabilizer level')
        self.level = str(level)
        if self.level == '0':
            self.delay = 0.0
        elif self.level.startswith('S-'):
            self.delay = 0.042 + (int(self.level[2:]) - 1) * 0.008
        else:
            self.delay = 0.004 + int(self.level) * 0.002
        self.sigma = self.delay / 2.5 if self.delay else 0.0

    def start(self, x, y, pressure, timestamp):
        self.active = True
        sample = Sample(x, y, max(0., min(1., pressure)), timestamp)
        self.samples = [sample]
        self.times = [timestamp]
        self.raw = self.last = sample
        self.points = [sample]  # latest pen reports, oldest first
        self.provisional = None  # first sample time of the newest curve segment, redrawn on the next report
        self.input_time = timestamp
        self.next_input = timestamp + self.STEP
        self.next_output = timestamp + self.STEP
        return [sample]

    def add(self, x, y, pressure, timestamp):
        if not self.active:
            return []
        self.input_time = max(timestamp, self.raw.time)
        return self._add(x, y, pressure, timestamp)

    def _add(self, x, y, pressure, timestamp):
        timestamp = max(timestamp, self.raw.time)
        sample = Sample(x, y, max(0., min(1., pressure)), timestamp)
        if self.delay == 0:
            self.raw = self.last = sample
            return [sample]
        if timestamp > self.raw.time:
            self.points.append(sample)
            del self.points[:-4]
            self._resample(new_point=True)
        else:  # a second report at the same instant moves the newest point
            self.points[-1] = sample
            self._resample(new_point=False)
        self.raw = sample
        return self._drain(timestamp - self.delay)

    def advance(self, timestamp):
        """Allow the brush to catch up while the pen remains stationary. While reports keep
        coming the pen is moving, and holding it in place here would make the line stutter."""
        if not self.active or timestamp - self.input_time < self.IDLE:
            return []
        return self._add(self.raw.x, self.raw.y, self.raw.pressure, timestamp)

    def _resample(self, new_point):
        """Uniform samples along a Catmull-Rom curve through the pen reports. The newest segment
        has no successor yet, so it is provisional and is redrawn once the next report arrives."""
        if self.provisional is not None:
            cut = bisect_left(self.times, self.provisional - 1e-9)
            del self.samples[cut:]
            del self.times[cut:]
            self.next_input = self.provisional
        points = self.points
        count = len(points)
        if new_point and count >= 3:
            self._segment(points[-3], points[-2], points[-4] if count >= 4 else None, points[-1])
        self.provisional = self.next_input
        if count >= 2:
            self._segment(points[-2], points[-1], points[-3] if count >= 3 else None, None)

    def _segment(self, a, b, before, after):
        """Hermite curve from report a to b, with tangents from the neighbouring reports. A tangent
        never exceeds the segment, so sudden stops or turns cannot make the curve loop or overshoot."""
        span = b.time - a.time
        if span <= 0:
            return
        limit = 1.5 * hypot(b.x - a.x, b.y - a.y) / span

        def velocity(p, q):
            if p is None or q is None or q.time <= p.time:
                return (b.x - a.x) / span, (b.y - a.y) / span
            vx, vy = (q.x - p.x) / (q.time - p.time), (q.y - p.y) / (q.time - p.time)
            speed = hypot(vx, vy)
            return (vx, vy) if speed <= limit else (vx * limit / speed, vy * limit / speed)

        (sx, sy), (ex, ey) = velocity(before, b), velocity(a, after)
        if after is None and before is not None:
            # No report after b yet: assume the curve keeps bending as it did (a parabola), so the
            # provisional end already heads the right way instead of arriving straight.
            cx, cy = (b.x - a.x) / span, (b.y - a.y) / span
            ex, ey = 2 * cx - sx, 2 * cy - sy
            speed = hypot(ex, ey)
            if speed > limit:
                ex, ey = ex * limit / speed, ey * limit / speed
        while self.next_input <= b.time + 1e-9:
            s = min(1., max(0., (self.next_input - a.time) / span))
            s2, s3 = s * s, s * s * s
            h00, h10, h01, h11 = 2 * s3 - 3 * s2 + 1, s3 - 2 * s2 + s, 3 * s2 - 2 * s3, s3 - s2
            self.samples.append(Sample(
                h00 * a.x + h01 * b.x + span * (h10 * sx + h11 * ex),
                h00 * a.y + h01 * b.y + span * (h10 * sy + h11 * ey),
                a.pressure + (b.pressure - a.pressure) * s,
                self.next_input,
            ))
            self.times.append(self.next_input)
            self.next_input += self.STEP

    def _smooth(self, timestamp):
        first = self.samples[0]
        last = self.raw
        start = bisect_left(self.times, timestamp - self.delay)
        end = bisect_left(self.times, timestamp + self.delay + 1e-9)
        window = self.samples[start:end]
        # Constant endpoint padding keeps the first/last positions well defined.
        padded = list(window)
        t = timestamp - self.delay
        while t < first.time:
            padded.append(Sample(first.x, first.y, first.pressure, t))
            t += self.STEP
        t = last.time + self.STEP
        while t <= timestamp + self.delay:
            padded.append(Sample(last.x, last.y, last.pressure, t))
            t += self.STEP
        weight_sum = x = y = pressure = 0.
        for point in padded:
            weight = exp(-0.5 * ((point.time - timestamp) / self.sigma) ** 2)
            weight_sum += weight
            x += point.x * weight
            y += point.y * weight
            pressure += point.pressure * weight
        if not weight_sum:
            return Sample(last.x, last.y, last.pressure, timestamp)
        return Sample(x / weight_sum, y / weight_sum, pressure / weight_sum, timestamp)

    def _drain(self, until):
        output = []
        while self.next_output <= until + 1e-9:
            point = self._smooth(self.next_output)
            output.append(point)
            self.last = point
            self.next_output += self.STEP
        # Retain only the moving window; long strokes do not retain all inputs. The provisional
        # segment is redrawn later, so a sample before it is always kept.
        keep = max(0, bisect_left(self.times, self.next_output - self.delay) - 1)
        if self.provisional is not None:
            keep = min(keep, max(0, bisect_left(self.times, self.provisional - 1e-9) - 1))
        if keep:
            del self.samples[:keep]
            del self.times[:keep]
        return output

    def finish(self, x, y, pressure, timestamp):
        if not self.active:
            return []
        self.input_time = max(timestamp, self.raw.time)
        output = self._add(x, y, pressure, timestamp)
        if self.delay:
            output.extend(self._drain(self.raw.time))
            # Include the exact lift position, including very short strokes.
            if hypot(self.last.x - x, self.last.y - y) > 1e-6:
                output.append(self.raw)
                self.last = self.raw
        self.active = False
        return output


def pressure_response(pressure, profile='Leve', minimum=0.15):
    """Light touch is useful immediately, with headroom for heavier pressure."""
    exponent = {'Leve': 0.55, 'Normal': 1.0, 'Firme': 1.6}[profile]
    pressure = max(0., min(1., pressure))
    return minimum + (1 - minimum) * pressure ** exponent
