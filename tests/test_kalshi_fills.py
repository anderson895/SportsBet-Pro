"""Fill detection sa Kalshi orders.

Bakit mahalaga: noong 2026 ay nagpalit ang Kalshi sa `*_fp` fixed-point
STRING fields (fill_count_fp="8.00"). Ang lumang integer na `fill_count`
ay wala na. Nang hinahanap pa ng bot ang lumang field, LAGING 0 ang
nababasa nito — kaya hindi nakikita ang mga fill, hindi naitatala ang
PnL, at HINDI kumikilos ang Hedge Sentinel kapag isang panig lang ang
na-fill. Binabantayan ng mga test na ito ang regression na iyon.
"""
import asyncio
import unittest

from src.execution.kalshi_live import KalshiLiveExecutor, filled_count


class _FakeClient:
    """Sapat lang para sa get_fills(); nagbabalik ng canned na payload."""

    def __init__(self, orders=None, fills=None) -> None:
        self._orders = orders or {}
        self._fills = fills or []
        self.fills_calls: list[str] = []

    async def get_order(self, order_id: str) -> dict:
        return self._orders[order_id]

    async def get_fills(self, limit: int = 200, ticker=None) -> list[dict]:
        self.fills_calls.append(ticker)
        return self._fills


class FilledCountTest(unittest.TestCase):
    def test_reads_new_fixed_point_string_field(self) -> None:
        # Ito ang aktwal na hugis ng 2026 Kalshi API response
        order = {
            "status": "executed",
            "fill_count_fp": "5.00",
            "initial_count_fp": "5.00",
            "remaining_count_fp": "0.00",
        }
        self.assertEqual(filled_count(order), 5)

    def test_unfilled_new_format(self) -> None:
        order = {
            "status": "canceled",
            "fill_count_fp": "0.00",
            "initial_count_fp": "8.00",
            "remaining_count_fp": "0.00",
        }
        self.assertEqual(filled_count(order), 0)

    def test_partial_fill(self) -> None:
        order = {"fill_count_fp": "13.53", "initial_count_fp": "20.00"}
        self.assertEqual(filled_count(order), 13)

    def test_falls_back_to_legacy_integer_fields(self) -> None:
        # Kung babalik ang lumang format, dapat gumana pa rin
        self.assertEqual(filled_count({"fill_count": 7}), 7)
        self.assertEqual(
            filled_count({"initial_count": 10, "remaining_count": 4}), 6
        )

    def test_derives_from_initial_minus_remaining_fp(self) -> None:
        order = {"initial_count_fp": "8.00", "remaining_count_fp": "3.00"}
        self.assertEqual(filled_count(order), 5)

    def test_unknown_shape_is_zero_not_crash(self) -> None:
        self.assertEqual(filled_count({}), 0)
        self.assertEqual(filled_count({"fill_count_fp": "oops"}), 0)


class ExecutorGetFillsTest(unittest.TestCase):
    def test_uses_order_ids_when_available(self) -> None:
        client = _FakeClient(orders={
            "y1": {"fill_count_fp": "5.00"},
            "n1": {"fill_count_fp": "3.00"},
        })
        ex = KalshiLiveExecutor(client)
        ex._order_ids = {"YES": "y1", "NO": "n1"}
        yes, no = asyncio.run(ex.get_fills("TICK"))
        self.assertEqual((yes, no), (5, 3))
        self.assertEqual(client.fills_calls, [])  # hindi kailangan ang fallback

    def test_falls_back_to_ticker_lookup_after_restart(self) -> None:
        """Walang order IDs sa memory (na-restart ang app) — dapat pa rin
        makita ang fills mula sa history, kung hindi ay mabubulag ang bot
        sa isang position na hawak na nito."""
        client = _FakeClient(fills=[
            {"outcome_side": "yes", "count_fp": "5.00"},
            {"outcome_side": "no", "count_fp": "2.00"},
            {"outcome_side": "no", "count_fp": "3.00"},
        ])
        ex = KalshiLiveExecutor(client)  # walang _order_ids
        yes, no = asyncio.run(ex.get_fills("TICK"))
        self.assertEqual((yes, no), (5, 5))
        self.assertEqual(client.fills_calls, ["TICK"])

    def test_ticker_lookup_failure_is_safe(self) -> None:
        class Boom(_FakeClient):
            async def get_fills(self, limit=200, ticker=None):
                raise RuntimeError("network down")

        ex = KalshiLiveExecutor(Boom())
        self.assertEqual(asyncio.run(ex.get_fills("TICK")), (0, 0))


if __name__ == "__main__":
    unittest.main()
