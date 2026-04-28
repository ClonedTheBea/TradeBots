import unittest

from app.capture import parse_tradebots_hud


class CaptureParserTests(unittest.TestCase):
    def test_parse_tradebots_hud_labeled_values(self):
        raw_text = """
        Trade Bots
        Date: 2025-04-12
        Current Price: $123.45
        Cash: $9,876.50
        Holdings: 12
        """

        snapshot = parse_tradebots_hud(raw_text)

        self.assertEqual(snapshot.timestamp, "2025-04-12")
        self.assertEqual(snapshot.price, 123.45)
        self.assertEqual(snapshot.cash, 9876.50)
        self.assertEqual(snapshot.holdings, 12.0)
        self.assertEqual(snapshot.raw_text, raw_text)

    def test_parse_tradebots_hud_accepts_alternate_labels(self):
        raw_text = """
        Day - Round 18
        Stock Price 88.01
        Balance: 1,250
        Shares: 4.5
        """

        snapshot = parse_tradebots_hud(raw_text)

        self.assertEqual(snapshot.timestamp, "Round 18")
        self.assertEqual(snapshot.price, 88.01)
        self.assertEqual(snapshot.cash, 1250.0)
        self.assertEqual(snapshot.holdings, 4.5)

    def test_parse_tradebots_hud_raises_when_price_missing(self):
        with self.assertRaisesRegex(ValueError, "current price"):
            parse_tradebots_hud("Date: 2025-04-12\nCash: 1000")

    def test_parse_tradebots_hud_falls_back_to_date_like_text(self):
        snapshot = parse_tradebots_hud("2025-04-12\nPrice: 101.25")

        self.assertEqual(snapshot.timestamp, "2025-04-12")
        self.assertEqual(snapshot.price, 101.25)

    def test_parse_tradebots_hud_accepts_trade_bots_top_bar(self):
        raw_text = "May 9 Yr 1   Price: $34.44 (-0.7%)   Cash: $495.00 (100%)   Holdings: $0.00"

        snapshot = parse_tradebots_hud(raw_text)

        self.assertEqual(snapshot.timestamp, "May 9 Yr 1")
        self.assertEqual(snapshot.price, 34.44)
        self.assertEqual(snapshot.cash, 495.0)
        self.assertEqual(snapshot.holdings, 0.0)

    def test_parse_tradebots_hud_falls_back_to_bottom_trade_panel_price(self):
        raw_text = "May 9 Yr 1\n$39.71 of stock @ $34.44\nTransaction Fee @ 2%: $6.79"

        snapshot = parse_tradebots_hud(raw_text)

        self.assertEqual(snapshot.timestamp, "May 9 Yr 1")
        self.assertEqual(snapshot.price, 34.44)

    def test_parse_tradebots_hud_accepts_compacted_game_date_from_ocr(self):
        snapshot = parse_tradebots_hud("May9Yr1 Price: $34.44 Cash: $495.09")

        self.assertEqual(snapshot.timestamp, "May 9 Yr 1")
        self.assertEqual(snapshot.price, 34.44)

    def test_parse_tradebots_hud_does_not_use_transaction_fee_as_price(self):
        with self.assertRaisesRegex(ValueError, "current price"):
            parse_tradebots_hud("May9Yr1 Price: =~\nTransaction Fee @ 2%: $6.79")

    def test_parse_tradebots_hud_accepts_red_mask_price_line(self):
        snapshot = parse_tradebots_hud("May9Yr1 Price: =~ Cash: $495.09\n$34.44 (-0.7%)")

        self.assertEqual(snapshot.timestamp, "May 9 Yr 1")
        self.assertEqual(snapshot.price, 34.44)


if __name__ == "__main__":
    unittest.main()
