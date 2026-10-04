# Xiaomi BLE Control

Home Assistant 自定义集成，通过本机蓝牙或 **ESPHome 主动蓝牙代理** 控制
`szxzh.fan.f11` / AIVI F11 Pro。

**无需小米网关，无需 XiaomiGateway3，无需小米云账号。**
这是独立 HACS 集成，不是官方 `xiaomi_ble` 的替换，也未被 HA Core 收录。

## 功能

- 主风扇：开关、米家原生 1–5 档。
- 独立数字实体：档位 0–5、无级调速 0–100%、设备端关机定时 0–480 分钟。
- 夜灯 `light`：开关，不支持调光。
- 传感器：电量、充电状态、工作状态、倒计时剩余秒数、充电/连接二进制状态。
- 可选四档风扇：适配现有巴法云插件，映射实际第 2–5 档。
- 已验证的 Mi Standard BLE 认证、AES-CCM 状态回读。
- 自动发现 F11；界面输入 MAC/12 字节 BLE token。
- 断线重连、30 秒状态失联检测、定期更新认证会话。
- 仅暴露已经确认的硬件功能；不伪造自然风、摇头、调光或 OTA 更新。

`fan.turn_on` 不传 percentage 时，按米家逻辑以最低风速启动。
界面显示来自真实设备回报，不使用乐观状态。

### 五档与无级调速

| HA 主风扇档位 | HA `percentage` | 设备实际百分比 |
|---|---|---|
| 1 | 20 | 1 |
| 2 | 40 | 25 |
| 3 | 60 | 50 |
| 4 | 80 | 75 |
| 5 | 100 | 100 |

这与米家插件的五档按钮一致。`percentage_step=20`，巴法云/HA 不再把它误当成 100 档。
主实体的 `percentage` 是逻辑档位，`device_percentage` 属性是设备真实风速。
无级调速实体直接读写设备百分比；中间值在主风扇上显示最近的档位。
0 档 / 0% 关闭。定时 0 表示取消，单位为分钟；倒计时传感器单位为秒。

**从 v0.1.0 升级：** 主风扇百分比改为逻辑档位。需要原始 1–100% 风速的自动化，
请改用 `number` 的无级调速实体。现有主风扇实体 ID 不变。

### 巴法云四档

复用 [larry-wong/bemfa](https://github.com/larry-wong/bemfa)，通过四档实体适配。
旧版插件会在关机状态下丢弃 `on#4` 的档位参数；修复见
[上游 PR #99](https://github.com/larry-wong/bemfa/pull/99)。遇到该问题需应用解析修复，
它不改变插件四档限制，也不更改其他主题配置。
1. 在 HA 实体列表启用本集成默认禁用的 **Bemfa fan** 四档实体。
2. 巴法云集成 → 配置 → 创建同步，选择该四档实体，而不是主五档风扇。
3. 再为夜灯实体创建同步，名称可用“艾维风扇”“艾维夜灯”。

| 巴法云命令 | HA 实际档位 | 设备风速 |
|---|---|---|
| `on#1` | 2 | 25% |
| `on#2` | 3 | 50% |
| `on#3` | 4 | 75% |
| `on#4` | 5 | 100% |
| `off` | 关闭 | 0% |

四档实体 `percentage_step=25`，默认开启为实际第 2 档。它与主风扇共享同一个 BLE
会话，并非第二个控制器。HA 独有的最低档仍可直接使用；其巴法云档位回传为 0，
不冒充四档中的第一档。插件自动生成 `hass…003` 风扇和 `hass…002` 灯主题。

米家插件“直吹风/自然风”仅改变手机本地 `mode` 存储和无级/五档控制面板，
没有 BLE 模式属性或模式写入；本集成不把这个界面切换冒充硬件自然风功能。

## 安装

1. HACS → 自定义仓库，添加：`https://github.com/E7G/xiaomi-ble-control`，类别选 **Integration**。
2. 下载 **Xiaomi BLE Control**，重启 HA。
3. 设置 → 设备与服务 → 添加集成 → **Xiaomi BLE Control**；或选择自动发现的 F11。
4. 输入风扇 MAC 和 **24 个十六进制字符的 BLE token**。

最低 HA 版本：2025.1。自动发现的设备仅限产品 ID `24466`。
手动填写也会核对产品 ID，并真实验证认证 token。

也可将仓库的 `custom_components/xiaomi_ble_control` 放入 HA 配置目录下的
`custom_components/`，然后重启。

### Token 类型

这里需要 **12 字节 Mi Standard BLE 认证 token**。它不是网关 token、MIoT OAuth token，
也不是 16 字节 MiBeacon bindkey / Wi-Fi miio token。

从自己已配对的米家设备/账号取得 token。本集成不自动配对、重置设备或提取 token。
Token 存在 HA 的 config entry 中，配置界面使用密码输入框；诊断信息不含凭据。
不要把 token、HA `.storage`、SSH 密码或米家抓包上传到 GitHub。

## 从 Gateway3 F11 实验版迁移

1. 备份 HA 配置和 `custom_components/xiaomi_gateway3`。
2. 删除 `configuration.yaml` 中 `xiaomi_gateway3.ble_fans` 的对应 F11 项。
   不要删除其他 Gateway3 设备/配置。
3. 重启 HA，让旧控制器释放蓝牙连接。
4. 添加本集成，填相同 MAC/token。
5. 如原风扇实体仍占用 `fan.aivi_f11_pro`，删除旧实体后将新实体 ID 改回原 ID，
   即可继续沿用引用此实体 ID 的卡片和自动化。
6. 成功后可恢复官方 Gateway3 版本；本集成与它完全独立。

**同一风扇只启用一个主动控制器。** 米家风扇页面也会占用唯一的 BLE 连接。

## 连接排查

- ESPHome Proxy 需要支持 **active GATT connections**，不能只有被动广播转发。
- 退出其他手机/平板的米家风扇页面。
- 风扇靠近蓝牙适配器/代理；金属遮挡、较低 RSSI 会影响连接。
- 若设备休眠、没有新广播，短按风扇实体电源键唤醒。
  已休眠/关闭的无线电不能靠 GATT 命令唤醒。
- 更换/重新配对导致 token 改变：集成菜单 → **重新配置**。
- 下载诊断可查看连接阶段、代理来源和设备属性；不含认证凭据。

## 协议与开发

协议层 `protocol.py` 不依赖 HA，可独立测试；连接和 UI 层分别位于
`coordinator.py`、`config_flow.py`、`fan.py`。

F11 的 `3.p.2` 写入值为 **0–100**，运行时通知值为 **128 + 风速百分比**，
空闲通知值为 `1`。开关同样写 `3.p.2`，不写工作状态 `3.p.1`。

```sh
pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
```

独立集成已在 F11 Pro + ESP32-C3 Proxy 上实机验证：
全部五档、四档云端映射、无级调速、夜灯开关、定时写入/取消和真实倒计时。
认证、HA 重启重连及界面重新配置也已验证。
33 项自动测试通过；发布前同时运行 GitHub Actions。

参考：
- [官方 MIoT F11 规格](https://home.miot-spec.com/spec/szxzh.fan.f11)
- [Mi Home 蓝牙开发说明](https://github.com/MiEcosystem/miot-plugin-sdk/wiki/03-%E8%93%9D%E7%89%99%E8%AE%BE%E5%A4%87%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)
- [Telink Mi GATT 规格](https://github.com/telink-semi/tc_ble_mesh/blob/master/vc_debug_tool/ble_lt_mesh/vendor/common/mi_api/libs/ble_spec/gatt_spec.h)
- [原实验版](https://github.com/E7G/XiaomiGateway3/blob/master/F11.md)

MIT License。非小米官方项目。
