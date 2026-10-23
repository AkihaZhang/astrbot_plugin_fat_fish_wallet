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
REMINDER_WINDOW = timedelta(minutes=3)


class _NoticeLedger:
    """进程内的一次性认领表，用来保证「同一个切换点、同一个会话只喊一次」。

    AstrBot 的事件总线是每条消息一个 asyncio 任务，同一瞬间可能有好几条消息
    同时跑进闸门。只要判定和落盘之间隔着 await，它们就都会读到「还没喊过」，
    于是连着发好几条一样的提示。

    claim() 全程没有 await，在 asyncio 单线程下「查 + 占位」是原子的，所以并发
    进来的任务里只有一个能拿到 True。放在模块级是因为插件重载后新旧实例可能
    同时活着（旧实例的提醒循环还没被取消），共享一份账本才不会各喊各的。
    """

    def __init__(self) -> None:
        self._day = ""
        self._keys: set[str] = set()

    def claim(self, day: str, key: str) -> bool:
        if day != self._day:
            self._day = day
            self._keys.clear()
        if key in self._keys:
            return False
        self._keys.add(key)
        return True


NOTICE_LEDGER = _NoticeLedger()


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

    def _segment_at(self, at: datetime) -> tuple[datetime, str]:
        """当前处在哪个「状态段」的开头，以及这段是高峰还是空闲。

        端点全部取时钟时刻，所以同一段时间里反复算出来的起点完全一致，用它做
        认领键才不会因为并发算出两个不同的值。
        """
        midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
        periods = self._periods()
        if not periods or self.get_wallet_policy(at=at, provider_id=None)["holiday"]:
            # 节假日整天按空闲算，一整天就是一个段
            return midnight, "offpeak"

        weekdays = self._weekdays()

        def state_of(moment: datetime) -> str:
            return "peak" if is_peak(moment, periods, weekdays) else "offpeak"

        marks = {midnight}
        for period in periods:
            marks.add(self._datetime_at(midnight, period.start))
            marks.add(self._datetime_at(midnight, period.end))
        state = state_of(at)
        start = midnight
        # 从最近的一个端点往回走，只要状态一样就继续往前，直到撞上状态不同的一刻
        for mark in sorted((m for m in marks if m <= at), reverse=True):
            if state_of(mark) != state:
                break
            start = mark
        return start, state

    def _boundary_key(self, at: datetime) -> tuple[str, str, datetime]:
        """返回 (日期, 认领键, 段起点)。认领键与状态段一一对应。"""
        start, state = self._segment_at(at)
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds = int((start - midnight).total_seconds())
        day = start.strftime("%Y-%m-%d")
        return day, f"{day}:{seconds}:{state}", start

    def _claim_notice(self, at: datetime, umo: str, suffix: str = "") -> bool:
        """认领「这个切换点要往这个会话喊一声」。并发进来的只有一个能拿到 True。"""
        day, key, _ = self._boundary_key(at)
        return NOTICE_LEDGER.claim(day, f"{key}|{umo}{suffix}")

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

    # 统计

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
            umo = event.unified_msg_origin
            provider_id, _ = await self._get_current_provider(umo)
            policy = self.get_wallet_policy(at=now, provider_id=provider_id)
            peak = policy["state"] == "peak"
            gated, reason = self._gate_decision(event, policy)
            override = policy["manual_override"]

            if gated:
                event.should_call_llm(False)
                event.stop_event()
                await self._bump_stats("blocked")
                if not await self._can_notice(event):
                    return
                provider = await self._provider_name(umo)
                if reason == "manual":
                    msg = self._cfg(
                        "manual_block_msg", "服务已被管理员手动关闭（拦截），等待恢复。"
                    )
                else:
                    # 同一段高峰里每个会话只讲一次「已进入」，其余用「当前处于」，
                    # 并发进来的消息里只有一个能认领到，不会连发
                    if self._claim_notice(now, umo, "|peak-enter"):
                        msg = self._cfg(
                            "peak_msg_enter",
                            "已进入高峰时段，{provider} 高峰时段费用太贵，该时段将停止服务至空闲时段，到时自动恢复。",
                        )
                    else:
                        msg = self._cfg(
                            "peak_msg_steady",
                            "当前处于高峰时段，{provider} 费用太贵，服务已暂停，空闲时段自动恢复。",
                        )
                await event.send(
                    self._notice(msg, self._cfg("peak_image", "高峰时段.png"), provider)
                )
                await self._mark_notified(event)
                return

            if peak and reason in ("admin", "whitelist", "provider"):
                await self._bump_stats("bypassed")

            # 仅自动模式下处理自然时段切换提示
            if not peak and override == "auto":
                await self._announce_offpeak(event, now, umo)
        except Exception as e:
            logger.error(f"[大肥鱼钱包保卫战] peak_gate 异常: {e}")

    async def _announce_offpeak(self, event, now, umo):
        """空闲时段到了，往这个会话说一声。同一个切换点每个会话只说一次。

        只在切换后的一小段时间内说，过期就不提了——不然下午五点有人在群里
        随口一句，机器人突然回「已到达空闲时段」，看着很怪。
        """
        if not self._cfg("announce_transition", True):
            return
        window = max(0, int(self._cfg("transition_notice_window_minutes", 10)))
        _, _, segment_start = self._boundary_key(now)
        if window and (now - segment_start) > timedelta(minutes=window):
            return
        # 先认领再发：提醒循环用的是同一把钥匙，所以同一个群里不会既收提醒又收这条
        if not self._claim_notice(now, umo):
            return
        if not await self._can_notice(event):
            return
        provider = await self._provider_name(umo)
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

    async def _can_notice(self, event) -> bool:
        if not event.is_private_chat():
            return True
        mode = str(self._cfg("private_notify_mode", "once") or "once")
        if mode == "never":
            return False
        if mode == "always":
            return True
        umo = event.unified_msg_origin
        # 先在进程内原子占位，再读 KV：同一秒并发进来的私信只有一个能放行，
        # KV 那份只是给重启后留个记号
        today = self._now().strftime("%Y-%m-%d")
        if not NOTICE_LEDGER.claim(today, f"{today}|{umo}|private-notice"):
            return False
        notified = await self._private_notified_today(umo)
        return umo not in notified

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

    async def _send_reminder(self, kind, targets):
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
        for umo in targets:
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
        await self._load_known_groups()
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
            peak_end = self._datetime_at(now, p.end)
            before_end_policy = self.get_wallet_policy(
                at=peak_end - timedelta(seconds=1), provider_id=None
            )
            after_end_policy = self.get_wallet_policy(at=peak_end, provider_id=None)
            events.append(
                (f"peakstart_{i}", peak_start - timedelta(minutes=lead), "peak", peak_start)
            )
            if (
                before_end_policy["state"] == "peak"
                and after_end_policy["state"] == "offpeak"
            ):
                events.append((f"peakend_{i}", peak_end, "offpeak", peak_end))

        changed = False
        for key, moment, kind, boundary_at in events:
            if key in done:
                continue
            if not (moment <= now < moment + REMINDER_WINDOW):
                continue
            # 每个目标单独认领：已经通过闸门收到过这条提示的会话不再重复推一遍
            targets = []
            for umo in self._resolve_reminder_targets():
                if self._claim_notice(boundary_at, umo):
                    targets.append(umo)
            if targets:
                await self._send_reminder(kind, targets)
            done.add(key)
            changed = True
        if changed:
            await self.put_kv_data(
                "reminder_fired", {"date": today, "events": sorted(done)}
            )

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
