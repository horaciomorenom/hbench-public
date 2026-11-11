import unittest

import numpy as np

from numerics import integrate


class TestIntegrate(unittest.TestCase):
    def test_exponential_decay(self):
        t, y = integrate(lambda t, y: -y, 1.0, 0.0, 2.0, 40)
        self.assertAlmostEqual(y[-1], np.exp(-2.0), places=7)

    def test_shapes(self):
        t, y = integrate(lambda t, y: -y, np.array([1.0, 2.0]), 0.0, 1.0, 10)
        self.assertEqual(t.shape, (11,))
        self.assertEqual(y.shape, (11, 2))


if __name__ == "__main__":
    unittest.main()
