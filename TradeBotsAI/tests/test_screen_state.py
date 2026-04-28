import unittest

from game_interface.screen_state import (
    parse_game_date,
    parse_money,
    parse_percent,
    parse_screen_state,
)


class ScreenStateParserTests(unittest.TestCase):
    def test_parse_money(self):
        self.assertEqual(parse_money("$495.00"), 495.0)
        self.assertEqual(parse_money("S1,234.56"), 1234.56)
        self.assertIsNone(parse_money("no money here"))

    def test_parse_percent(self):
        self.assertEqual(parse_percent("3.24%"), 3.24)
        self.assertEqual(parse_percent("(-0.7%)"), -0.7)
        self.assertIsNone(parse_percent("no percent here"))

    def test_parse_game_date(self):
        self.assertEqual(parse_game_date("Mar 11 Yr 1"), "Mar 11 Yr 1")
        self.assertEqual(parse_game_date("May9Yr1"), "May 9 Yr 1")
        self.assertIsNone(parse_game_date("2026-04-28"))

    def test_parse_screen_state_from_clean_top_hud(self):
        text = (
            "Mar 11 Yr 1 Price: $28.99 (3.24%) Cash: $495.00 Holdings: $0.00 "
            "Selected: BUY Slider: 100%"
        )

        state = parse_screen_state(text)

        self.assertEqual(state.game_date, "Mar 11 Yr 1")
        self.assertEqual(state.price, 28.99)
        self.assertEqual(state.gain_percent, 3.24)
        self.assertEqual(state.cash, 495.0)
        self.assertEqual(state.holdings, 0.0)
        self.assertEqual(state.selected_trade_action, "BUY")
        self.assertEqual(state.slider_state, "100%")
        self.assertEqual(state.raw_text, text)
        self.assertIsNotNone(state.captured_at)

    def test_parse_screen_state_uses_red_mask_price_fallback(self):
        text = """
        [top-hud]
        May9Yr1 Price: =~ Cash: $495.09 (108%) Holdings: © 9
        [top-red-price]
        $34.44 (-0.7%)
        """

        state = parse_screen_state(text)

        self.assertEqual(state.game_date, "May 9 Yr 1")
        self.assertEqual(state.price, 34.44)
        self.assertEqual(state.gain_percent, -0.7)
        self.assertEqual(state.cash, 495.09)

    def test_parse_screen_state_does_not_treat_cash_as_price(self):
        state = parse_screen_state("May9Yr1 Price: =~ Cash: $495.09 Holdings: $0.00")

        self.assertIsNone(state.price)


if __name__ == "__main__":
    unittest.main()
