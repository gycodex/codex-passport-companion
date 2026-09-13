# Windows 桌面伙伴

本页描述 v0.2.3 桌面版。独立窗口本身兼容旧固件；使用局域网自动发现与双端确认配对，需要同时升级 v0.2.3 固件。已发布的 v0.2.2 下载包不含这些改动。

## 单文件 EXE

构建产物为 `dist/windows-exe/Passport.exe`，双击即可打开，不需要 Python、源码目录或
首次联网安装程序依赖。Windows 10/11 x64 仍需 Microsoft Edge WebView2 Runtime。
把 EXE 放在固定目录，可自行创建桌面快捷方式；托盘支持登录 Windows 时启动。

`Passport-Windows-x64.zip` 包含相同 EXE、中文使用说明、SHA-256 和第三方许可文件。
这是便携程序，不是安装向导；Codex、输入法和虚拟音频驱动由用户自行安装。
EXE 内置 Frida 17.18.0，只在启用豆包兼容功能时使用；原有权限和版本校验保留。

更新前先退出旧版后台。完整打包复现方式：

```powershell
python -m pip install -r tools/requirements-build-exe.txt
python tools/build_windows_exe.py
```

EXE 的窗口、后台和授权辅助进程使用不同入口。独立子进程各自管理解压目录，避免
父进程退出清理资源后影响后台。登录启动指向固定位置的 EXE，不指向临时解压目录。
构建来源及源文件哈希保存在包内 `notices/BUILD.json`；未提交的源码构建会明确标记。

## 从源码打开与创建快捷方式

完整保留项目目录，双击 `install-passport.cmd`，即可在桌面和开始菜单创建 **Passport** 快捷方式。
以后双击图标打开独立窗口。也可以直接双击 `start-console.vbs`。
源码启动器使用便携目录加快捷方式的方式；创建快捷方式后不要移动或删除源码目录。

当前源码第一次运行需要 Python 3.10+，启动器会自动准备运行环境并安装依赖。
后续 Windows 一体包需预装 `tools/requirements-desktop.txt`，才可免装 Python 和依赖。
桌面窗口使用 Microsoft Edge WebView2 Runtime；如果启动失败，日志在配置目录的
`desktop.log`，可使用 `start-browser.cmd` 打开网页版。

## 第一次使用

1. 打开并登录 Codex。Passport 自动检查能否找到程序；此时不会宣称已经登录成功。
2. 点击“下一步：连接设备”。默认使用局域网，也可以选择蓝牙：在设备上开启蓝牙，点击搜索，选择自己的设备。
   有多台设备时必须自行选择；首次配对在 Windows 窗口输入设备显示的六位码。
   局域网模式点击「搜索局域网设备」，选择设备，核对六位号码并在两端确认即可。需要支持自动配对的新固件；旧版文件导入保留在兼容选项。
3. 局域网新配对成功后会自动连接；已有配对或蓝牙模式点击“连接设备”。首次同步成功后，点击“开始使用”。

向导默认选中“打开 Passport 时自动连接设备”，可以取消。
中途关闭或连接失败会保留已保存的配置，下次继续引导。
已有配置的用户直接进入状态页，不覆盖原连接方式和自动连接偏好。

## 日常使用

- 主页面查看任务和用量状态；“连接与功能设置”打开连接参数、语音输入和高级设置。
- 关闭窗口后，Passport 在系统托盘继续运行。再次双击桌面图标，会打开已有窗口。
- 托盘右键菜单可打开窗口、启用或关闭“登录 Windows 时启动”、退出程序。
- 登录启动默认关闭，仅在用户勾选后写入当前用户启动项。
- “退出”会等待后台确认断开，再关闭窗口。断开失败时保留窗口并提示重试。
- 语音是可选功能，仍需虚拟音频线和输入法；详见 [VOICE.md](VOICE.md)。

网页版关闭页面不会退出后台；请使用页面里的“退出”。豆包授权切换后台时，桌面窗口
会等待后台恢复，并在新后台令牌生效后刷新页面，不需要再开一个窗口。

## 更新或移除

更新前从托盘退出 Passport。将新版本放在固定目录后，重新运行安装入口更新快捷方式。
删除前先取消托盘菜单中的登录启动，再退出；随后删除两个快捷方式和程序目录。
配置仍保留在 `$CODEX_HOME/passport-console`（默认 `~/.codex/passport-console`）。

## 开发与验证

桌面外壳 `tools/passport_desktop.py` 复用本机 HTTP 后台，不在 GUI 线程中运行 BLE 或音频。
现有 Host、Origin 和令牌校验保持启用。外壳只向页面开放退出动作。

```powershell
python -m pip install -r tools/requirements-desktop.txt
python tools/passport_desktop.py
python -m unittest discover -s tests -p "test_*.py"
```

界面调试可指定 `--port 18766 --config-dir build-desktop-smoke`，与日常配置隔离。
发布脚本会检查 Windows 运行时是否包含桌面依赖；不会把开发虚拟环境打包进去。

实现参考：[pywebview API](https://pywebview.flowrl.com/api/)、
[pystray API](https://pystray.readthedocs.io/en/stable/reference.html)。
