# 局域网连接（feature/lan-connection）

此分支支持通过 Wi‑Fi 同步 Codex 用量与任务状态。设备连接 **2.4 GHz** Wi‑Fi；电脑可以通过同一路由器的网线或 Wi‑Fi 连接，无需蓝牙。宠物、任务完成提示音和自动息屏继续生效。

## 手机热点配网（推荐）

1. 设备长按确认键打开菜单，进入 **设置 → 无线网络**，再按确认键进入配网。设备会重启，暂时停止蓝牙。
2. 手机连接 **Passport Setup** 热点，密码显示在设备屏幕上，每次进入配网都会重新生成。手机提示无互联网时，选择继续使用这个网络。
3. 浏览器手动打开 **http://192.168.4.1**。点击扫描并选择 2.4 GHz 网络，也可以手动输入隐藏网络名称；填写密码并保存。此时只是保存，还没有连接路由器。
4. 点击 **下载 passport-lan.json**，确认文件已保存，再点 **已保存文件，连接 Wi-Fi**。手机配网时，把下载的文件传到台式机。
5. 设备重启，热点关闭。在 **设置 → 无线网络** 查看路由器分配的 IP。在电脑安装 `tools/requirements-lan.txt`，运行：

   ```powershell
   python tools/codex_bridge.py --lan 192.168.1.50 --lan-key-file "C:\path\passport-lan.json"
   ```

热点只在主动配网时开启，10 分钟后自动关闭；设备配网页按确认键也可立即退出。未保存时保留原网络和连接模式；保存后退出会尝试连接新网络。若一直显示 `Connecting...`，重新进入配网检查密码。换 Wi-Fi 会保留已有配对密钥，电脑无需重新配对。

本版参考 [leo0183/leo-radio](https://github.com/leo0183/leo-radio) 的热点网页流程。支持扫描、手动输入和下载配对文件；暂未移植设备按键输入密码、多网络列表或自动弹出认证页。短暂断网时继续重连，不自动开放配网热点。

也可通过 USB 打开热点：`python tools/configure_lan.py --port COM3 --setup`。

## USB 配网（备选）

1. 刷入本分支的应用固件，通过 USB 数据线连接设备。应用镜像仅写入 `0x10000`。
2. 安装本机依赖：

   ```powershell
   python -m pip install -r tools/requirements-lan.txt
   ```

3. 运行配网工具（把 COM3 换成实际端口）：

   ```powershell
   python tools/configure_lan.py --port COM3
   ```

   在本机输入 Wi‑Fi 名称和密码。密码隐藏输入；无密码网络可直接回车。支持普通开放网络和 WPA2/WPA3-Personal，不支持需要网页登录的网络或企业认证。Wi‑Fi 密码只保存到设备的 NVS，不保存到电脑配置文件，不上传 GitHub。

4. 设备重启后，在 **设置 → 无线网络** 查看 IP。也可通过 USB 查询：

   ```powershell
   python tools/configure_lan.py --port COM3 --status
   ```

5. 用设备 IP 启动桥接：

   ```powershell
   python tools/codex_bridge.py --lan 192.168.1.50
   ```

   电脑需安装并登录 Codex CLI。必要时用 `--codex` 指定实际 Codex 可执行文件。Windows 的 npm 安装可指定其 vendor 目录内的 `codex.exe`。

之后设备只需供电，USB 无需连接电脑。桥接自动重试断线，每 10 秒发送心跳。设备 IP 由路由器分配；建议在路由器设置 DHCP 地址保留，避免重启后地址改变。访客网络的客户端隔离可能阻止电脑连接设备。

## 配对文件与换电脑

设备同一时间只处理一个桥接连接。切换电脑时，先停止旧电脑上的桥接，再启动新电脑。固件会以新连接的首个完成计数建立基准，不补播历史提醒；之后的新完成事件正常触发动画和提示音。新电脑计数比旧电脑小、或本机计数被重置，都不会再被旧的累计值挡住。自动提示音仍遵循设备的声音设置及 22:00–08:00 静音时段。

配网工具在本机 `~/.codex/passport-lan.json` 保存随机生成的配对密钥，文件不包含 Wi‑Fi 密码或 Codex 登录凭据。换电脑时可自行把这个文件复制到新电脑同一位置，或用 `--lan-key-file` 指定它。也可以重新 USB 配网，生成新密钥；旧密钥随之失效。不要提交或公开配对文件。

## 切回蓝牙

```powershell
python tools/configure_lan.py --port COM3 --transport ble
# 恢复已配置的局域网：
python tools/configure_lan.py --port COM3 --transport lan
```

这会保留 Wi-Fi 和配对密钥，仅切换模式并重启。只有使用 `--disable` 才会清除 Wi-Fi 与密钥。未配网时也默认使用蓝牙；必要时在设备设置中开启蓝牙。恢复出厂设置同样清除局域网配置。

## 实现与验证范围

### 配网后重启与同步修复（2026-09-10）

首次连接路由器后，默认 2304 字节系统事件栈在 DHCP/IP 日志路径溢出，造成循环重启。已将 `CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE` 提高到 4096，并在 USB 状态增加 `uptime_s` 和 `event_stack_free`。升级应用固件即可保留已有 Wi-Fi 和配对密钥，不需要重新配网。

同时修复桥接程序把 BLE 换行分隔符带入 LAN JSON 的问题；局域网模式将整幅画布刷新限制为每秒 5 帧，避免 Wi-Fi 与画面刷新并行时导致通信任务和空闲任务得不到运行机会。

实机已验证 DHCP 获取地址、加密通信及三次 TCP 重连；持续桥接时事件栈余量约 1520 字节、空闲堆约 38 KB。主机测试为 14 项 C、16 项 Python。配网凭据和桌面配对文件均保留。

换电脑提醒修复：主机测试覆盖高计数切低计数、低计数切高计数、计数重置与重复心跳。实机模拟完成计数 50000 → 新连接 1 → 完成 2，设备确认一次音频播放（`sound_stage=5`, `sound_played=1`），运行时长持续增加。USB 状态现在也包含音频阶段和播放次数，便于区分事件遗漏与静音/音量问题。

- ESP32-C3 内存有限，因此每次启动只运行 LAN 或 BLE 中的一种传输。功能均保留，可经 USB 切换，不同时运行两个无线协议栈。
- Wi‑Fi 高速 IRAM 优化关闭，收发缓冲数量按低频同步需求收紧；网络帧缓冲仅在 LAN 模式分配，该模式同时释放未使用的蓝牙控制器预留内存。
- 设备监听 TCP 8765，仅接受一个桥接客户端。握手使用双方随机挑战和 HMAC-SHA256 验证，派生会话 nonce；随后使用 AES-256-GCM 加密、递增序号及分离的双向 nonce 防止篡改与重放。不需要互联网服务器或端口转发。
- LAN 只接受 Codex 用量心跳和时间同步，不提供远程审批、设备改名、解绑或配置指令。配网通过物理 USB，或主动进入的独立热点模式。
- 配网热点使用随机 WPA2 密码；网页接口校验会话令牌。配网期间不连接路由器、不启动 BLE 或 LAN 服务；正常使用时不启动网页服务。配对文件只通过该临时热点下载，文件不包含 Wi-Fi 密码。网页资源均来自设备本身。
- 有界消息缓冲区、超时及连接代次检查限制无效请求；UI 修改仍在应用任务内执行。
- 主机测试覆盖消息白名单、加密校验、错误密钥、篡改、重放、消息长度、TCP 分片与重连。USB 状态中的 `crypto_ok` 是设备 mbedTLS 与 Python AES-GCM 测试向量的互通自检。
- 2026-09-10 验证：14 项 C 主机测试、15 项 Python 测试通过；ESP-IDF 5.5.3 构建通过。实机验证热点启动、主动退出、USB 分片和无效配置拒绝；热点空闲堆约 41 KB，退出后 BLE 空闲堆约 33 KB。浏览器使用模拟接口验证了手机布局、密码校验、保存/下载/重启流程。
- 用户随后已完成真实热点网页配网与配对文件下载；更新固件后完成目标路由器联调。长时间浸泡及 20 次重连测试未运行。
- 用户已完成目标 Wi-Fi 配网，更新固件后验证了实际 LAN 桥接同步。提示音并发时的堆余量、路由器掉线恢复和长时间浸泡仍待单独验证；三次 TCP 重连不等于路由器掉线测试。

## English quick start

Open Settings → Wi-Fi on the Passport and press OK. Join the password-protected `Passport Setup` hotspot with your phone, open `http://192.168.4.1`, save the network, download the pairing JSON and restart. Transfer the JSON to the computer and run `python tools/codex_bridge.py --lan DEVICE_IP --lan-key-file PATH_TO_JSON`. Install `tools/requirements-lan.txt` first. Alternatively use `python tools/configure_lan.py --port COM3` over USB, which stores the key in `~/.codex/passport-lan.json`. Use `--transport ble` or `--transport lan` over USB to switch without deleting pairing. `--disable` explicitly forgets LAN settings. Wi-Fi credentials stay on the device. This branch uses one wireless transport at a time and retains the pet, chime and idle-sleep features.
