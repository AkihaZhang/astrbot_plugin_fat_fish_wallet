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

一个 AstrBot 插件：按照模型供应商的峰谷计费，在高峰时段自动暂停所有模型服务，空闲时段自动恢复，从源头上省掉高峰时段的模型调用费用。

## 背景

学生党想给 bot 接官方 DeepSeek API，个人开发者又买不到价格合适、额度够用的 Coding Plan——如今各家订阅普遍涨价、额度缩水，API 高峰时段的价格也偏高。这个插件做的事情很简单：高峰时段（默认 09:00-12:00、14:00-18:30）自动停掉模型调用，等到空闲时段再恢复，能省一点是一点。

## 功能特性

- 自动识别当前会话使用的模型供应商（匹配 provider 的 id / 模型名 / 适配器名），不写死 DeepSeek，换供应商也生效
- 高峰时段暂停服务，只对唤醒/艾特消息回复提示（群聊闲聊不刷屏）；空闲时段自动恢复并提示
- 白名单：指定用户或群聊可无视拦截，正常使用
- 时段自动提醒：高峰开始前几分钟、以及高峰结束（12:00 / 18:30）时，主动推送到指定群聊
- `/峰谷` 查询当前时段、下次切换时间、模型供应商、今日拦截统计
- 管理员可手动强制开启（放行）/ 关闭（拦截）/ 自动
- 时段、星期、时区、提示文案、图片、提醒目标均可配置
- 全平台通用（aiocqhttp、telegram、lark、discord 等）

## 公共策略接口

其他插件可调用活动实例的 `FatFishWalletGuard.get_wallet_policy(*, at=None, provider_id=None)` 获取只读决策。返回内容包括 `enabled`、`allowed`、`state`、`timezone`、`manual_override`、`provider_affected`、`holiday`、`holiday_name`、`peak_periods` 和 `peak_weekdays`。普通消息闸门、`/峰谷` 状态、启动状态和高峰提醒均使用同一策略函数；自动模式按 `holidays.CN()` 将中国法定节假日视为非高峰，节假日不会生成虚假的进/出高峰提醒。强制放行/拦截及总开关优先于自动时段策略；此接口不处理管理员或白名单豁免。

## 安装

1. 将 `astrbot_plugin_fat_fish_wallet` 文件夹放入 AstrBot 的 `data/plugins/` 目录，或在 WebUI 插件页选择「上传安装」上传 `astrbot_plugin_fat_fish_wallet.zip`。
2. 在 WebUI 插件页启用 / 重载插件。首次安装会自动安装依赖（`requirements.txt`，Windows 下含 `tzdata`）。
3. 按需在插件配置中修改时段、文案、图片、提醒目标等。

## 使用方法

| 指令 | 说明 | 权限 |
| --- | --- | --- |
| `/峰谷` | 当前时段、时段配置、下次切换、供应商、白名单、今日统计（附图片） | 所有人 |
| `/峰谷 统计` | 今日拦截 / 豁免统计 | 所有人 |
| `/峰谷 强制 开启` | 强制放行，不受时段限制（同义：放行） | 管理员 |
| `/峰谷 强制 关闭` | 强制拦截，暂停模型使用（同义：拦截） | 管理员 |
| `/峰谷 强制 自动` | 恢复按时段自动拦截/放行 | 管理员 |
| `/白名单` | 查看白名单 | 所有人 |
| `/白名单 添加 用户 <ID>` | 添加用户白名单 | 管理员 |
| `/白名单 添加 群 <ID>` | 添加群聊白名单 | 管理员 |
| `/白名单 移除 用户\|群 <ID>` | 移除白名单 | 管理员 |
| `/白名单 清空` | 清空白名单 | 管理员 |

命令别名：`/峰谷` 也支持 `/时段`、`/peak`、`/钱包`、`/谷`；`/白名单` 也支持 `/wl`、`/whitelist`。
提示仅在唤醒消息（带唤醒前缀，如 `@机器人` 或自定义前缀词）时回复；普通群聊消息会被静默拦截，不刷屏。手动强制开启/关闭时不触发自然时段切换提示。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 总开关 |
| `timezone` | `Asia/Shanghai` | 时区（IANA 名称） |
| `peak_periods` | `09:00-12:00,14:00-18:30` | 高峰时段，含开始不含结束 |
| `peak_weekdays` | `0,1,2,3,4,5,6` | 生效星期（0=周一…6=周日，留空=每天） |
| `affected_providers` | `deepseek` | 拦截的供应商匹配词，`*`=全部，留空=不拦截 |
| `gate_when_provider_unknown` | `true` | 识别不到供应商时是否仍拦截 |
| `admins_bypass` | `true` | 管理员是否豁免 |
| `attach_images` | `true` | 回复是否附带图片 |
| `peak_image` / `offpeak_image` | `高峰时段.png` / `空闲时段.png` | 图片文件名（替换 `assets/` 同名文件即可换图） |
| `peak_msg_enter` / `peak_msg_steady` | 高峰提示文案 | 支持 `{provider}`、`{time}` |
| `offpeak_msg` | 恢复提示文案 | 同上 |
| `manual_block_msg` | 手动拦截提示文案 | 同上 |
| `manual_override` | `auto` | `auto` / `always_allow`（放行）/ `always_block`（拦截） |
| `announce_transition` | `true` | 时段切换时是否发送提示 |
| `private_notify_mode` | `once` | 私信高峰提示频率：`once`（每天一次）/ `always`（每次）/ `never`（不提示） |
| `whitelist_users` / `whitelist_groups` | `[]` | 初始白名单种子，之后用 `/白名单` 指令管理 |
| `reminder_enabled` | `true` | 时段自动提醒总开关 |
| `reminder_targets` | `[]` | 提醒目标；留空=自动记录的所有群；也可填群号或完整消息来源 |
| `reminder_lead_minutes` | `5` | 高峰开始前提前多少分钟提醒 |
| `reminder_peak_msg` | 高峰即将到来文案 | 支持 `{time}` |
| `reminder_offpeak_msg` | 空闲到来文案 | 支持 `{time}` |

**关于提醒目标**：插件会自动记录与机器人互动过的群聊（存于插件 KV）。`reminder_targets` 留空时提醒会发送到所有已记录群聊；你也可以填群号（自动匹配记录到的群）或完整 `unified_msg_origin`（形如 `aiocqhttp:GroupMessage:群号`，可用 `/sid` 或日志获取）来限定范围。提醒仅在自动模式下、且当天高峰开始前与结束时各发送一次。

## 目录结构

```
astrbot_plugin_fat_fish_wallet/
├── metadata.yaml        # 插件元数据
├── main.py              # 插件主逻辑
├── scheduler.py         # 峰谷时段计算（纯逻辑，可单独测试）
├── _conf_schema.json    # 配置 Schema
├── requirements.txt     # 依赖（Windows 下 tzdata）
├── LICENSE              # MIT 许可证
├── logo.png             # 插件 Logo
└── assets/
    ├── 高峰时段.png
    └── 空闲时段.png
```

## 常见问题

**为什么提示只在唤醒消息时回复？**
高峰期群聊消息量大，逐条回复会刷屏。只有带唤醒前缀或艾特机器人的消息才属于主动调用，此时回复提示才有意义；其余消息静默拦截。

**其他插件主动调用 LLM 能拦吗？**
不能完全拦住。拦截作用于消息事件管道（`stop_event()` + `should_call_llm(False)`），AstrBot 默认的 LLM 请求链路不会执行；但其他插件通过 `context.llm_generate()` 等主动发起的请求属于内部调用，AstrBot 未提供该层级的阻断 API。

**手动强制开启/关闭有什么行为？**
- 强制开启（放行）：所有消息不受时段限制，恢复正常使用，不再提示。
- 强制关闭（拦截）：暂停模型使用，仅白名单/管理员仍可用，其余消息回复手动拦截提示。
- 手动开关激活期间，不会触发自然的「已进入高峰 / 已到达空闲时段」提示，也不会发送定时提醒，避免与实际状态矛盾。

**更换提示图片？**
把新图片放到 `assets/` 下，覆盖 `peak_image` / `offpeak_image` 指向的文件名即可，无需改代码。

## 开发与测试

```bash
python test_fat_fish_scheduler.py   # 时段逻辑单测
python test_fat_fish_smoke.py       # 桩环境冒烟测试
```

## License

[MIT](LICENSE)
