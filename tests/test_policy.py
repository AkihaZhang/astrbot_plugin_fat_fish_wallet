"""Contracts for the public, shared Fat Fish wallet policy."""
from __future__ import annotations

import inspect
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "fatfish_policy_test_package"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PACKAGE_ROOT)]
sys.modules[PACKAGE_NAME] = package

from fatfish_policy_test_package.main import FatFishWalletGuard


class Provider:
    def __init__(self, model):
        self._model = model

    def meta(self):
        return types.SimpleNamespace(id=self._model, model=self._model, type="")


class Context:
    def get_provider_by_id(self, provider_id):
        return Provider(provider_id) if provider_id else None


class StatusEvent:
    unified_msg_origin = "aiocqhttp:GroupMessage:123"

    def is_admin(self):
        return False

    def chain_result(self, chain):
        return chain


class FatFishPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "peak_periods": "14:00-18:00",
            "peak_weekdays": "0,1,2,3,4,5,6",
            "affected_providers": "deepseek",
            "gate_when_provider_unknown": True,
            "manual_override": "auto",
        }
        self.guard = FatFishWalletGuard(Context(), self.config)

    def policy(self, at, provider="deepseek/model"):
        return self.guard.get_wallet_policy(at=at, provider_id=provider)

    def test_october_7_2026_holiday_is_offpeak_in_auto_mode(self):
        at = datetime(2026, 10, 7, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        policy = self.policy(at)
        self.assertTrue(policy["holiday"])
        self.assertTrue(policy["holiday_name"])
        self.assertTrue(policy["allowed"])
        self.assertEqual(policy["state"], "offpeak")
        self.guard._is_whitelisted = lambda _event: False
        event = types.SimpleNamespace(is_admin=lambda: False)
        self.assertEqual(self.guard._gate_decision(event, policy), (False, ""))
        self.config["manual_override"] = "always_block"
        blocked_policy = self.policy(at)
        self.assertFalse(blocked_policy["allowed"])
        self.assertEqual(self.guard._gate_decision(event, blocked_policy), (True, "manual"))

    def test_manual_block_wins_on_holiday_and_unaffected_provider(self):
        at = datetime(2026, 10, 7, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.config["manual_override"] = "always_block"
        self.config["affected_providers"] = "openai"
        policy = self.policy(at)
        self.assertTrue(policy["holiday"])
        self.assertFalse(policy["provider_affected"])
        self.assertFalse(policy["allowed"])
        self.assertEqual(policy["state"], "forced block")

    def test_manual_allow_wins_for_unaffected_provider(self):
        self.config["manual_override"] = "always_allow"
        self.config["affected_providers"] = "openai"
        policy = self.policy(datetime(2026, 10, 7, 14, 55))
        self.assertFalse(policy["provider_affected"])
        self.assertTrue(policy["allowed"])
        self.assertEqual(policy["state"], "forced allow")

    def test_disabled_wallet_allows_even_with_manual_block(self):
        self.config.update(enabled=False, manual_override="always_block")
        policy = self.policy(datetime(2026, 1, 5, 15, 0))
        self.assertFalse(policy["enabled"])
        self.assertTrue(policy["allowed"])

    def test_automatic_weekday_peak_blocks_affected_provider(self):
        at = datetime(2026, 1, 5, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        policy = self.policy(at)
        self.assertFalse(policy["holiday"])
        self.assertTrue(policy["provider_affected"])
        self.assertFalse(policy["allowed"])
        self.assertEqual(policy["state"], "peak")

    def test_missing_holiday_dependency_falls_back_to_time_policy(self):
        at = datetime(2026, 1, 5, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.dict("sys.modules", {"holidays": None}):
            policy = self.policy(at)
        self.assertFalse(policy["holiday"])
        self.assertFalse(policy["allowed"])
        self.assertEqual(policy["state"], "peak")

    def test_message_gate_and_status_call_shared_public_policy(self):
        source = inspect.getsource(FatFishWalletGuard.peak_gate)
        status_source = inspect.getsource(FatFishWalletGuard.peak_status)
        self.assertIn("get_wallet_policy", source)
        self.assertIn("get_wallet_policy", status_source)

        event = types.SimpleNamespace(is_admin=lambda: False)
        self.guard._is_whitelisted = lambda _event: False
        self.config.update(manual_override="always_block", affected_providers="openai")
        policy = self.guard.get_wallet_policy(
            at=datetime(2026, 10, 7, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai")),
            provider_id="deepseek/model",
        )
        self.assertEqual(self.guard._gate_decision(event, policy), (True, "manual"))

    async def test_holiday_suppresses_peak_and_fake_offpeak_reminders(self):
        self.guard.get_kv_data = AsyncMock(return_value={})
        self.guard.put_kv_data = AsyncMock()
        self.guard._send_reminder = AsyncMock()
        now = datetime(2026, 10, 7, 13, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        await self.guard._check_reminders(now)
        self.guard._send_reminder.assert_not_awaited()
        self.guard.put_kv_data.assert_not_awaited()

    async def test_regular_peak_start_reminder_remains_enabled(self):
        self.guard.get_kv_data = AsyncMock(return_value={})
        self.guard.put_kv_data = AsyncMock()
        self.guard._send_reminder = AsyncMock()
        now = datetime(2026, 10, 8, 13, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        await self.guard._check_reminders(now)
        self.guard._send_reminder.assert_awaited_once_with("peak")

    async def test_peak_status_reports_policy_consistent_transition(self):
        now = datetime(2026, 10, 7, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.guard._now = lambda: now
        self.guard._load_whitelist = AsyncMock()
        self.guard._today_stats = AsyncMock(
            return_value={"date": "2026-10-07", "blocked": 0, "bypassed": 0}
        )
        self.guard._get_current_provider = AsyncMock(
            return_value=("deepseek/model", Provider("deepseek/model"))
        )
        result = [
            item
            async for item in self.guard.peak_status(StatusEvent())
        ]
        status_text = "\n".join(
            str(getattr(item, "text", item)) for item in result[0]
        )
        transition_line = next(
            line for line in status_text.splitlines() if line.startswith("下次切换：")
        )
        self.assertIn("高峰", transition_line)
        self.assertNotIn("→ 空闲", transition_line)
        self.assertIn("钱包策略：offpeak（允许）", status_text)

    async def test_manual_override_status_has_no_normal_transition(self):
        self.config["manual_override"] = "always_block"
        now = datetime(2026, 10, 7, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.guard._now = lambda: now
        self.guard._load_whitelist = AsyncMock()
        self.guard._today_stats = AsyncMock(
            return_value={"date": "2026-10-07", "blocked": 0, "bypassed": 0}
        )
        self.guard._get_current_provider = AsyncMock(
            return_value=("deepseek/model", Provider("deepseek/model"))
        )
        result = [item async for item in self.guard.peak_status(StatusEvent())]
        status_text = "\n".join(
            str(getattr(item, "text", item)) for item in result[0]
        )
        transition_line = next(
            line for line in status_text.splitlines() if line.startswith("下次切换：")
        )
        self.assertIn("当前策略下无预定切换", transition_line)
        self.assertIn("当前时段：手动策略覆盖", status_text)
        self.assertIn("钱包策略：forced block（拦截）", status_text)

    async def test_startup_log_uses_public_policy_on_holiday(self):
        now = datetime(2026, 10, 7, 14, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.guard._now = lambda: now
        self.guard._load_whitelist = AsyncMock()
        self.guard._load_known_groups = AsyncMock()
        self.config["reminder_enabled"] = False
        with patch("fatfish_policy_test_package.main.logger.info") as logger_info:
            await self.guard.initialize()
        rendered = " ".join(str(arg) for arg in logger_info.call_args.args)
        self.assertIn("offpeak", rendered)
        self.assertNotIn("当前高峰", rendered)


if __name__ == "__main__":
    unittest.main()
