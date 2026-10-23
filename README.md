<div align="center">

<img src="./logo.png" alt="logo" height="120" />

# 大肥鱼钱包保卫战

**高峰暂停 · 空闲恢复 · 守护钱包**

[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.9.2-blue?style=for-the-badge)](https://docs.astrbot.app)
[![License](https://img.shields.io/github/license/foxchuqiao/astrbot_plugin_fat_fish_wallet?style=for-the-badge&color=green)](#)
[![Stars](https://img.shields.io/github/stars/foxchuqiao/astrbot_plugin_fat_fish_wallet?style=for-the-badge&color=yellow)](https://github.com/foxchuqiao/astrbot_plugin_fat_fish_wallet)
[![Last commit](https://img.shields.io/github/last-commit/foxchuqiao/astrbot_plugin_fat_fish_wallet?style=for-the-badge&color=orange)](https://github.com/foxchuqiao/astrbot_plugin_fat_fish_wallet)

</div>

---

给 AstrBot 用的小插件。模型 API 在高峰时段卖得贵，它就趁这个点把服务停下来，等回到空闲再放开。省下来的钱谈不上多，但月底看账单确实会舒服一点。

## 它能干什么

- 到了高峰自动停模型调用，回到空闲自动恢复，中间不用人管
- 认得出当前会话用的是哪个供应商，不写死 DeepSeek，换一家也照样生效
- 白名单里的人、群聊可以无视拦截，正常用
- 高峰开始前几分钟、高峰结束那一刻，主动往群里推个提醒
- `/峰谷` 随时查现在是什么状态、下次什么时候变、今天拦了多少
- 时段、星期、时区、文案、图片、提醒发到哪儿，全都能改

## 为什么要做这个

学生党想给 bot 接官方 DeepSeek API，个人开发者又买不到额度够用、价格合适的 Coding Plan。各家订阅这两年都在涨价，额度还在缩水。

既然高峰贵，那就在高峰别用。道理就这么简单。

## 拦截是怎么发生的

默认拦两段，09:00-12:00 和 14:00-18:30。这两个点没什么玄机，就是一天里模型最忙、单价最高的那一段，中午和傍晚留出来给自己干活用。时段随便改，改成夜里拦也行。

每次有消息要叫模型干活，插件在事件管道最前面插一脚（priority 100），然后一路判下来：

1. 认出当前会话用的是哪个供应商
2. 看现在落在哪个时段、今天星期几生效不生效、是不是节假日
3. 先过一遍豁免：手动放行、管理员、白名单，任意一条成立就直接放过
4. 都没豁免，再看是不是手动拦截或者高峰，该拦就 `should_call_llm(False)` 加上 `stop_event()`，这次模型调用根本不会发生

认供应商不靠写死的名字，是拿 provider 的 id、模型名、适配器名一起去匹配 `affected_providers` 里的关键词。所以换供应商不用改代码，改配置就行。填 `*` 表示全都拦，留空表示谁也不拦。

拦下来的原因分好几种，管理员豁免、白名单豁免、供应商不在拦截范围、手动开关、纯高峰。`/峰谷 统计` 会把今天这几种各多少条列出来。

有个地方容易误会。插件只处理真正会触发模型调用的消息，也就是叫醒机器人的那些（艾特，或者带唤醒前缀）。群里普通闲聊它不插嘴，不拦也不回话。1.1.1 之前是每条都回一句提示，结果群里刷屏，后来才改成只认唤醒消息。

## 节假日不拦

中国人上班的日子跟日历上的星期几对不上。国庆、春节、五一，再加上调休的补班日，光看星期几一定判错。

自动模式下插件会查一下当天是不是中国法定节假日（依赖 `holidays` 包）。是假期就当空闲处理，不拦，也不发高峰提醒。不然大过节的往群里推一条「已进入高峰，服务暂停」，实在不像话。

两个边界得先说清楚，免得你踩了还以为有 bug。

**补班日不会被当成工作日。** `holidays` 只给节假日，不给调休上班日。像 2026-10-10 这种周六补班的日期，插件仍然按周末处理成空闲。要精确到这一层得自己动代码。

**假期逻辑没有独立开关。** 自动模式下直接生效。想在大年初一也照样拦，要么切到手动拦截（`manual_override` 设成 `always_block`），要么干脆把插件关掉。

## 安装

1. 把 `astrbot_plugin_fat_fish_wallet` 整个文件夹丢进 AstrBot 的 `data/plugins/` 目录；或者在 WebUI 插件页点「上传安装」，传 `astrbot_plugin_fat_fish_wallet.zip`
2. 在 WebUI 插件页启用或重载一下
3. 第一次装的时候会自动拉依赖。Windows 上会多装一个 `tzdata`（Python 的时区数据库），另外还有 `holidays`（节假日数据）
4. 想改时段、文案、图片、提醒目标，都在插件配置里调，不用碰代码

装不上 `holidays` 也不会崩。插件会打一条警告，然后退回纯时段判断，只是假期不再豁免。

需要 AstrBot 4.9.2 或更新。

## 命令

| 指令 | 说明 | 权限 |
| --- | --- | --- |
| `/峰谷` | 当前时段、节假日、钱包策略、下次切换、供应商、白名单、今日统计（带图） | 所有人 |
| `/峰谷 统计` | 今天拦了多少、豁免了多少 | 所有人 |
| `/峰谷 强制 开启` | 强制放行，不管时段（同义：放行） | 管理员 |
| `/峰谷 强制 关闭` | 强制拦截，暂停模型使用（同义：拦截） | 管理员 |
| `/峰谷 强制 自动` | 交还给时段规则 | 管理员 |
| `/白名单` | 看看现在有哪些 | 所有人 |
| `/白名单 添加 用户 <ID>` | 加一个用户进白名单 | 管理员 |
| `/白名单 添加 群 <ID>` | 加一个群进白名单 | 管理员 |
| `/白名单 移除 用户\|群 <ID>` | 从白名单里去掉 | 管理员 |
| `/白名单 清空` | 清空 | 管理员 |

`/峰谷` 还有几个别名，`/时段`、`/peak`、`/钱包`、`/谷` 都行；`/白名单` 也认 `/wl` 和 `/whitelist`。

手动强制开启或关闭期间，自然的「已进入高峰」「已到空闲」这类提示不会触发，也不会发定时提醒。状态跟实际情况对不上的话说出来只会更乱。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 总开关 |
| `timezone` | `Asia/Shanghai` | 时区，填 IANA 名称 |
| `peak_periods` | `09:00-12:00,14:00-18:30` | 高峰时段，含开始不含结束 |
| `peak_weekdays` | `0,1,2,3,4,5,6` | 哪几天生效，0 是周一，6 是周日，留空等于每天 |
| `affected_providers` | `deepseek` | 要拦的供应商关键词，`*` 表示全部，留空表示不拦 |
| `gate_when_provider_unknown` | `true` | 认不出供应商时还拦不拦 |
| `admins_bypass` | `true` | 管理员是否豁免 |
| `attach_images` | `true` | 回复要不要带图 |
| `peak_image` / `offpeak_image` | `高峰时段.png` / `空闲时段.png` | 图片文件名，换 `assets/` 下的同名文件就等于换图 |
| `peak_msg_enter` / `peak_msg_steady` | 高峰刚进 / 高峰持续 | 文案，支持 `{provider}`、`{time}` |
| `offpeak_msg` | 恢复提示 | 同上 |
| `manual_block_msg` | 手动拦截提示 | 同上 |
| `manual_override` | `auto` | `auto` 按时段 / `always_allow` 一律放行 / `always_block` 一律拦截 |
| `announce_transition` | `true` | 时段切换时发不发提示 |
| `transition_notice_window_minutes` | `10` | 切换提示只在切换后这么多分钟内发，`0` 表示不限制 |
| `private_notify_mode` | `once` | 私信高峰提示频率，`once` 每天一次 / `always` 每次 / `never` 不提示 |
| `whitelist_users` / `whitelist_groups` | `[]` | 初始白名单，之后用 `/白名单` 管 |
| `reminder_enabled` | `true` | 定时提醒的总开关 |
| `reminder_targets` | `[]` | 提醒发给谁，留空等于自动记录下来的所有群 |
| `reminder_lead_minutes` | `5` | 高峰开始前提前多久提醒 |
| `reminder_peak_msg` | 高峰将至 | 支持 `{time}` |
| `reminder_offpeak_msg` | 空闲到来 | 支持 `{time}` |

关于提醒目标多说一句。插件会自动记下跟机器人互动过的群聊，存在插件 KV 里。`reminder_targets` 留空的时候，提醒会发给所有记录到的群；你也可以填群号（会自动对上记录里的群），或者填完整的 `unified_msg_origin`（长得像 `aiocqhttp:GroupMessage:123`，用 `/sid` 或者翻日志能拿到）来限定范围。

## 给别的插件用

如果你在写另一个插件，想提前知道现在能不能调模型，可以直接问它，不用自己再算一遍时段。

```python
meta = self.context.get_registered_star("astrbot_plugin_fat_fish_wallet")
guard = meta.star_cls if meta else None
if guard is not None:
    policy = guard.get_wallet_policy(provider_id="deepseek-chat")
    if not policy["allowed"]:
        ...  # 这会儿别调模型
```

`star_cls` 就是插件实例，不过插件没激活的时候它是 `None`，所以取完记得判一下。

`get_wallet_policy(at=None, provider_id=None)` 两个参数都可选。`at` 不传就是现在，传个不带时区的 datetime 会按配置里的时区解释；`provider_id` 不传就当你没有供应商，`gate_when_provider_unknown` 那条规则会生效。

返回来的是个字典：

| 字段 | 意思 |
| --- | --- |
| `enabled` | 总开关开着没 |
| `allowed` | 这会儿该不该放行 |
| `state` | `offpeak` / `peak` / `forced allow` / `forced block` |
| `timezone` | 实际用的时区，配置里那个不合法会回落到 `Asia/Shanghai` |
| `manual_override` | 手动开关的当前档位 |
| `provider_affected` | 这个供应商在拦截范围内吗 |
| `holiday` | 当天是不是法定节假日 |
| `holiday_name` | 节日名字，不是假期就是空串 |
| `peak_periods` / `peak_weekdays` | 当前生效的时段和星期，原样返回 |
| `evaluated_at` | 判定用的是哪个时间点 |

这个接口是只读的，但它没替你考虑管理员和白名单，那两层是消息闸门里单独判的。你要跟插件行为完全一致，这两条得自己补上。

## 目录结构

```
astrbot_plugin_fat_fish_wallet/
├── metadata.yaml        # 插件元数据
├── main.py              # 插件主逻辑
├── scheduler.py         # 峰谷时段计算，纯逻辑，可以单独测
├── _conf_schema.json    # 配置 Schema
├── requirements.txt     # 依赖
├── tests/
│   └── test_policy.py   # 策略与提醒的单测
├── LICENSE              # MIT
├── logo.png             # 插件 Logo
└── assets/
    ├── 高峰时段.png
    └── 空闲时段.png
```

## 常见问题

**为什么只有叫机器人的时候才回提示？**

因为只有那时候才算一次真正的模型调用。群里的闲聊不叫醒机器人，本来也不会走模型，插件没必要插嘴，说了反而刷屏。

**别的插件自己调 LLM，能拦住吗？**

拦不干净。插件卡的是消息事件管道，走 AstrBot 默认的 LLM 请求链路一定被挡住。但其他插件通过 `context.llm_generate()` 这类内部接口主动发起的请求，AstrBot 没开这一层的口子，拦不到。

**手动开关和自动时段怎么配合？**

- 强制开启（放行）：所有消息都能用，不看时段，也不再提示
- 强制关闭（拦截）：模型暂停，只有白名单和管理员还能用，其余消息回一句手动拦截提示
- 两种强制期间都不会有「已进入高峰」「已到空闲」这类自然切换提示，也不会发定时提醒

**高峰期私信一直弹提示？**

私信默认每个会话一天只提示一次。嫌少就把 `private_notify_mode` 改成 `always`，嫌烦就改成 `never`。

**切换点会不会连发好几条一样的提示？**

以前会，现在不会了。AstrBot 给每条消息单开一个任务，切换那一刻同时进来的几条消息本来就是并发的，老版本里它们各自都判断出「该提示了」，于是各发一条。现在改成「谁先抢到谁发」：同一个切换点、同一个会话只有一条能发出去。定时提醒和这条回复也共用一份额度，所以同一个群不会既收到提醒、又收到回复。

顺带一提，切换过去超过 `transition_notice_window_minutes`（默认 10 分钟）就不再补发了。下午三点有人在群里随口说一句，机器人不该突然回你「已到达空闲时段」。

**我明明在高峰时段，怎么没被拦？**

先看三件事。今天是不是法定节假日（`/峰谷` 里能看到），当前供应商在不在 `affected_providers` 里，手动开关是不是被切成了 `always_allow`。这三条任意一条成立都不会拦。

**想换提示图片？**

把新图丢进 `assets/`，覆盖 `peak_image` / `offpeak_image` 指的那个文件名就行，不用改代码。

## 开发与测试

测试只有一个文件，在装好 AstrBot 的环境里（或者你自己把 `astrbot` 放到 `PYTHONPATH` 上）跑：

```bash
python -m unittest discover -s tests
```

覆盖的是节假日判定、手动开关优先级、`holidays` 缺失时的退化、提醒在假期不发、状态文案和下次切换的一致性这些。改 `main.py` 里策略相关的逻辑前，先跑一遍心里有底。

## 更新日志

每个版本改了什么都在 [CHANGELOG.md](./CHANGELOG.md)，按 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的格式记。

## License

[MIT](LICENSE)
