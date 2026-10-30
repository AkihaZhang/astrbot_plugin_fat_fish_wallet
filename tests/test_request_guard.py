"""Regression: random replies must be blocked before a paid model request.

The message handler used to skip non-wake messages. Built-in random replies
can request a model before that handler runs, so exercise the request hooks.
These tests can use the isolated API boundary installed by run_local.py;
the existing test_policy.py provides the real guard and in-memory KV fixtures.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import test_policy as fixtures


class RequestGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixtures = fixtures.NoticeSpamTests()
        self.fixtures.setUp()
        self.guard = self.fixtures.make_guard(skip_cn_holidays=False, admins_bypass=False)
        self.now = datetime(2026, 10, 30, 14, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.guard._now = lambda: self.now

    def event(self, *, wake=False, admin=False):
        event = fixtures.BurstEvent("aiocqhttp:GroupMessage:1")
        event.is_at_or_wake_command = wake
        event.is_admin = lambda: admin
        return event

    async def run_request_hook(self, event, kind):
        # Invoke the same hook entry points AstrBot dispatches before waiting
        # and before calling the provider. Missing hooks reproduce the old leak.
        name = {"waiting": "guard_before_waiting", "request": "guard_before_model"}[kind]
        hook = getattr(self.guard, name, None)
        if hook is None:
            return
        if kind == "request":
            await hook(event, object())
        else:
            await hook(event)

    async def paid_request_count(self, event):
        # Same two cancellation boundaries as AstrBot 4.29.3 InternalAgentSubStage.
        await self.run_request_hook(event, "waiting")
        if event.stopped:
            return 0
        await self.run_request_hook(event, "request")
        return 0 if event.stopped else 1

    async def test_peak_random_reply_never_reaches_paid_model_and_stays_silent(self):
        event = self.event()
        calls = await self.paid_request_count(event)
        self.assertEqual(calls, 0)
        self.assertEqual(event.sent, [])
        self.assertIs(event.llm_allowed, False)
        self.assertEqual((await self.guard._today_stats())["blocked"], 1)

    async def test_request_queued_before_peak_is_rechecked_before_model_call(self):
        self.now = self.now.replace(hour=13, minute=59)
        event = self.event()
        await self.run_request_hook(event, "waiting")
        self.assertFalse(event.stopped)
        self.now = self.now.replace(hour=14, minute=0)
        await self.run_request_hook(event, "request")
        self.assertTrue(event.stopped)
        self.assertEqual(event.sent, [])

    async def test_blocked_first_random_reply_still_records_group_for_reminders(self):
        event = self.event()
        self.assertEqual(await self.paid_request_count(event), 0)
        self.assertIn(event.unified_msg_origin, self.guard._known_groups)

    async def test_early_wake_request_is_blocked_with_normal_notice(self):
        event = self.event(wake=True)
        self.assertEqual(await self.paid_request_count(event), 0)
        self.assertEqual(len(event.sent), 1)
        self.assertIn("高峰", fixtures.event_text(event))

    async def test_offpeak_random_reply_is_allowed_without_notice(self):
        self.now = self.now.replace(hour=18, minute=30)
        event = self.event()
        self.assertEqual(await self.paid_request_count(event), 1)
        self.assertEqual(event.sent, [])

    async def test_disabled_guard_allows_random_reply(self):
        self.guard.config["enabled"] = False
        self.assertEqual(await self.paid_request_count(self.event()), 1)

    async def test_manual_allow_allows_random_reply(self):
        self.guard.config["manual_override"] = "always_allow"
        self.assertEqual(await self.paid_request_count(self.event()), 1)

    async def test_manual_block_blocks_random_reply_outside_peak(self):
        self.guard.config["manual_override"] = "always_block"
        self.now = self.now.replace(hour=20)
        event = self.event()
        self.assertEqual(await self.paid_request_count(event), 0)
        self.assertEqual(event.sent, [])

    async def test_user_whitelist_is_preserved(self):
        self.guard._wl_users.add("u1")
        self.assertEqual(await self.paid_request_count(self.event()), 1)

    async def test_group_whitelist_is_preserved(self):
        self.guard._wl_groups.add("1")
        self.assertEqual(await self.paid_request_count(self.event()), 1)

    async def test_admin_exemption_is_preserved(self):
        self.guard.config["admins_bypass"] = True
        self.assertEqual(await self.paid_request_count(self.event(admin=True)), 1)

    async def test_admin_is_blocked_when_exemption_disabled(self):
        self.assertEqual(await self.paid_request_count(self.event(admin=True)), 0)

    async def test_unaffected_provider_is_allowed(self):
        self.guard.config["affected_providers"] = "openai"
        self.assertEqual(await self.paid_request_count(self.event()), 1)

    async def test_ordinary_message_recording_is_not_stopped_by_message_gate(self):
        event = self.event()
        await self.guard.peak_gate(event)
        self.assertFalse(event.stopped)
        self.assertEqual(event.sent, [])


if __name__ == "__main__":
    unittest.main()
