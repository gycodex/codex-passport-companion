# FoloToy AI Passport · Codex 用量伙伴

**简体中文** · [English](README.md)

这个固件把 FoloToy AI Passport 变成一个注重隐私的 Codex 桌面伙伴：显示当前
5 小时与 7 天窗口的剩余比例、以进度条展示余量、显示正在进行的任务数，并在
Codex 生成最终答复时显示 6 秒钟的 **任务已完成** 提示。首页右上角同时显示电量。

当前发布版本：**0.1.0**。

实现基于仓库的 `demo/claude-buddy-port` 参考分支，保留了有界状态机、像素 UI、
加密 Nordic UART BLE、绑定与自动重连。新增的本机桥接器负责把 Codex 数据转换成
设备协议。

## 数据流与隐私

```text
Codex app-server ── 限额快照 ───────────┐
                                        ├─ 本机 Python 桥 ── 加密 BLE ── Passport
~/.codex/sessions ─ 消息元数据 ─────────┘
```

桥接器通过本机 Codex app-server 调用 `account/rateLimits/read`。为了识别任务开始和
`final_answer`，它只读取本地 JSONL 记录的类型、角色与阶段，不会把提示词或回答
正文发送到设备，也不会读取或复制 Codex 登录令牌。

Codex 返回的是已用百分比而不是绝对消息数，所以设备显示
`剩余 = 100 - usedPercent`。如果接口在窗口重置时暂时不可用，桥接器会先切换到
下一个周期并在恢复连接后校准；如果从未取得过快照，界面会明确显示不可用。

## 编译与烧录

使用 ESP-IDF 5.5.3，目标芯片为 ESP32-C3：

```bash
get_idf553
idf.py set-target esp32c3
idf.py build
idf.py flash monitor
```

设备名为 `Codex-<MAC 后缀>`。首次加密连接时 Passport 会显示六位配对码，请在
操作系统的蓝牙配对窗口中输入。

## 运行本机桥接器

请先安装并登录 Codex CLI，建议使用 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements-codex-bridge.txt
.venv/bin/python tools/codex_bridge.py
```

常用选项：

```bash
# 不使用蓝牙，只验证本机 Codex 用量数据。
python3 tools/codex_bridge.py --dry-run

# 周围有多台设备时指定设备。
python3 tools/codex_bridge.py --device Codex-A1B2C3
```

桥接器每 60 秒刷新一次用量、每 2 秒刷新任务数、每 10 秒发送一次心跳，BLE
中断后会自动重连；按 `Ctrl+C` 停止。

## 按键

- `UP`：在首页、用量页、信息页之间切换。
- `DOWN`：滚动或切换子页面。
- 长按 `OK`：打开菜单。
- Settings → Unpair：经设备端确认后删除 BLE 绑定。

## 测试

```bash
get_idf553
cmake -S tests -B build-host
cmake --build build-host
ctest --test-dir build-host --output-on-failure
python3 -m unittest tests/test_codex_bridge.py
```

固件编译成功不等于真机验收。真机还需分别验证配对、两个用量窗口、重置倒计时、
运行/就绪状态、完成庆祝提示、断线重连、电池显示和 BLE 长连接稳定性。

## 归属

BLE 与 Buddy 应用基础来自本仓库的 `demo/claude-buddy-port` 分支；该分支记录了与
Anthropic 公开 Hardware Buddy 协议的兼容关系。归属信息见 [NOTICE](NOTICE)。
本 Codex 扩展与桥接器不是 OpenAI 官方硬件集成。
