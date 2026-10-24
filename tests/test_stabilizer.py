import math
import unittest

from stabilizer import Stabilizer, pressure_response


class StabilizerTests(unittest.TestCase):
    def test_disabled_has_no_delay(self):
        engine = Stabilizer('0')
        engine.start(0, 0, .2, 0)
        output = engine.add(30, 20, .7, .01)
        self.assertEqual((output[-1].x, output[-1].y, output[-1].pressure), (30, 20, .7))

    def test_stronger_levels_reduce_jitter(self):
        def deviation(level):
            engine = Stabilizer(level)
            points = engine.start(0, 0, .5, 0)
            for n in range(1, 241):
                t = n / 240
                points.extend(engine.add(200 * t, 3 * math.sin(t * 2 * math.pi * 30), .5, t))
            points.extend(engine.finish(200, 0, .5, 1))
            return math.sqrt(sum(p.y * p.y for p in points if .2 < p.time < .8) /
                             sum(1 for p in points if .2 < p.time < .8))
        self.assertLess(deviation('S-7'), deviation('3') * .15)

    def test_sampling_rate_does_not_change_strength(self):
        def path(rate):
            engine = Stabilizer('S-4')
            points = engine.start(0, 0, .5, 0)
            for n in range(1, rate + 1):
                t = n / rate
                points.extend(engine.add(300 * t, 60 * math.sin(t * 6), .5, t))
            points.extend(engine.finish(300, 60 * math.sin(6), .5, 1))
            return points
        slow, fast = path(60), path(240)
        self.assertEqual(len(slow), len(fast))
        self.assertLess(max(math.hypot(a.x - b.x, a.y - b.y) for a, b in zip(slow, fast)), .15)

    def test_release_drains_curved_tail_and_reaches_endpoint(self):
        engine = Stabilizer('S-7')
        engine.start(100, 0, .5, 0)
        for n in range(1, 201):
            t = n / 200
            engine.add(100 * math.cos(t * math.pi), 100 * math.sin(t * math.pi), .5, t)
        before = engine.last
        tail = engine.finish(-100, 0, .5, 1)
        self.assertGreater(len(tail), 15)
        self.assertAlmostEqual(tail[-1].x, -100)
        self.assertAlmostEqual(tail[-1].y, 0)
        # A single straight connection would have zero perpendicular deviation.
        dx, dy = -100 - before.x, -before.y
        deviation = max(abs(dx * (p.y - before.y) - dy * (p.x - before.x)) /
                        math.hypot(dx, dy) for p in tail)
        self.assertGreater(deviation, .2)

    def test_very_short_stroke_keeps_endpoint(self):
        engine = Stabilizer('S-7')
        engine.start(0, 0, .2, 0)
        tail = engine.finish(2, 3, .2, .001)
        self.assertEqual((tail[-1].x, tail[-1].y), (2, 3))

    def test_stationary_pen_catches_up(self):
        engine = Stabilizer('S-7')
        engine.start(0, 0, .5, 0)
        engine.add(30, 20, .5, .1)
        engine.advance(.4)
        self.assertAlmostEqual(engine.last.x, 30)
        self.assertAlmostEqual(engine.last.y, 20)

    def test_long_stroke_keeps_only_a_small_window(self):
        engine = Stabilizer('S-7')
        engine.start(0, 0, .5, 0)
        for n in range(1, 2001):
            engine.add(n, 0, .5, n / 240)
        self.assertLess(len(engine.samples), 60)

    def test_sparse_reports_follow_a_curve_not_a_polygon(self):
        engine = Stabilizer('1')
        points = engine.start(100, 0, .5, 0)
        for n in range(1, 25):  # a report every 30 degrees: straight chords would cut 3.4 px inside
            angle = n * math.pi / 6
            points.extend(engine.add(100 * math.cos(angle), 100 * math.sin(angle), .5, n / 60))
        middle = [p for p in points if .1 < p.time < .3]
        self.assertGreater(len(middle), 30)
        self.assertLess(max(abs(math.hypot(p.x, p.y) - 100) for p in middle), 1.)

    def test_timer_does_not_hold_a_moving_pen(self):
        engine = Stabilizer('S-2')
        engine.start(0, 0, .5, 0)
        engine.add(10, 0, .5, .01)
        self.assertEqual(engine.advance(.015), [])
        self.assertTrue(engine.advance(.2))

    def test_light_pressure_is_useful_but_heavy_pressure_remains_distinct(self):
        light = pressure_response(.1, 'Leve')
        heavy = pressure_response(.9, 'Leve')
        self.assertGreater(light, pressure_response(.1, 'Normal'))
        self.assertGreater(heavy - light, .35)
        self.assertAlmostEqual(pressure_response(1, 'Leve'), 1)
        values = [pressure_response(n / 100, 'Leve') for n in range(101)]
        self.assertTrue(all(a < b for a, b in zip(values, values[1:])))


if __name__ == '__main__':
    unittest.main()
