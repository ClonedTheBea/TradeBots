import unittest

from strategy.indicators import bollinger_bands, macd, rsi, sma


class IndicatorTests(unittest.TestCase):
    def test_sma_returns_none_until_period_is_available(self):
        values = [1, 2, 3, 4, 5]

        self.assertEqual(sma(values, 3), [None, None, 2.0, 3.0, 4.0])

    def test_rsi_for_strong_uptrend_reaches_100(self):
        values = list(range(1, 30))

        result = rsi(values, 14)

        self.assertEqual(result[14], 100.0)
        self.assertEqual(result[-1], 100.0)

    def test_macd_outputs_points_after_warmup(self):
        values = [float(value) for value in range(1, 60)]

        result = macd(values)

        self.assertIsNone(result[0])
        self.assertIsNotNone(result[-1])
        self.assertGreater(result[-1].macd, 0)

    def test_bollinger_bands_wrap_constant_series(self):
        values = [10.0] * 25

        result = bollinger_bands(values, 20)

        self.assertIsNone(result[18])
        self.assertEqual(result[-1].middle, 10.0)
        self.assertEqual(result[-1].upper, 10.0)
        self.assertEqual(result[-1].lower, 10.0)


if __name__ == "__main__":
    unittest.main()

