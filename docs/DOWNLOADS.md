# v0.2.5 下载与安装

**推荐普通 Windows 用户下载 [Passport-Windows-x64-v0.2.5.zip](https://github.com/gycodex/codex-passport-companion/releases/download/v0.2.5/Passport-Windows-x64-v0.2.5.zip)**，不要选页面自动生成的 Source code。

[发布页](https://github.com/gycodex/codex-passport-companion/releases/tag/v0.2.5) · [三步上手](QUICKSTART.zh_CN.md) · [版本说明](releases/v0.2.5.md)

这是预发布版，适用于 Windows 10/11 x64、FoloToy AI Passport（ESP32-C3、8 MB Flash）。

## 包内有什么

| 文件 | 用途 |
| --- | --- |
| `Passport.exe` | 双击打开电脑端，不需要 Python |
| `升级设备固件.exe` | USB 升级工具，不需要 Python 或手写刷机命令 |
| `firmware/` | 配套固件和校验信息，请保留完整目录 |
| `先读我-三步开始.md` | 首次安装、联网、配对、日常使用说明 |
| `SHA256SUMS.txt`、`notices/` | 校验值、构建来源和第三方许可 |

先完整解压到固定目录。首次安装或升级时，退出 Passport 并连接 USB，双击升级工具，核对设备后输入 FLASH。工具会验证分区、备份原应用、只更新 0x10000 应用分区并校验。不要整片擦除，也不要把应用写入 recovery 分区。

随后打开并登录 Codex，双击 Passport.exe。选择局域网，搜索设备并核对两端号码，即可自动保存配对；无需导入文件或填写 IP。详见[三步上手](QUICKSTART.zh_CN.md)。

## 系统要求与范围

- Windows 需要 Microsoft Edge WebView2 Runtime；Codex 单独安装并登录。
- 基础任务同步和完成提示音无需语音驱动。语音默认关闭，需要自己的输入法及虚拟音频驱动；豆包兼容另需 Windows 授权。
- EXE 内置可选豆包适配所需 Frida 17.18.0；不包含 Codex、输入法或虚拟音频驱动。
- 关闭窗口后仍在托盘运行；更新前从程序或托盘菜单退出。
- macOS/Linux 用户使用源码启动脚本 `bash start-console.command`，需要自行准备 Python；本版一体包仅面向 Windows x64。
- 已验证单台设备升级、任务同步与提示音播放执行；第二台电脑、20 次重连、30 分钟稳定性与缩小缓冲后的持续语音录制仍未完整验收。
- 程序未代码签名；从项目 Release 下载并核对 SHA256。第三方许可范围及待确认事项见 NOTICE。

## 从源码复现 Windows 一体包

在对应 tag 的干净工作区，使用 ESP-IDF 5.5.3 新建构建目录并执行 `idf.py -B build-release build`。再运行：

```powershell
python -m pip install -r tools/requirements-build-exe.txt
python tools/build_easy_release.py --firmware-dir build-release --idf-dir $env:IDF_PATH --output dist/release-v0.2.5
```

输出目录必须不存在。脚本检查版本一致性和干净工作区，构建两个 EXE，保留依赖许可证并生成一体 ZIP 和校验值。
