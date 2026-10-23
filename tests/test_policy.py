"""Contracts for the public, shared Fat Fish wallet policy."""
from __future__ import annotations

import asyncio
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

from fatfish_policy_test_package.main import NOTICE_LEDGER, FatFishWalletGuard


class Provider:
    def __init__(self, model):
        self._model = model

    def meta(self):
        return types.SimpleNamespace(id=self._model, model=self._model, type="")


class Context:
    def get_provider_by_id(self, provider_id):
        return Provider(provider_id) if provider_id else None


class BurstContext(Context):
    def __init__(self, sent_messages):
        self._sent = sent_messages

    async def get_current_chat_provider_id(self, umo=None):
        return "deepseek-chat"

    async def send_message(self, umo, chain):
        self._sent.append((umo, chain))


class StatusEvent:
    unified_msg_origin = "aiocqhttp:GroupMessage:123"

    def is_admin(self):
        return False

    def chain_result(self, chain):
        return chain


class FatFishPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        NOTICE_LEDGER._day = ""
        NOTICE_LEDGER._keys.clear()
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
        self.guard._groups_loaded = True
        self.guard._known_groups = {"aiocqhttp:GroupMessage:1"}
        now = datetime(2026, 10, 8, 13, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        await self.guard._check_reminders(now)
        self.guard._send_reminder.assert_awaited_once_with(
            "peak", ["aiocqhttp:GroupMessage:1"]
        )

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


class SlowKV:
    """带 IO 延迟的 KV，用来把「查完再写」之间的窗口撑开。"""

    def __init__(self) -> None:
        self.data: dict = {}
        self.fail_writes = False

    async def get(self, key, default=None):
        await asyncio.sleep(0.01)
        return self.data.get(key, default)

    async def put(self, key, value):
        await asyncio.sleep(0.01)
        if self.fail_writes:
            raise RuntimeError("kv write failed")
        self.data[key] = value


class BurstEvent:
    def __init__(self, umo, private=False):
        self.unified_msg_origin = umo
        self.sent: list = []
        self.stopped = False
        self.llm_allowed = None
        self.is_at_or_wake_command = True
        self._private = private

    def is_admin(self):
        return False

    def is_private_chat(self):
        return self._private

    def get_group_id(self):
        return None if self._private else self.unified_msg_origin.rsplit(":", 1)[-1]

    def get_sender_id(self):
        return "u1"

    def get_message_str(self):
        return "你好"

    def should_call_llm(self, value):
        self.llm_allowed = value

    def stop_event(self):
        self.stopped = True

    async def send(self, chain):
        self.sent.append(chain)

    def chain_result(self, chain):
        return chain

    def plain_result(self, text):
        return text


def event_text(event) -> str:
    return "\n".join(
        str(getattr(item, "text", item)) for item in event.sent[0].chain
    )


class NoticeSpamTests(unittest.IsolatedAsyncioTestCase):
    """时段切换时的重复推送回归。AstrBot 每条消息一个 task，并发下会连发。"""

    def setUp(self):
        NOTICE_LEDGER._day = ""
        NOTICE_LEDGER._keys.clear()
        self.kv = SlowKV()
        self.sent_messages: list = []

    def make_guard(self, **overrides):
        config = {
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "peak_periods": "09:00-12:00,14:00-18:30",
            "peak_weekdays": "0,1,2,3,4,5,6",
            "affected_providers": "deepseek",
            "gate_when_provider_unknown": True,
            "manual_override": "auto",
            "attach_images": False,
            "announce_transition": True,
            "transition_notice_window_minutes": 10,
        }
        config.update(overrides)
        guard = FatFishWalletGuard(BurstContext(self.sent_messages), config)
        guard.get_kv_data = self.kv.get
        guard.put_kv_data = self.kv.put
        guard._wl_loaded = True
        guard._wl_users = set()
        guard._wl_groups = set()
        guard._groups_loaded = True
        guard._known_groups = set()
        return guard

    async def test_concurrent_burst_sends_one_offpeak_notice(self):
        guard = self.make_guard()
        guard._now = lambda: datetime(2026, 1, 5, 12, 0, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        events = [BurstEvent("aiocqhttp:GroupMessage:1") for _ in range(6)]
        await asyncio.gather(*(guard.peak_gate(event) for event in events))
        self.assertEqual(sum(len(event.sent) for event in events), 1)

    async def test_concurrent_private_burst_respects_once_mode(self):
        guard = self.make_guard()
        guard._now = lambda: datetime(2026, 1, 5, 12, 0, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        umo = "aiocqhttp:FriendMessage:9"
        events = [BurstEvent(umo, private=True) for _ in range(6)]
        await asyncio.gather(*(guard.peak_gate(event) for event in events))
        self.assertEqual(sum(len(event.sent) for event in events), 1)

    async def test_concurrent_peak_burst_only_first_says_entered(self):
        guard = self.make_guard()
        guard._now = lambda: datetime(2026, 1, 5, 10, 0, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        events = [BurstEvent("aiocqhttp:GroupMessage:1") for _ in range(6)]
        await asyncio.gather(*(guard.peak_gate(event) for event in events))
        self.assertEqual(sum(len(event.sent) for event in events), 6)
        texts = [event_text(event) for event in events if event.sent]
        self.assertEqual(sum(1 for text in texts if "已进入高峰" in text), 1)
        self.assertEqual(sum(1 for text in texts if "当前处于高峰" in text), 5)

    async def test_notice_skipped_long_after_transition(self):
        guard = self.make_guard()
        guard._now = lambda: datetime(2026, 1, 5, 13, 30, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        event = BurstEvent("aiocqhttp:GroupMessage:1")
        await guard.peak_gate(event)
        self.assertEqual(event.sent, [])

    async def test_reminder_does_not_repeat_when_kv_write_fails(self):
        self.kv.fail_writes = True
        guard = self.make_guard()
        guard._known_groups = {"aiocqhttp:GroupMessage:1"}
        guard._now = lambda: datetime(2026, 1, 5, 18, 30, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
        for _ in range(6):
            try:
                await guard._check_reminders()
            except Exception:
                pass  # 真实环境里由 _reminder_loop 兜住，下一个 tick 继续
        self.assertEqual(len(self.sent_messages), 1)

    async def test_reminder_skips_chat_already_told_by_gate(self):
        guard = self.make_guard()
        guard._known_groups = {"aiocqhttp:GroupMessage:1"}
        guard._now = lambda: datetime(2026, 1, 5, 18, 30, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
        event = BurstEvent("aiocqhttp:GroupMessage:1")
        await guard.peak_gate(event)
        self.assertEqual(len(event.sent), 1)
        await guard._check_reminders()
        self.assertEqual(self.sent_messages, [])

    async def test_gate_skips_chat_already_told_by_reminder(self):
        guard = self.make_guard()
        guard._known_groups = {"aiocqhttp:GroupMessage:1"}
        guard._now = lambda: datetime(2026, 1, 5, 18, 30, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
        await guard._check_reminders()
        self.assertEqual(len(self.sent_messages), 1)
        event = BurstEvent("aiocqhttp:GroupMessage:1")
        await guard.peak_gate(event)
        self.assertEqual(event.sent, [])


if __name__ == "__main__":
    unittest.main()
