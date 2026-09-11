# v0.2.2 下载与安装

这是预发布版。仅适用于 FoloToy AI Passport（ESP32-C3、8 MB Flash）。

## 下载哪个文件

| 文件 | 用途 |
| --- | --- |
| `passport-windows-x64-v0.2.2.zip` | Windows 10/11 x64 推荐。含电脑控制台、独立 Python 运行时、依赖、固件和刷机工具；无需另装 Python |
| `passport-desktop-source-v0.2.2.zip` | macOS/Linux 或自行管理 Python 的用户。需要 Python 3.10+；首次启动联网安装依赖 |
| `passport-firmware-v0.2.2.zip` | 固件与刷机脚本。已下载 Windows 包的用户无需重复下载 |
| `SHA256SUMS.txt` | 三个下载包的 SHA-256 校验值 |

先完整解压，不要直接在压缩包内运行程序。解压到普通可写目录，保留所有子目录。

## Windows：启动电脑端

1. 启动并登录自己的 Codex 桌面应用或 CLI。此下载包不包含 Codex 或登录凭据。
2. 双击 `start-console.vbs`。如果无法启动，运行 `start-console.cmd` 查看错误。
3. 本机网页打开后，选择蓝牙或局域网并连接。蓝牙首次使用需输入设备上的六位配对码。
4. 若使用语音，另行安装虚拟音频线和输入法，按 `docs/VOICE.md` 配置。基础用量显示不需要音频驱动。

程序未做代码签名；仅从本项目 Release 下载并核对校验值。Windows ARM64 未验证。
关闭网页不会退出后台；请使用网页中的“退出”。

## macOS/Linux：启动电脑端

解压 desktop-source 包，安装并登录 Codex，再在终端进入解压目录执行：

```bash
bash start-console.command
```

需要 Python 3.10+。Linux 音频可能需要系统 PortAudio 包；macOS 语音需要 BlackHole
以及相应蓝牙、麦克风和辅助功能权限。macOS 整机及跨电脑语音验收尚未完成。

## 更新设备固件

1. 先退出电脑控制台和串口监视器，用 USB 数据线连接 Passport。
2. Windows 一体包：双击 `flash-firmware.cmd`。macOS/Linux 固件包：运行 `bash flash-firmware.command`。
3. 核对设备串口和版本，输入 `FLASH` 确认。多个设备时需要自行选择串口。
4. 工具先校验固件与设备分区布局，再备份原应用，最后仅更新 `0x10000` 主应用分区并校验。
5. 备份放在包内 `backups/`；刷写日志也在该目录。成功后重启设备，再打开控制台连接。

Windows 固件精简包不含运行时，可安装 Python 3.10+，执行
`python -m pip install esptool==4.12.0` 后再运行脚本；更推荐下载 Windows 一体包。

**不要写入 recovery 分区，也不要执行整片擦除。** 本版本的主应用超过 1 MB，不能放入
设备的 recovery 分区。工具保留 NVS（配网、绑定）、cardid 和 recovery。
若提示分区布局不匹配，工具会停止；不要绕过检查或按其他板型刷写。
`bootloader.bin` 和 `partition-table.bin` 仅附作开发者参考，默认刷机工具不会覆盖它们。

## 已知范围

- 含 Codex 用量、任务完成/中断提示、BLE/LAN、语音输入、菜单精简。
- 等待输入、审批和任务失败提醒尚未接入。
- 豆包仅适配文档中已校验的 Windows 版本，首次启用仍需联网安装可选组件并接受 Windows 授权。
- 未捆绑 Codex、豆包、VB-CABLE、BlackHole 或 Frida 二进制。
- 不是完成全部硬件验收的稳定版；第二台电脑、macOS、20 次重连和 30 分钟压力测试仍有未验证项。
- 许可范围与上游授权待确认事项见 `NOTICE`，不能将整个分发包统一宣称为 MIT。

发布页：https://github.com/gycodex/codex-passport-companion/releases/tag/v0.2.2
