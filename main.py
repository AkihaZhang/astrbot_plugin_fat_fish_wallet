"""大肥鱼钱包保卫战：高峰时段自动暂停模型服务，空闲时段自动恢复。"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star

from .scheduler import (
    DEFAULT_PEAK_PERIODS,
    fmt_duration,
    fmt_periods_for_display,
    get_zoneinfo,
    is_peak,
    now_in,
    parse_periods,
    parse_weekdays,
)

ASSETS = Path(__file__).resolve().parent / "assets"
MY_COMMANDS = ("峰谷", "谷", "时段", "peak", "钱包", "白名单", "wl", "whitelist")

_PROVIDER_NAMES = {
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "anthropic": "Claude",
    "gemini": "Gemini",
    "ollama": "Ollama",
    "siliconflow": "硅基流动",
    "qwen": "通义千问",
    "doubao": "豆包",
    "moonshot": "Kimi",
    "zhipu": "智谱",
}


class FatFishWalletGuard(Star):
    """大肥鱼钱包保卫战

    高峰时段自动暂停模型服务，空闲时段自动恢复。
    指令：
    /峰谷              查询当前时段、供应商、下次切换、白名单、统计
    /峰谷 统计         今日拦截/豁免
    /峰谷 强制 开启|关闭|自动   管理员手动控制（开启=放行可用，关闭=暂停拦截）
    /白名单            管理可无视拦截的用户与群聊
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._wl_loaded = False
        self._wl_users: set[str] = set()
        self._wl_groups: set[str] = set()
        self._groups_loaded = False
        self._known_groups: set[str] = set()
        self._reminder_task: asyncio.Task | None = None

    def _cfg(self, key, default=None):
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _now(self) -> datetime:
        return now_in(get_zoneinfo(self._cfg("timezone", "Asia/Shanghai")))

    def _periods(self):
        return parse_periods(str(self._cfg("peak_periods", DEFAULT_PEAK_PERIODS)))

    def _weekdays(self):
        return parse_weekdays(str(self._cfg("peak_weekdays", "0,1,2,3,4,5,6") or ""))

    def get_wallet_policy(
        self,
        *,
        at: datetime | None = None,
        provider_id: str | None = None,
    ) -> dict:
        """Return the read-only wallet gate policy for another plugin or UI."""
        timezone_name = str(self._cfg("timezone", "Asia/Shanghai") or "Asia/Shanghai")
        zone = get_zoneinfo(timezone_name)
        if zone is None:
            timezone_name = "Asia/Shanghai"
            zone = get_zoneinfo(timezone_name)
        if at is None:
            local_at = now_in(zone)
        elif at.tzinfo is None:
            local_at = at.replace(tzinfo=zone) if zone else at.astimezone()
        else:
            local_at = at.astimezone(zone) if zone else at.astimezone()

        enabled = bool(self._cfg("enabled", True))
        override = str(self._cfg("manual_override", "auto") or "auto")
        try:
            provider = self.context.get_provider_by_id(provider_id) if provider_id else None
        except Exception:
            provider = None
        affected = self._provider_affected(provider_id, provider)
        holiday_name = ""
        try:
            import holidays

            holiday_name = str(holidays.CN().get(local_at.date()) or "")
        except Exception as exc:
            logger.warning(
                f"[大肥鱼钱包保卫战] holidays.CN() 不可用，按星期/时段计算：{exc}"
            )
        holiday = bool(holiday_name)

        if not enabled:
            state, allowed = "offpeak", True
        elif override == "always_allow":
            state, allowed = "forced allow", True
        elif override == "always_block":
            state, allowed = "forced block", False
        else:
            peak = False if holiday else is_peak(
                local_at, self._periods(), self._weekdays()
            )
            state = "peak" if peak else "offpeak"
            allowed = not affected or not peak

        return {
            "enabled": enabled,
            "allowed": allowed,
            "state": state,
            "timezone": timezone_name,
            "manual_override": override,
            "provider_affected": affected,
            "holiday": holiday,
            "holiday_name": holiday_name,
            "peak_periods": str(self._cfg("peak_periods", DEFAULT_PEAK_PERIODS)),
            "peak_weekdays": str(self._cfg("peak_weekdays", "0,1,2,3,4,5,6") or ""),
            "evaluated_at": local_at,
        }

    def _render(self, tmpl, provider="") -> str:
        s = str(tmpl)
        s = s.replace("{time}", self._now().strftime("%H:%M"))
        s = s.replace("{provider}", provider or "当前模型")
        return s

    # 供应商识别

    async def _get_current_provider(self, umo):
        try:
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
        except Exception:
            return None, None
        try:
            prov = self.context.get_provider_by_id(provider_id)
        except Exception:
            prov = None
        return provider_id, prov

    def _provider_affected(self, provider_id, prov) -> bool:
        affected = str(self._cfg("affected_providers", "deepseek") or "").strip()
        if not affected:
            return False
        if affected == "*":
            return True
        keywords = [k.strip().lower() for k in affected.split(",") if k.strip()]
        if not keywords:
            return False
        if not provider_id or prov is None:
            return bool(self._cfg("gate_when_provider_unknown", True))
        try:
            meta = prov.meta()
            haystack = " ".join(
                str(x or "")
                for x in (
                    getattr(meta, "id", ""),
                    getattr(meta, "model", ""),
                    getattr(meta, "type", ""),
                )
            ).lower()
        except Exception:
            return bool(self._cfg("gate_when_provider_unknown", True))
        return any(k in haystack for k in keywords)

    def _provider_display(self, prov) -> str:
        if prov is None:
            return "当前模型"
        try:
            meta = prov.meta()
        except Exception:
            return "当前模型"
        name = str(getattr(meta, "provider_display_name", "") or "").strip()
        if name:
            return name
        t = str(getattr(meta, "type", "") or "").lower()
        return _PROVIDER_NAMES.get(t, t.capitalize() or "当前模型")

    async def _provider_name(self, umo) -> str:
        _, prov = await self._get_current_provider(umo)
        return self._provider_display(prov)

    def _provider_status_text(self, provider_id, prov) -> str:
        if not provider_id:
            return "未识别 / 未配置"
        model = ptype = ""
        if prov is not None:
            try:
                meta = prov.meta()
                model = str(getattr(meta, "model", "") or "")
                ptype = str(getattr(meta, "type", "") or "")
            except Exception:
                pass
        return f"{model or provider_id}（{ptype or '未知'}）"

    # 白名单

    async def _load_whitelist(self):
        if self._wl_loaded:
            return
        try:
            data = await self.get_kv_data("whitelist", {}) or {}
            users = {str(x).strip() for x in (data.get("users") or []) if str(x).strip()}
            groups = {str(x).strip() for x in (data.get("groups") or []) if str(x).strip()}
            if not users and not groups:
                users = {
                    str(x).strip()
                    for x in (self._cfg("whitelist_users", []) or [])
                    if str(x).strip()
                }
                groups = {
                    str(x).strip()
                    for x in (self._cfg("whitelist_groups", []) or [])
                    if str(x).strip()
                }
            self._wl_users, self._wl_groups = users, groups
        except Exception as e:
            logger.error(f"[大肥鱼钱包保卫战] 白名单读取失败: {e}")
        self._wl_loaded = True

    async def _save_whitelist(self):
        try:
            await self.put_kv_data(
                "whitelist",
                {"users": sorted(self._wl_users), "groups": sorted(self._wl_groups)},
            )
        except Exception as e:
            logger.error(f"[大肥鱼钱包保卫战] 白名单保存失败: {e}")

    def _is_whitelisted(self, event: AstrMessageEvent) -> bool:
        if event.get_sender_id() in self._wl_users:
            return True
        gid = event.get_group_id()
        return bool(gid and gid in self._wl_groups)

    # 自动记录群聊（用于定时提醒目标）

    async def _load_known_groups(self):
        if self._groups_loaded:
            return
        try:
            data = await self.get_kv_data("known_groups", []) or []
            self._known_groups = {str(x) for x in data if str(x)}
        except Exception:
            self._known_groups = set()
        self._groups_loaded = True

    async def _save_known_groups(self):
        try:
            await self.put_kv_data("known_groups", sorted(self._known_groups))
        except Exception:
            pass

    def _record_group(self, event: AstrMessageEvent):
        if event.get_group_id() and event.unified_msg_origin:
            umo = event.unified_msg_origin
            if umo not in self._known_groups:
                self._known_groups.add(umo)
                asyncio.create_task(self._save_known_groups())

    def _resolve_reminder_targets(self) -> list[str]:
        targets = [
            str(x).strip()
            for x in (self._cfg("reminder_targets", []) or [])
            if str(x).strip()
        ]
        if not targets:
            return sorted(self._known_groups)
        out: list[str] = []
        for t in targets:
            if ":" in t:
                out.append(t)
            else:
                out.extend(u for u in sorted(self._known_groups) if t in u)
        return list(dict.fromkeys(out))

    # 状态与统计（只记录自然时段切换，不受手动开关影响）

    async def _period_state(self):
        try:
            data = await self.get_kv_data("period_state", {}) or {}
            if data.get("date") != self._now().strftime("%Y-%m-%d"):
                return None
            return data.get("state")
        except Exception:
            return None

    async def _save_period_state(self, state):
        try:
            await self.put_kv_data(
                "period_state",
                {"date": self._now().strftime("%Y-%m-%d"), "state": state},
            )
        except Exception:
            pass

    async def _bump_stats(self, key):
        try:
            today = self._now().strftime("%Y-%m-%d")
            stats = await self.get_kv_data("stats", {}) or {}
            if stats.get("date") != today:
                stats = {"date": today, "blocked": 0, "bypassed": 0}
            stats[key] = int(stats.get(key, 0)) + 1
            await self.put_kv_data("stats", stats)
        except Exception:
            pass

    async def _today_stats(self):
        try:
            stats = await self.get_kv_data("stats", {}) or {}
            if stats.get("date") != self._now().strftime("%Y-%m-%d"):
                return {"date": self._now().strftime("%Y-%m-%d"), "blocked": 0, "bypassed": 0}
            return stats
        except Exception:
            return {"date": "", "blocked": 0, "bypassed": 0}

    # 消息构造

    def _notice(self, text, image_name, provider=""):
        chain = [Plain(self._render(text, provider))]
        if self._cfg("attach_images", True):
            img = ASSETS / str(image_name)
            if img.is_file():
                chain.append(Image.fromFileSystem(str(img)))
        return MessageChain(chain=chain)

    def _is_my_command(self, event) -> bool:
        msg = event.get_message_str().strip()
        if msg.startswith("/"):
            msg = msg[1:].strip()
        elif not event.is_at_or_wake_command:
            return False
        return any(msg == n or msg.startswith(n + " ") for n in MY_COMMANDS)

    # 高峰闸门

    def _gate_decision(self, event, policy):
        if not policy["enabled"]:
            return False, ""
        override = policy["manual_override"]
        if override == "always_allow":
            return False, ""
        if self._cfg("admins_bypass", True) and event.is_admin():
            return False, "admin"
        if self._is_whitelisted(event):
            return False, "whitelist"
        if override == "always_block":
            return True, "manual"
        if policy["state"] != "peak":
            return False, ""
        if not policy["provider_affected"]:
            return False, "provider"
        return True, "peak"

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE,
        priority=100,
    )
    async def peak_gate(self, event: AstrMessageEvent):
        try:
            if self._is_my_command(event):
                return
            await self._load_known_groups()
            self._record_group(event)
            # 非唤醒消息（群聊闲聊、状态类事件等）不拦截不提示，避免刷屏
            if not event.is_at_or_wake_command:
                return
            await self._load_whitelist()
            now = self._now()
            provider_id, _ = await self._get_current_provider(event.unified_msg_origin)
            policy = self.get_wallet_policy(at=now, provider_id=provider_id)
            peak = policy["state"] == "peak"
            gated, reason = self._gate_decision(event, policy)
            override = policy["manual_override"]
            can_notice = await self._can_notice(event)

            if gated:
                event.should_call_llm(False)
                event.stop_event()
                await self._bump_stats("blocked")
                if not can_notice:
                    return
                provider = await self._provider_name(event.unified_msg_origin)
                if reason == "manual":
                    msg = self._cfg(
                        "manual_block_msg", "服务已被管理员手动关闭（拦截），等待恢复。"
                    )
                else:
                    enter = await self._period_state() != "peak"
                    if enter:
                        msg = self._cfg(
                            "peak_msg_enter",
                            "已进入高峰时段，{provider} 高峰时段费用太贵，该时段将停止服务至空闲时段，到时自动恢复。",
                        )
                    else:
                        msg = self._cfg(
                            "peak_msg_steady",
                            "当前处于高峰时段，{provider} 费用太贵，服务已暂停，空闲时段自动恢复。",
                        )
                    await self._save_period_state("peak")
                await event.send(
                    self._notice(msg, self._cfg("peak_image", "高峰时段.png"), provider)
                )
                await self._mark_notified(event)
                return

            if peak and reason in ("admin", "whitelist", "provider"):
                await self._bump_stats("bypassed")

            # 仅自动模式下处理自然时段切换提示
            if not peak and override == "auto":
                if (
                    self._cfg("announce_transition", True)
                    and await self._period_state() == "peak"
                    and can_notice
                ):
                    provider = await self._provider_name(event.unified_msg_origin)
                    await event.send(
                        self._notice(
                            self._cfg(
                                "offpeak_msg",
                                "已到达空闲时段，服务恢复，可以正常使用了。",
                            ),
                            self._cfg("offpeak_image", "空闲时段.png"),
                            provider,
                        )
                    )
                    await self._mark_notified(event)
                await self._save_period_state("offpeak")
        except Exception as e:
            logger.error(f"[大肥鱼钱包保卫战] peak_gate 异常: {e}")

    async def _can_notice(self, event) -> bool:
        if not event.is_private_chat():
            return True
        mode = str(self._cfg("private_notify_mode", "once") or "once")
        if mode == "never":
            return False
        if mode == "always":
            return True
        notified = await self._private_notified_today(event.unified_msg_origin)
        return event.unified_msg_origin not in notified

    async def _mark_notified(self, event):
        if not event.is_private_chat():
            return
        if str(self._cfg("private_notify_mode", "once") or "once") != "once":
            return
        await self._mark_private_notified(event.unified_msg_origin)

    async def _private_notified_today(self, umo) -> set:
        try:
            data = await self.get_kv_data("private_notified", {}) or {}
            if data.get("date") != self._now().strftime("%Y-%m-%d"):
                return set()
            return set(data.get("sessions") or [])
        except Exception:
            return set()

    async def _mark_private_notified(self, umo):
        try:
            today = self._now().strftime("%Y-%m-%d")
            data = await self.get_kv_data("private_notified", {}) or {}
            sessions = set(data.get("sessions") or []) if data.get("date") == today else set()
            sessions.add(umo)
            await self.put_kv_data(
                "private_notified", {"date": today, "sessions": sorted(sessions)}
            )
        except Exception:
            pass

    # 指令：/峰谷

    @filter.command("峰谷", alias={"谷", "时段", "peak", "钱包"})
    async def peak_status(self, event: AstrMessageEvent, action: str = "", value: str = ""):
        await self._load_whitelist()
        action = (action or "").strip()
        value = (value or "").strip()

        if action == "统计":
            stats = await self._today_stats()
            yield event.plain_result(
                "今日峰谷统计\n"
                f"日期：{stats.get('date', '')}\n"
                f"拦截 {stats.get('blocked', 0)} 条\n"
                f"豁免 {stats.get('bypassed', 0)} 条"
            )
            return

        if action == "强制":
            if not event.is_admin():
                yield event.plain_result("无权限，仅管理员可操作。")
                return
            if value in ("开启", "放行", "allow", "always_allow"):
                self.config["manual_override"] = "always_allow"
                reply = "已强制开启服务（放行），不受时段限制，可正常使用。"
            elif value in ("关闭", "拦截", "block", "always_block"):
                self.config["manual_override"] = "always_block"
                reply = "已强制关闭服务（拦截），暂停模型使用（白名单/管理员仍可用）。"
            elif value in ("自动", "auto"):
                self.config["manual_override"] = "auto"
                reply = "已恢复自动模式，按时段自动拦截/放行。"
            else:
                yield event.plain_result("用法：/峰谷 强制 开启|关闭|自动")
                return
            try:
                self.config.save_config()
            except Exception:
                logger.error("[大肥鱼钱包保卫战] 配置保存失败")
            yield event.plain_result(reply)
            return

        if action:
            yield event.plain_result("用法：/峰谷 [统计] [强制 开启|关闭|自动]")
            return

        now = self._now()
        provider_id, prov = await self._get_current_provider(event.unified_msg_origin)
        policy = self.get_wallet_policy(at=now, provider_id=provider_id)
        peak = policy["state"] == "peak"
        target, when = self._next_policy_transition(now, provider_id)
        affected = policy["provider_affected"]
        override = policy["manual_override"]

        if override == "always_allow":
            state = "手动放行中"
        elif override == "always_block":
            state = "手动拦截中"
        elif not policy["enabled"] or policy["allowed"]:
            state = "服务正常（当前供应商不在拦截范围）" if peak and not affected else "服务正常（空闲时段）"
        elif not affected:
            state = "服务正常（当前供应商不在拦截范围）"
        elif self._cfg("admins_bypass", True) and event.is_admin():
            state = "服务正常（管理员豁免）"
        elif self._is_whitelisted(event):
            state = "服务正常（白名单豁免）"
        else:
            state = "高峰拦截中"

        stats = await self._today_stats()
        periods_txt = fmt_periods_for_display(
            str(self._cfg("peak_periods", DEFAULT_PEAK_PERIODS))
        )
        period_label = {
            "peak": "高峰",
            "offpeak": "空闲",
        }.get(policy["state"], "手动策略覆盖")
        if target is None or when is None:
            transition_txt = "当前策略下无预定切换"
        else:
            remain_txt = fmt_duration((when - now).total_seconds())
            next_txt = "高峰" if target == "peak" else "空闲"
            transition_txt = f"约 {remain_txt} → {next_txt}"
        lines = [
            "【大肥鱼钱包保卫战】",
            f"当前时段：{period_label}",
            f"时段配置：{periods_txt}",
            f"中国法定节假日：{policy['holiday_name'] or ('是' if policy['holiday'] else '否')}",
            f"钱包策略：{policy['state']}（{'允许' if policy['allowed'] else '拦截'}）",
            f"下次切换：{transition_txt}",
            f"模型供应商：{self._provider_status_text(provider_id, prov)}",
            f"服务状态：{state}",
            f"白名单：用户 {len(self._wl_users)} / 群 {len(self._wl_groups)}",
            f"今日统计：拦截 {stats.get('blocked', 0)} / 豁免 {stats.get('bypassed', 0)}",
        ]
        if override != "auto":
            lines.append(f"手动开关：{override}")

        text = "\n".join(lines)
        chain = [Plain(text)]
        if self._cfg("attach_images", True):
            image = str(
                self._cfg("peak_image", "高峰时段.png")
                if peak
                else self._cfg("offpeak_image", "空闲时段.png")
            )
            img = ASSETS / image
            if img.is_file():
                chain.append(Image.fromFileSystem(str(img)))
        yield event.chain_result(chain)

    def _datetime_at(self, now: datetime, seconds: int) -> datetime:
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight + timedelta(seconds=int(seconds))

    def _next_policy_transition(self, now: datetime, provider_id: str | None):
        """Find the next natural state change by consulting shared policy."""
        current = self.get_wallet_policy(at=now, provider_id=provider_id)
        if not current["enabled"] or current["manual_override"] != "auto":
            return None, None
        state = current["state"]
        periods = self._periods()
        for day_offset in range(15):
            day = now + timedelta(days=day_offset)
            midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
            candidates = [midnight]
            for period in periods:
                candidates.append(self._datetime_at(midnight, period.start))
                candidates.append(self._datetime_at(midnight, period.end))
            for candidate in sorted(set(candidates)):
                if candidate <= now:
                    continue
                policy = self.get_wallet_policy(at=candidate, provider_id=provider_id)
                candidate_state = policy["state"]
                if candidate_state != state:
                    return candidate_state, candidate
                state = candidate_state
        return None, None

    # 指令：/白名单

    @filter.command("白名单", alias={"wl", "whitelist"})
    async def whitelist_mgmt(
        self,
        event: AstrMessageEvent,
        action: str = "",
        kind: str = "",
        target: str = "",
    ):
        await self._load_whitelist()
        action = (action or "").strip()
        kind = (kind or "").strip()
        target = (target or "").strip()

        if not action:
            yield event.plain_result(
                "白名单\n"
                f"用户（{len(self._wl_users)}）：{'、'.join(sorted(self._wl_users)) or '（空）'}\n"
                f"群聊（{len(self._wl_groups)}）：{'、'.join(sorted(self._wl_groups)) or '（空）'}\n"
                "----\n"
                "/白名单 添加|移除 用户|群 <ID>；/白名单 清空"
            )
            return

        if action in ("清空", "clear"):
            if not event.is_admin():
                yield event.plain_result("无权限，仅管理员可操作。")
                return
            self._wl_users.clear()
            self._wl_groups.clear()
            await self._save_whitelist()
            yield event.plain_result("白名单已清空。")
            return

        if action in ("添加", "add", "移除", "remove", "删除", "del"):
            if not event.is_admin():
                yield event.plain_result("无权限，仅管理员可操作。")
                return
            if not kind or not target:
                yield event.plain_result("用法：/白名单 添加 用户 123456 或 /白名单 添加 群 123456789")
                return
            is_user = kind in ("用户", "user", "u")
            is_group = kind in ("群", "群聊", "group", "g")
            if not (is_user or is_group):
                yield event.plain_result("类型须为「用户」或「群」。")
                return
            store = self._wl_users if is_user else self._wl_groups
            if action in ("添加", "add"):
                store.add(target)
                verb = "已添加"
            else:
                store.discard(target)
                verb = "已移除"
            await self._save_whitelist()
            yield event.plain_result(f"{verb}{'用户' if is_user else '群聊'} {target}。")
            return

        yield event.plain_result("用法：/白名单 [添加|移除 用户|群 <ID>] [/白名单 清空]")

    # 时段定时提醒

    async def _send_reminder(self, kind):
        if kind == "peak":
            tmpl = self._cfg(
                "reminder_peak_msg",
                "提醒：高峰时段即将到来（约 {time}），过几分钟将暂停模型服务。",
            )
            image = str(self._cfg("peak_image", "高峰时段.png"))
        else:
            tmpl = self._cfg(
                "reminder_offpeak_msg",
                "提醒：已到达空闲时段，模型服务恢复，可以正常使用了。",
            )
            image = str(self._cfg("offpeak_image", "空闲时段.png"))
        chain = self._notice(tmpl, image)
        await self._load_known_groups()
        for umo in self._resolve_reminder_targets():
            try:
                await self.context.send_message(umo, chain)
            except Exception as e:
                logger.error(f"[大肥鱼钱包保卫战] 发送提醒到 {umo} 失败: {e}")

    async def _check_reminders(self, now: datetime | None = None):
        if not self._cfg("reminder_enabled", True):
            return
        now = now or self._now()
        current_policy = self.get_wallet_policy(at=now, provider_id=None)
        if (
            not current_policy["enabled"]
            or current_policy["manual_override"] != "auto"
            or current_policy["holiday"]
        ):
            return
        today = now.strftime("%Y-%m-%d")
        periods = self._periods()
        if not periods:
            return
        lead = max(0, int(self._cfg("reminder_lead_minutes", 5)))
        fired = await self.get_kv_data("reminder_fired", {}) or {}
        if fired.get("date") != today:
            fired = {"date": today, "events": []}
        done = set(fired.get("events", []))
        events = []
        for i, p in enumerate(periods):
            peak_start = self._datetime_at(now, p.start)
            peak_start_policy = self.get_wallet_policy(at=peak_start, provider_id=None)
            if peak_start_policy["state"] != "peak":
                continue
            start_at = peak_start - timedelta(minutes=lead)
            peak_end = self._datetime_at(now, p.end)
            before_end_policy = self.get_wallet_policy(
                at=peak_end - timedelta(seconds=1), provider_id=None
            )
            after_end_policy = self.get_wallet_policy(at=peak_end, provider_id=None)
            end_at = peak_end
            events.append((f"peakstart_{i}", start_at, "peak"))
            if (
                before_end_policy["state"] == "peak"
                and after_end_policy["state"] == "offpeak"
            ):
                events.append((f"peakend_{i}", end_at, "offpeak"))
        changed = False
        for key, moment, kind in events:
            if key in done:
                continue
            if moment <= now < moment + timedelta(minutes=3):
                await self._send_reminder(kind)
                done.add(key)
                changed = True
        if changed:
            await self.put_kv_data("reminder_fired", {"date": today, "events": sorted(done)})

    async def _reminder_loop(self):
        while True:
            try:
                await self._check_reminders()
            except Exception as e:
                logger.error(f"[大肥鱼钱包保卫战] 提醒循环异常: {e}")
            await asyncio.sleep(30)

    # 生命周期

    async def initialize(self):
        await self._load_whitelist()
        await self._load_known_groups()
        now = self._now()
        policy = self.get_wallet_policy(at=now, provider_id=None)
        logger.info(
            f"[大肥鱼钱包保卫战] 已加载，当前策略 {policy['state']}，"
            f"{'允许' if policy['allowed'] else '拦截'}，"
            f"法定节假日：{policy['holiday_name'] or ('是' if policy['holiday'] else '否')}，"
            f"白名单用户 {len(self._wl_users)} / 群 {len(self._wl_groups)}"
        )
        if self._cfg("reminder_enabled", True):
            self._reminder_task = asyncio.create_task(self._reminder_loop())

    async def terminate(self):
        if self._reminder_task:
            self._reminder_task.cancel()
            self._reminder_task = None
        await self._save_whitelist()
        await self._save_known_groups()
