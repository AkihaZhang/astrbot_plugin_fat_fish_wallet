<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:38bdf8,100:1e293b&height=120&section=header" width="100%" alt="" />

<img src="./logo.png" alt="logo" height="110" />

# 大肥鱼钱包保卫战

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=16&pause=1400&center=true&vCenter=true&width=480&color=38BDF8&lines=%E9%AB%98%E5%B3%B0%E6%9A%82%E5%81%9C%20%C2%B7%20%E7%A9%BA%E9%97%B2%E6%81%A2%E5%A4%8D%20%C2%B7%20%E5%AE%88%E6%8A%A4%E9%92%B1%E5%8C%85" alt="高峰暂停 · 空闲恢复 · 守护钱包" />

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.9.2-blue?style=for-the-badge)](https://docs.astrbot.app)
[![Platforms](https://img.shields.io/badge/platforms-aiocqhttp%20%7C%20telegram%20%7C%20lark%20%7C%20discord-4b5563?style=for-the-badge)](#)
[![License](https://img.shields.io/github/license/foxchuqiao/astrbot_plugin_fat_fish_wallet?style=for-the-badge&color=green)](#)
[![Stars](https://img.shields.io/github/stars/foxchuqiao/astrbot_plugin_fat_fish_wallet?style=for-the-badge&color=yellow)](https://github.com/foxchuqiao/astrbot_plugin_fat_fish_wallet)
[![Last commit](https://img.shields.io/github/last-commit/foxchuqiao/astrbot_plugin_fat_fish_wallet?style=for-the-badge&color=orange)](https://github.com/foxchuqiao/astrbot_plugin_fat_fish_wallet)

</div>

---

一个给 AstrBot 用的峰谷计费守卫插件。它在模型 API 的高峰时段暂停服务，等到空闲时段自动恢复，从而避开高峰时段的溢价。

## 功能

- 高峰时段自动停止模型调用，空闲时段自动恢复，无需人工干预
- 自动识别当前会话使用的模型供应商，按配置关键词匹配，不写死 DeepSeek
- 白名单用户与群聊可绕过拦截
- 高峰开始前、高峰结束时向指定群聊推送提醒
- `/峰谷` 实时查询时段、策略、供应商、下次切换与今日统计
- 时段、星期、时区、文案、图片、提醒目标均可配置，全平台通用

## DeepSeek 的峰谷规则

插件的默认值依照 DeepSeek 官方定价页的现行规则（[api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing)，2026-10 核对）：

| 项目 | 规则 |
| --- | --- |
| 高峰时段 | 北京时间 09:00-12:00、14:00-18:00（对应 UTC 01:00-04:00、06:00-10:00） |
| 高峰日 | 周一至周五，中国法定节假日除外 |
| 空闲时段 | 其余全部时间，含周末与法定节假日整天 |
| 价格关系 | 空闲价是高峰价的一半 |

对应到插件配置就是 `peak_periods = 09:00-12:00,14:00-18:00`、`peak_weekdays = 0,1,2,3,4`，并开启 `skip_cn_holidays`。三项都是默认值，新装即符合上述规则。

## 换用其他供应商

不依赖 DeepSeek。想用在别家，改三个配置即可：

1. `affected_providers` 填该供应商的匹配词，多个用逗号分隔，`*` 表示全部拦截，留空表示不拦截。匹配范围是 provider 的 id、模型名和适配器名，例如 `openai`、`claude`、`qwen`。
2. `peak_periods` 与 `peak_weekdays` 按对方的价格表填写。
3. 如果对方没有「中国法定节假日算空闲」这条规则，把 `skip_cn_holidays` 关掉。

## 拦截是怎么发生的

每次有消息要触发模型调用，插件在事件管道最前面介入（priority 100），依次判断：

1. 识别当前会话使用的供应商
2. 判断当前时间属于哪个时段、当天是否在生效星期内、是否为法定节假日
3. 检查豁免条件：手动放行、管理员、白名单，任一成立即放行
4. 无豁免时判断是否需要拦截，需要则调用 `should_call_llm(False)` 与 `stop_event()`，本次模型调用不会发生

拦截原因分为管理员豁免、白名单豁免、供应商不在拦截范围、手动开关、高峰时段五类，`/峰谷 统计` 按类别计数。

插件只处理真正会触发模型调用的消息，即带唤醒前缀或艾特机器人的消息。群内普通聊天不进入拦截流程，也不回复提示。1.1.1 之前的版本对每条消息都回复，造成刷屏，现行为已调整。

## 周末与节假日

按 DeepSeek 的规则，周末与法定节假日全天按空闲计费，因此插件在 `peak_weekdays` 里排除周六周日、并由 `skip_cn_holidays` 覆盖法定节假日，即可完全对齐。

有一个边界需要说明：调休形成的补班日（例如周六上班）不是法定节假日，DeepSeek 按「周末」将其归为空闲时段，插件的行为与此一致。如果你的供应商按工作日计费、补班日算高峰，需要自行调整 `peak_weekdays`。

## 安装

**推荐：插件市场安装。** 在 AstrBot 的插件市场里搜索「大肥鱼钱包保卫战」，直接点安装即可，依赖会自动拉取。

手动安装：

1. 把 `astrbot_plugin_fat_fish_wallet` 目录放入 AstrBot 的 `data/plugins/`；或在 WebUI 插件页选择「上传安装」，上传 `astrbot_plugin_fat_fish_wallet.zip`
2. 在插件页启用或重载插件
3. 首次安装会自动安装依赖：Windows 下额外安装 `tzdata`（Python 时区数据库），以及 `holidays`（法定节假日数据）

若 `holidays` 安装失败，插件不会崩溃：会打印一条警告并退回纯时段判断，仅失去节假日豁免能力。

运行要求：AstrBot 4.9.2 及以上。

## 指令

下表以 `/峰谷` 书写。`/` 是 AstrBot 默认的指令前缀（唤醒前缀）；如果你在 AstrBot 里改过它（例如改成 `#` 或 `！`），请按你设置的符号来，实际指令是「你设置的前缀 + 峰谷」。

| 指令 | 说明 | 权限 |
| --- | --- | --- |
| `/峰谷` | 当前时段、节假日、策略、下次切换、供应商、白名单、今日统计（附图片） | 所有人 |
| `/峰谷 统计` | 今日拦截与豁免数量 | 所有人 |
| `/峰谷 强制 开启` | 强制放行，不受时段限制（同义：放行） | 管理员 |
| `/峰谷 强制 关闭` | 强制拦截，暂停模型使用（同义：拦截） | 管理员 |
| `/峰谷 强制 自动` | 恢复按时段自动判断 | 管理员 |
| `/白名单` | 查看当前白名单 | 所有人 |
| `/白名单 添加 用户 <ID>` | 添加用户白名单 | 管理员 |
| `/白名单 添加 群 <ID>` | 添加群聊白名单 | 管理员 |
| `/白名单 移除 用户\|群 <ID>` | 移除白名单条目 | 管理员 |
| `/白名单 清空` | 清空白名单 | 管理员 |

`/峰谷` 另有别名 `/时段`、`/peak`、`/钱包`、`/谷`；`/白名单` 另有别名 `/wl`、`/whitelist`。

手动强制开启或关闭期间，不会触发自然时段切换提示，也不会发送定时提醒，以避免与实际状态冲突。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 总开关 |
| `timezone` | `Asia/Shanghai` | 时区，填 IANA 名称 |
| `peak_periods` | `09:00-12:00,14:00-18:00` | 高峰时段，含开始不含结束 |
| `peak_weekdays` | `0,1,2,3,4` | 高峰生效的星期，0 为周一，6 为周日，留空表示每天 |
| `affected_providers` | `deepseek` | 要拦截的供应商匹配词，`*` 表示全部，留空表示不拦截 |
| `skip_cn_holidays` | `true` | 中国法定节假日整天按空闲处理 |
| `gate_when_provider_unknown` | `true` | 无法识别供应商时是否仍拦截 |
| `admins_bypass` | `true` | 管理员是否豁免 |
| `attach_images` | `true` | 回复是否附带图片 |
| `peak_image` / `offpeak_image` | `高峰时段.png` / `空闲时段.png` | 图片文件名，替换 `assets/` 下同名文件即可换图 |
| `peak_msg_enter` / `peak_msg_steady` | 高峰刚进入 / 高峰持续 | 文案，支持 `{provider}`、`{time}` |
| `offpeak_msg` | 恢复提示 | 同上 |
| `manual_block_msg` | 手动拦截提示 | 同上 |
| `manual_override` | `auto` | `auto` 按时段 / `always_allow` 一律放行 / `always_block` 一律拦截 |
| `announce_transition` | `true` | 时段切换时是否发送提示 |
| `transition_notice_window_minutes` | `10` | 切换提示仅在切换后这么多分钟内发送，`0` 表示不限制 |
| `private_notify_mode` | `once` | 私信高峰提示频率：`once` 每天一次 / `always` 每次 / `never` 不提示 |
| `whitelist_users` / `whitelist_groups` | `[]` | 初始白名单，后续用 `/白名单` 管理 |
| `reminder_enabled` | `true` | 定时提醒总开关 |
| `reminder_targets` | `[]` | 提醒目标，留空表示自动记录的全部群聊 |
| `reminder_lead_minutes` | `5` | 高峰开始前提前多少分钟提醒 |
| `reminder_peak_msg` | 高峰将至 | 支持 `{time}` |
| `reminder_offpeak_msg` | 空闲到来 | 支持 `{time}` |

关于提醒目标：插件会自动记录与机器人交互过的群聊（存于插件 KV）。`reminder_targets` 留空时，提醒发送到所有已记录群聊；也可填群号（自动匹配已记录群），或填完整的 `unified_msg_origin`（形如 `aiocqhttp:GroupMessage:123`，可用 `/sid` 或日志获取）来限定范围。

## 给其他插件调用

这一节面向**同一台 AstrBot 上的其他插件**。如果你只装了本插件，可以跳过。

常见场景：你还装了自动回复、绘图、总结之类的插件，它们自己也会请求模型。这些请求不经过消息管道，本插件的拦截管不到。解决办法是让它们在发起请求前问一句当前能不能用：

```python
meta = self.context.get_registered_star("astrbot_plugin_fat_fish_wallet")
guard = meta.star_cls if meta else None
if guard is not None:
    policy = guard.get_wallet_policy(provider_id="deepseek-flash")
    if not policy["allowed"]:
        ...  # 当前处于高峰，不要发起请求
```

`star_cls` 即插件实例；插件未激活时为 `None`，取用前需判空。

`get_wallet_policy(at=None, provider_id=None)` 两个参数均可选。`at` 不传表示当前时刻，传入不带时区的 datetime 会按配置时区解释；`provider_id` 不传表示视为未知供应商，此时 `gate_when_provider_unknown` 生效。

返回字典包含：

| 字段 | 含义 |
| --- | --- |
| `enabled` | 总开关是否开启 |
| `allowed` | 当前是否应当放行 |
| `state` | `offpeak` / `peak` / `forced allow` / `forced block` |
| `timezone` | 实际使用的时区，配置非法时回落 `Asia/Shanghai` |
| `manual_override` | 手动开关当前档位 |
| `provider_affected` | 该供应商是否在拦截范围内 |
| `holiday` | 当天是否为法定节假日 |
| `holiday_name` | 节日名称，非节假日为空串 |
| `peak_periods` / `peak_weekdays` | 当前生效的时段与星期配置 |
| `evaluated_at` | 本次判定使用的时间点 |

该接口为只读，不包含管理员与白名单豁免，这两层在消息管道内单独判断。若需与插件行为完全一致，调用方需自行补齐。

## 目录结构

```
astrbot_plugin_fat_fish_wallet/
├── metadata.yaml        # 插件元数据
├── main.py              # 插件主逻辑
├── scheduler.py         # 峰谷时段计算，纯逻辑，可单独测试
├── _conf_schema.json    # 配置 Schema
├── requirements.txt     # 依赖
├── tests/
│   └── test_policy.py   # 策略、提醒与并发去重测试
├── LICENSE              # MIT
├── logo.png             # 插件 Logo
└── assets/
    ├── 高峰时段.png
    └── 空闲时段.png
```

## 常见问题

**为什么只有唤醒消息才会收到提示？**

只有这类消息才会真正触发模型调用。群内闲聊不会请求模型，插件无需介入，介入反而造成刷屏。

**其他插件自行调用 LLM，能拦截吗？**

不能完全拦截。插件作用于消息事件管道，AstrBot 默认的 LLM 请求链路一定被挡住。但其他插件通过 `context.llm_generate()` 等接口发起的内部请求，AstrBot 未开放该层级的阻断能力，需要对方主动调用 `get_wallet_policy()` 配合。

**手动开关与自动时段如何配合？**

- 强制开启（放行）：所有消息可用，不受时段限制，也不再提示
- 强制关闭（拦截）：模型暂停，仅白名单与管理员可用，其余消息回复手动拦截提示
- 两种强制状态下均不触发自然切换提示，也不发送定时提醒

**高峰期私信提示过多？**

私信默认每个会话每天提示一次。需要更多可改为 `private_notify_mode = always`，需要关闭可改为 `never`。

**我处于高峰时段却没有被拦截？**

依次检查：当天是否为法定节假日（`/峰谷` 可查）、当前供应商是否在 `affected_providers` 内、手动开关是否为 `always_allow`。三者任一成立都不会拦截。

**时段切换时会不会重复发送提示？**

不会。AstrBot 为每条消息单独创建任务，切换点附近的并发消息会同时进入闸门。插件采用进程内原子认领，同一个切换点、同一个会话只发送一次；定时提醒与切换提示共用同一份额度，同一群聊不会既收到提醒又收到回复。切换超过 `transition_notice_window_minutes` 后不再补发。

**如何更换提示图片？**

将新图片放入 `assets/`，覆盖 `peak_image` / `offpeak_image` 指向的文件名即可，无需修改代码。

## 开发与测试

测试位于 `tests/`，在已安装 AstrBot 的环境（或将 `astrbot` 加入 `PYTHONPATH`）中运行：

```bash
python -m unittest discover -s tests
```

覆盖节假日判定、手动开关优先级、`holidays` 缺失时的退化、假期不发提醒、状态文案与下次切换一致性、以及时段切换的并发去重。修改 `main.py` 中策略相关逻辑前，建议先跑一遍。

## 贡献者

1.1.2 的节假日策略与公共接口由 [QHongboQ](https://github.com/QHongboQ) 在 [PR #2](https://github.com/foxchuqiao/astrbot_plugin_fat_fish_wallet/pull/2) 中实现，包括只读的 `get_wallet_policy()` 接口、自动模式下的节假日豁免、`holidays` 依赖与确定性的策略测试。

## 许可证

本项目使用 [MIT 许可证](LICENSE)。

Copyright © 2026 foxchuqiao

允许自由使用、修改、分发与商业使用，需保留版权声明与许可声明；软件按「现状」提供，不附带任何担保。
