"""Board-free checks of screening measurements and refusal paths."""
import math
from pathlib import Path
import tempfile
import unittest

import screen


class ScreeningTests(unittest.TestCase):
    def test_interpolation_and_coverage(self):
        data = [[0., 0.], [1., 2.], [2., 4.]]
        self.assertEqual(screen.interpolate(data, .5, 1), 1.)
        self.assertEqual(screen.interpolate(data, 2., 1), 4.)
        for at in (-.1, 2.1):
            with self.assertRaises(ValueError):
                screen.interpolate(data, at, 1)

    def test_settling_uses_last_excursion_not_first_crossing(self):
        data = [[i*1e-8, 1.] for i in range(301)]
        data[0][1] = 0.
        data[100][1] = 1.01
        self.assertAlmostEqual(screen.settling(data, 0., 3e-6, 1), 1.01e-6)

    def test_settling_rejects_unstable_tail(self):
        data = [[i*1e-8, 1.+.01*(i % 2)] for i in range(301)]
        with self.assertRaises(ValueError):
            screen.settling(data, 0., 3e-6, 1)

    def test_settling_rejects_short_capture(self):
        with self.assertRaises(ValueError):
            screen.settling([[0., 0.], [1e-6, 1.]], 0., 3e-6, 1)

    def test_surrogate_reproduces_datasheet_settling_law(self):
        for source in (0, 68, 1000, 10000):
            calculated = math.log(8192)*(screen.RON+source)*screen.CSAMPLE
            self.assertAlmostEqual(calculated*1e9, .054*source+205, places=9)
        self.assertAlmostEqual(screen.ACQUISITION*1e9, 769.230769, places=5)

    def test_data_refuses_nan_bad_width_and_nonmonotonic_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'result.dat'
            for bad in ('x y\n0 1\n1 nan\n', 'x y\n0 1\n1 2 3\n',
                        'x y\n1 1\n0 2\n', 'x y\n0 1\n0 2\n', 'x y\n'):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    screen.read_data(path, 2)
            path.write_text('x y\n0 1\n1 2\n')
            self.assertEqual(screen.read_data(path, 2), [[0., 1.], [1., 2.]])

    def test_netlist_override_refuses_missing_or_duplicate_target(self):
        self.assertEqual(screen.replace_once('before target after', 'target', 'new'),
                         'before new after')
        for text in ('missing', 'target target'):
            with self.assertRaises(ValueError):
                screen.replace_once(text, 'target', 'new')

    def test_sampling_switches_and_previous_levels_are_explicit(self):
        fixture = screen.acquisition_fixture(.5, 2.5, screen.ACQUISITION)
        self.assertIn('VPREV0 previous0 0 0.5', fixture)
        self.assertIn('VPREV1 previous1 0 2.5', fixture)
        self.assertIn('SADC0 adc0 sample0 track 0 SAMPLE', fixture)
        self.assertIn('SADC1 adc1 sample1 track 0 SAMPLE', fixture)


if __name__ == '__main__':
    unittest.main()
