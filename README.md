# Xiaomi BLE Control

Home Assistant 自定义集成，通过本机蓝牙或 **ESPHome 主动蓝牙代理** 控制
`szxzh.fan.f11` / AIVI F11 Pro。

**无需小米网关，无需 XiaomiGateway3，无需小米云账号。**
这是独立 HACS 集成，不是官方 `xiaomi_ble` 的替换，也未被 HA Core 收录。

## 功能

- 风扇开关、1–100% 调速；0% 关闭。
- 已验证的 Mi Standard BLE 认证、AES-CCM 状态回读。
- 自动发现 F11；界面输入 MAC/12 字节 BLE token。
- 断线重连、30 秒状态失联检测、定期更新认证会话。
- 属性：电量、充电状态、夜灯、定时和剩余时间。
- 本次没有夜灯/定时控制实体，也不模拟米家 UI 的自然风模式。

`fan.turn_on` 不传 percentage 时，按米家逻辑以最低风速启动。
界面显示来自真实设备回报，不使用乐观状态。

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

原 Gateway3 实验版已在 F11 Pro + ESP32-C3 Proxy 上验证开关、20%/40% 调速、
状态回读及 HA 重启重连；独立集成的验证结果见发布说明。

参考：
- [官方 MIoT F11 规格](https://home.miot-spec.com/spec/szxzh.fan.f11)
- [Mi Home 蓝牙开发说明](https://github.com/MiEcosystem/miot-plugin-sdk/wiki/03-%E8%93%9D%E7%89%99%E8%AE%BE%E5%A4%87%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97)
- [Telink Mi GATT 规格](https://github.com/telink-semi/tc_ble_mesh/blob/master/vc_debug_tool/ble_lt_mesh/vendor/common/mi_api/libs/ble_spec/gatt_spec.h)
- [原实验版](https://github.com/E7G/XiaomiGateway3/blob/master/F11.md)

MIT License。非小米官方项目。
