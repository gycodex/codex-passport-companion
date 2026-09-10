# FoloToy AI Passport · Codex 用量伙伴

**简体中文** · [English](README.md)

这个固件把 FoloToy AI Passport 变成一个注重隐私的 Codex 桌面伙伴：显示当前
接口实际返回的用量窗口剩余比例（例如 7 天）、以进度条展示余量、显示正在进行的任务数，并在
Codex 生成最终答复时显示 6 秒钟的 **任务已完成** 提示。首页右上角同时显示电量。

窗口名称按实际分钟数生成；没有返回的窗口不会显示，也不会被当作剩余 100%。

当前固件版本：**0.1.0-idle-sleep**。

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

## 致谢

本项目基于 [zt20/codex-usage-ai-passport](https://github.com/zt20/codex-usage-ai-passport) 二次开发。感谢原作者 **zt20** 开源 Codex 用量显示固件及桥接程序，为这个桌面伙伴提供了基础。

同时感谢：

- [FoloToy/ai-passport](https://github.com/FoloToy/ai-passport)：提供 AI Passport 平台及开源固件基础。
- [Shinku-Chen/ai-passport 的 feature/voice-keychain 分支](https://github.com/Shinku-Chen/ai-passport/tree/feature/voice-keychain)：在排查和调校任务完成提示音时，提供了音频实现参考。
- [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)：提供公开的 Hardware Buddy BLE 协议参考。原有归属与许可声明保留在 [NOTICE](NOTICE) 中。

本仓库在这些工作的基础上，增加了用量窗口自适应、首页像素宠物、任务轻提醒、自动息屏及蓝牙稳定性修复。本 Codex 扩展与桥接器不是 OpenAI 官方硬件集成。

## 本地增强：轻提醒

### 自动息屏

默认连续空闲 5 分钟关闭背光并暂停界面动画重绘，蓝牙与用量同步继续运行。新任务、实时任务完成、配对码或待确认操作会亮屏；运行中或等待处理的任务保持亮屏。普通空闲心跳和重复完成事件不重置计时。

设置菜单的 **Auto sleep** 可选 **1 min / 5 min / 10 min / Never**，断电保存。任意键点击或长按可唤醒，唤醒的这一次操作不执行其他功能。亮屏恢复之前设置的亮度。此功能关闭背光，不进入会中断蓝牙的深度睡眠。

蓝牙状态中的 `sys.screen_off` 报告息屏状态，`sys.sleep_mode` 的 0/1/2/3 分别对应 1/5/10 分钟及永不息屏。

### 完成提示音

任务完成后播放一次约 0.18 秒的轻柔双音。长按确认键打开菜单，进入设置 → 声音，可循环切换 Off / On / Auto，并保存到设备。

- Off：始终静音。
- On：全天提示。
- Auto（默认）：按电脑同步的本地时间，在 22:00–08:00 静音；未同步时间时也不响。

重复心跳不重复响铃，断线重连不补响旧任务。密集完成事件合并提醒；提示音由独立音频任务播放。

扬声器听感校准采用编解码器音量 80、PCM 峰值 10000，保留缓入缓出。`status` 响应附带 `sound`：`mode` 为 0/1/2（Off/On/Auto），`stage` 为 0（未触发）、1（初始化）、2（配置格式）、3（音量）、4（写入）、5（写入完成）、100（失败），`played` 是本次开机成功写入音频的次数，并不证明实际听感。首次播放需要初始化音频设备。
