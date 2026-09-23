# FoloToy AI Passport · Codex 用量伙伴

**简体中文** · [English](README.md)

这个固件把 FoloToy AI Passport 变成一个注重隐私的 Codex 桌面伙伴：显示当前
接口实际返回的用量窗口剩余比例（例如 7 天）、以进度条展示余量、显示正在进行的任务数，并在
Codex 生成最终答复时显示 6 秒钟的 **任务已完成** 提示。首页右上角同时显示电量。

窗口名称按实际分钟数生成；没有返回的窗口不会显示，也不会被当作剩余 100%。

当前分支固件版本：**0.2.5**（预发布）。见[更新说明](docs/releases/v0.2.5.md)。

**普通用户直接下载：[Windows 一体包](https://github.com/gycodex/codex-passport-companion/releases/download/v0.2.5/Passport-Windows-x64-v0.2.5.zip)**。完整解压，按需双击升级工具更新设备，再双击 `Passport.exe`。无需 Python；包内含配套固件、升级工具和[三步上手说明](docs/QUICKSTART.zh_CN.md)。

电脑桥接现在识别日志中的 `turn_aborted`：仅结束对应轮次的运行计数，在首页短暂显示约 6 秒的 `Task interrupted`，不增加完成计数、不触发完成庆祝或提示音。其他任务仍可继续运行；同批有任务完成时，优先显示完成提醒。桥接启动或重新连接时不会补播旧中断。此功能复用现有状态文字，无需重刷固件；更新后重启电脑端桥接生效。等待输入、等待审批和任务失败尚未接入，不能从单次工具报错推断整个任务失败。

蓝牙或局域网桥接首次连接、断线恢复并收到首个有效状态时，会播放一声约 100 毫秒的连接提示音。普通同步不重复播放；遵循声音开关和自动模式的夜间静音设置。

**设备麦克风：**新固件与新版控制台可通过蓝牙或局域网把设备声音交给讯飞、豆包或 Typeless 等输入法，使用可配置快捷键开始和结束。需要安装虚拟音频线；蓝牙需要安全配对及足够的协商数据包大小，录音稳定性仍需实测。详见 [语音输入设置](docs/VOICE.md)。

**Windows 桌面版（源码启动）：**双击 `install-passport.cmd` 创建 Passport 桌面图标，或用 `start-console.vbs` 直接打开。首次使用按向导连接设备，以后在状态页查看任务与用量；关闭窗口后在托盘运行，可选登录 Windows 时启动。无需为桌面版重刷固件。详见 [桌面版说明](docs/DESKTOP.md)。网页版保留在 `start-browser.cmd`，macOS 仍使用 `bash start-console.command`。

**单文件 EXE：**已支持构建 `dist/windows-exe/Passport.exe`，无需 Python 和源码目录；同时生成带中文说明与许可证的 ZIP。构建方法和运行要求见 [EXE 说明](docs/DESKTOP.md#单文件-exe)。v0.2.5 一体包同时提供电脑 EXE 和配套固件；自动配对需使用配套固件。

**局域网连接：**支持加密 Wi‑Fi 传输，无蓝牙的台式机也可使用。支持手机连接设备热点，在网页中扫描、填写 Wi‑Fi，电脑搜索设备并核对号码完成配对；也可通过 USB 配网。保留蓝牙模式。详见 [局域网配网与使用说明](docs/LAN.md)。

实现基于仓库的 `demo/claude-buddy-port` 参考分支，保留了有界状态机、像素 UI、
加密 Nordic UART BLE、绑定与自动重连。新增的本机桥接器负责把 Codex 数据转换成
设备协议。

## 快速开始

Windows 10/11 x64 用户优先使用 [Windows 一体包](docs/DOWNLOADS.md)：

1. 完整解压 ZIP。设备需要升级时，连接 USB，运行 `升级设备固件.exe`，按提示备份、升级并校验。
2. 安装并登录 Codex，再双击 `Passport.exe`。需要 Microsoft Edge WebView2 Runtime，无需安装 Python。
3. 选择蓝牙并完成安全配对；或先[给设备连接 Wi-Fi](docs/LAN.md)，再在 Passport 中搜索设备，核对电脑和设备上的六位号码，两端确认后自动保存配对。

### 从源码运行

使用 **`main`** 分支：

```sh
git clone --branch main https://github.com/gycodex/codex-passport-companion.git
cd codex-passport-companion
```

1. 给 FoloToy AI Passport 刷入本分支固件，见下方「编译与烧录」。已有最新版固件可跳过。
2. 电脑安装 Python 3.10+ 和 Codex CLI，完成 Codex 登录。
3. Windows 双击 `start-console.vbs`；macOS 执行 `bash start-console.command`。
4. 在桌面窗口或浏览器控制台选择蓝牙或局域网，按提示配对并连接。配套固件支持搜索设备、核对号码自动配对。广播搜索不到时，当前源码控制台可使用“跨子网 / 按 IP 查找”，填写电脑可访问的设备 IP，仍通过六位码确认，无需配对文件；旧固件可使用单独的手动连接选项填写 IP、导入配对 JSON。需要麦克风时再配置语音输入。

| 想做什么 | 阅读这份说明 |
| --- | --- |
| 启动、连接、切换蓝牙 / 局域网、换电脑 | [控制台使用](docs/CONSOLE.md) |
| 给设备配置 Wi-Fi | [局域网配网](docs/LAN.md) |
| 讯飞 / 豆包语音输入 | [麦克风与输入法](docs/VOICE.md) |
| 已验证内容、已知限制和发布事项 | [验证记录](docs/RELEASE_CHECKLIST.md) |

设备首页：**上键换页，下键语音，长按确认打开菜单**。左上角显示 `已连接BLE` 或 `已连接LAN`，右上角显示电量。蓝牙和局域网都支持用量、任务状态、完成提醒及设备麦克风；同一设备一次只连接一台电脑。

语音需要虚拟音频线和本机输入法，不是系统原生蓝牙麦克风。Windows 豆包适配为实验性功能，仅支持已验证版本。蓝牙已试用，但延迟、识别率、其他电脑及长时间稳定性仍需验证。

## 数据流与隐私

```text
Codex app-server ── 用量 / 任务状态 ─────┐
                                        ├─ 本机 Python 桥 ── 加密 BLE / LAN ── Passport
~/.codex/sessions ─ 消息元数据 ─────────┘
```

桥接器通过本机 Codex app-server 的 `account/rateLimits/read` 和 `thread/list` 获取
用量与活动任务状态。它解析本地会话 JSONL 文件，使用记录类型、角色、阶段、时间戳、
会话与轮次标识及任务事件，识别任务开始、完成和中断。提示词和回答正文不会发送到设备；
桥接器也不会读取或复制 Codex 登录令牌。

Codex 返回的是已用百分比而不是绝对消息数，所以设备显示
`剩余 = 100 - usedPercent`。如果接口在窗口重置时暂时不可用，桥接器会先切换到
下一个周期并在恢复连接后校准；如果从未取得过快照，界面会明确显示不可用。

## 编译与烧录

安装并进入 ESP-IDF 5.5.3 的开发终端，目标芯片为 ESP32-C3：

```bash
idf.py set-target esp32c3
idf.py build
idf.py flash monitor
```

Windows PowerShell 下，若 CMake 报 ESP-IDF 路径转义错误，在激活 ESP-IDF 环境后执行
`$env:IDF_PATH = $env:IDF_PATH.Replace('\', '/')`，将路径改为正斜杠，再重新构建。

应用写入 `0x10000` 的 3 MB `factory` 分区。构建中针对独立 1 MB `recovery` 分区的
容量警告不代表 factory 分区已满。保留 `0x700000` 的出厂恢复镜像，不要向该分区写入本应用。

设备名为 `Codex-<MAC 后缀>`。首次加密连接时 Passport 会显示六位配对码，请在
操作系统的蓝牙配对窗口中输入。

## 运行本机桥接器

以下命令行示例使用 BLE。请先安装并登录 Codex CLI，使用 Python 3.10 或更高版本。命令适用于 macOS/Linux；Windows 可使用上面的源码启动脚本，或使用 `.venv\Scripts\python.exe` 并通过 `-m pip` 安装依赖：

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

设置菜单仅保留屏幕亮度、声音、自动睡眠、蓝牙、Wi-Fi、无线网络、伙伴形象和重置（另有返回项）。重置子菜单保留恢复出厂设置、解除蓝牙配对和返回；两项重置操作仍需设备端确认。已移除无实际效果的指示灯、任务记录、时钟旋转和删除自定义角色入口。此菜单精简需要更新设备固件。

- `UP`：在首页、用量页、信息页之间切换。
- `DOWN`：首页切换录音，用量页和信息页切换子页面，菜单内移动选项。语音转发需要另行完成语音设置。
- 长按 `OK`：打开菜单。
- 设置 → 重置 → 解除蓝牙配对：经设备端确认后删除 BLE 绑定。

## 测试

先进入 ESP-IDF 5.5.3 环境，确保已设置 `IDF_PATH`。Python 测试需使用已安装控制台开发依赖的环境。

```bash
cmake -S tests -B build-host
cmake --build build-host
ctest --test-dir build-host --output-on-failure
python3 -m unittest discover -s tests -p "test_*.py"
```

固件编译成功不等于真机验收。真机还需分别验证安全配对、实际返回的用量窗口及窗口缺失、
重置倒计时、运行/就绪状态、完成与中断提示、断线重连、电池显示和 BLE/LAN 稳定性。
至少执行 20 次连接/断开循环及 30 分钟持续连接，记录堆内存、看门狗、分配失败与传输错误。
未执行的真机检查标记为 `NOT RUN`，完整范围见[发布检查](docs/RELEASE_CHECKLIST.md)。

## 致谢

配网交互参考了 [leo0183/leo-radio](https://github.com/leo0183/leo-radio) 的设备热点与 `192.168.4.1` 网页配网流程，感谢作者公开实现。本项目按现有 C 固件和内存预算独立实现该流程，未移植电台功能。

本项目基于 [zt20/codex-usage-ai-passport](https://github.com/zt20/codex-usage-ai-passport) 二次开发。感谢原作者 **zt20** 开源 Codex 用量显示固件及桥接程序，为这个桌面伙伴提供了基础。

同时感谢：

- [FoloToy/ai-passport](https://github.com/FoloToy/ai-passport)：提供 AI Passport 平台及开源固件基础。
- [Shinku-Chen/ai-passport 的 feature/voice-keychain 分支](https://github.com/Shinku-Chen/ai-passport/tree/feature/voice-keychain)：在排查和调校任务完成提示音时，提供了音频实现参考。
- [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)：提供公开的 Hardware Buddy BLE 协议参考。原有归属与许可声明保留在 [NOTICE](NOTICE) 中。

本仓库在这些工作的基础上，增加了用量窗口自适应、首页像素宠物、任务轻提醒、自动息屏及蓝牙稳定性修复。本 Codex 扩展与桥接器不是 OpenAI 官方硬件集成。

## 本地增强：轻提醒

### 自动息屏

默认连续空闲 5 分钟关闭背光并暂停界面动画重绘，蓝牙与用量同步继续运行。新任务、实时任务完成、配对码或待确认操作会亮屏；运行中或等待处理的任务保持亮屏，到达设定时间后自动调暗至 20%。普通空闲心跳和重复完成事件不重置计时。

设置菜单的 **自动睡眠** 可选 **1 分钟 / 5 分钟 / 10 分钟 / 永不**，断电保存。任意键点击或长按可唤醒，唤醒的这一次操作不执行其他功能。亮屏恢复之前设置的亮度。此功能关闭背光，不进入会中断蓝牙的深度睡眠。

蓝牙状态中的 `sys.screen_off` 报告息屏状态，`sys.sleep_mode` 的 0/1/2/3 分别对应 1/5/10 分钟及永不息屏。

### 完成提示音

任务完成后播放一次约 0.18 秒的轻柔双音。长按确认键打开菜单，进入设置 → 声音，可循环切换关闭 / 开启 / 自动，并保存到设备。

- 关闭（Off）：始终静音。
- 开启（On）：全天提示。
- 自动（Auto，默认）：按电脑同步的本地时间，在 22:00–08:00 静音；未同步时间时也不响。

重复心跳不重复响铃，断线重连不补响旧任务。密集完成事件合并提醒；提示音由独立音频任务播放。

扬声器听感校准采用编解码器音量 80、PCM 峰值 10000，保留缓入缓出。`status` 响应附带 `sound`：`mode` 为 0/1/2（Off/On/Auto），`stage` 为 0（未触发）、1（初始化）、2（配置格式）、3（音量）、4（写入）、5（写入完成）、100（失败），`played` 是本次开机成功写入音频的次数，并不证明实际听感。首次播放需要初始化音频设备。

### 工作调暗与空闲关屏

「自动睡眠」的 1 / 5 / 10 分钟同时用于工作和空闲：工作中持续到时降至最低背光（20%），普通心跳不会重置计时；任务完成或进入空闲时恢复用户原亮度，再重新计算空闲关屏时间。按键、配对码、待确认操作和配网页面会恢复亮度。「永不」禁用自动调暗与自动关屏。调暗不改动用户亮度档位。设备菜单、状态提示和配网页面已补齐中文。

## 许可与发布状态

本项目原创贡献采用 [MIT](LICENSE)，继承代码和依赖的许可范围见 [NOTICE](NOTICE)。上游授权及未完成验证见 [发布检查](docs/RELEASE_CHECKLIST.md)。Windows 豆包适配为实验性功能，需主动启用，且仅支持校验通过的版本，详见 [语音设置](docs/VOICE.md)。
