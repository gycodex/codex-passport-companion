# 本机浏览器控制台 / Local browser console

本功能在 `feature/lan-connection` 分支。控制台兼容已有 BLE 固件和本分支 LAN 固件，**不需要为了控制台重新刷机**。设备当前选择哪种连接模式，就在网页选对应模式；网页不能远程切换设备的 BLE/Wi-Fi 模式。

## 启动

先安装 Python 3.10+、Codex CLI，并在当前系统用户下完成 Codex 登录。

- **Windows：**双击仓库根目录 `start-console.vbs`（无黑窗口），或使用 `start-console.cmd` 查看启动错误。首次启动会检查 Python 版本、创建独立 Python 环境并安装依赖。旧版 Python 环境会备份后重建；如果控制台已在运行，直接打开网页。
- **macOS：**在终端执行 `bash start-console.command`。也可先 `chmod +x start-console.command`，然后双击启动。首次使用蓝牙时允许系统的蓝牙访问请求。
- 浏览器自动打开 `http://127.0.0.1:8766/`。以后重复启动会打开已有控制台，不建立第二个桥接。
- 关闭浏览器标签页不会断开；Windows 后台不需要保留终端，点击网页底部「退出后台」可退出程序并断开设备。macOS 仍需保持启动终端运行，也可按 Ctrl+C 退出。

手动启动：

```sh
python -m pip install -r tools/requirements-console.txt
python tools/passport_console.py
```

可用参数：`--no-browser`、`--port 8766`、`--config-dir 路径`。不同端口启动多个程序会各自占用桥接，请避免同时连接同一设备。

## 首次连接

**局域网**：选 `Wi-Fi / LAN`，输入设备网络信息页显示的 IPv4 地址，点击 `Import pairing file` 导入配网下载的 `passport-lan.json`，再点 `Save & connect`。电脑可用网线，设备需接 2.4 GHz Wi-Fi，两者须在可互通的局域网。设备重新获取地址后，在断开状态修改 IP 即可。

**蓝牙**：设备须已处于蓝牙模式。选 `Bluetooth` → `Search for devices`，选择设备，点 `Save & connect`。首次按系统配对窗口输入设备屏幕上的六位数字。电脑须有蓝牙适配器；通过本机 Python 连接，浏览器不需要 Web Bluetooth 支持。

已有命令行桥接需先退出；一个设备同一时间只由一台电脑同步。超时可能是 IP 改变、网络隔离、设备离线或其他电脑仍占用连接，不能仅凭超时断言设备被占用。

## 日常使用

- `Save` 保存配置；`Disconnect` 停止同步并释放连接，配置保留。
- `Connect when this console starts` 表示**启动控制台时自动连接**，不是系统开机自启。
- 「提醒检查 → 播放提醒」 在当前连接中发送完成事件，不另开连接。事件会推进本机完成序号，并遵循设备音量和夜间静音规则。
- 左侧显示实际返回的额度窗口、任务数量和最近同步时间。未返回的窗口不显示。
- 默认优先从当前用户正在运行的 Codex CLI / app-server 进程取得可执行文件路径，无需填写。排除桌面界面进程和其他用户的进程；进程退出或不可读时自动跳过。找不到运行进程时，再查 Windows 常见 npm 安装位置及 macOS 的 PATH、Homebrew、nvm 等位置。进程参数仅用于辨别 CLI，不保存或输出到日志。特殊安装位置可在「高级设置」取消「自动查找 Codex」，再手动指定。

## 本机数据与验证范围

页面及 API 仅监听 `127.0.0.1`，校验 Host、Origin 和每次程序启动生成的请求令牌；页面不加载外部字体或脚本。配置保存在 `$CODEX_HOME/passport-console`，未设置时为 `~/.codex/passport-console`。`pairing.json` 含密钥，不应分享或提交到 Git；网页状态和活动日志不返回密钥。文件使用当前用户权限保存（Unix 新文件模式 0600）。同一系统账户中的其他程序仍能读取这些配置。

Windows 本机已验证控制台启动、LAN 连接、输入法适配及语音试用。另一台电脑首次安装、macOS、BLE 实机完整验收和规定的连接循环／长时间 soak 均为 NOT RUN，详见 [发布检查](RELEASE_CHECKLIST.md)。

豆包需要在语音设置中主动启用实验性适配，并在退出已有后台后使用 `start-console-admin.cmd`。普通用户无需管理员权限或 Frida。兼容构建限制和降级方式见 [语音说明](VOICE.md)。

## English quick start

Install Python 3.10+ and the Codex CLI, then sign in to Codex. Run `start-console.cmd` on Windows or `bash start-console.command` on macOS. Select LAN (device IP + pairing JSON) or Bluetooth (scan + OS pairing prompt), then **Save & connect**. Existing firmware is supported without a console-specific update. On macOS, keep the launcher terminal running. Windows runs in the background; closing the browser tab does not stop the bridge. Autoconnect applies when the console starts, not at OS login. macOS and physical BLE validation are pending.
