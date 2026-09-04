# 小信：Pepper × 百炼实时语音接待系统

本项目运行在**与 Pepper 同一局域网的 Windows 或 Linux 电脑**上，实现如下语音链路：

```text
"小信"唤醒 → Pepper 前方麦克风 → 百炼实时 ASR → 本地快速回答或 qwen 模型 → Pepper 中文朗读
```

机器人名称为“小信”。本地 `system_prompt.txt` 中的提示词决定接待内容；程序负责语音输入、实时识别、调用模型和朗读。

## 1. 交付内容与平台入口

将整个 `pepper_bailian_bridge/` 目录发送给使用者。Linux/WSL 部署需要隐藏目录 `.runtime/`；它是项目内置的 Linux Python 2.7 运行时。Windows 不能运行这个 Linux 运行时，必须使用 Windows Python 2.7 和 Windows 版 Pepper NAOqi SDK。

项目目录中各文件用途如下：

| 文件 | 用途 |
| --- | --- |
| `run_wake_dialog.sh` | Linux/WSL 日常启动入口 |
| `run_wake_dialog.cmd` | Windows 日常启动入口 |
| `wake_dialog.py` | 唤醒、连续会话和主流程控制 |
| `voice_dialog.py` | 百炼模型调用、流式回答与 Pepper 朗读 |
| `local_replies.json` | 无需调用大模型的现场高频问答 |
| `learned_replies.json` | 现场自动学习的问答缓存 |
| `alumni_welcome_options.json` | 校友接待会随机播报的欢迎词集合 |
| `asr_pcm_stream.py` | 百炼实时语音识别 WebSocket 客户端 |
| `pepper_pcm_stream.py` | 从 Pepper 前方麦克风获取 16 kHz PCM 音频 |
| `pepper_say.py` | 调用 Pepper 中文扬声器；朗读时默认做受限的小幅头部、肩部和肘部动作 |
| `emoji_display.py` | 提供内置 SVG 表情页面，并驱动 Pepper 胸前平板 |
| `pepper_emoji.py` | 通过 `ALTabletService` 打开表情页面 |
| `pepper_wake_word_test.py` | Pepper 内置中文唤醒词监听模块 |
| `run_pepper_*.sh`、`run_wake_word_test.sh` | Linux/WSL 内部启动脚本 |
| `run_pepper_*.cmd`、`run_wake_word_test.cmd` | Windows 内部启动脚本 |
| `.runtime/` | Linux/WSL 专用 Python 2.7 运行时；Windows 不使用 |

## 2. Windows 部署

Windows 版仍由 Python 3 运行百炼、ASR 和对话控制；只有连接 Pepper 的 `qi`/NAOqi 客户端使用 Python 2.7。请准备：

1. Pepper NAOqi SDK 2.5.x 的 Windows 版本（SDK 不包含在本项目中）；
2. 可执行的 Python 2.7（建议 32 位 Python 配合 SDK 的 32 位版本，位数必须匹配）；
3. Python 3 和 DashScope Python SDK：

   ```powershell
   py -3 -m pip install "dashscope>=1.25.17"
   ```

在 PowerShell 中设置本机路径和 Pepper IP。路径请改成实际安装位置：

```powershell
$env:PEPPER_SDK_ROOT = "C:\path\to\pynaoqi-python2.7-2.5.7.1-win64"
$env:PEPPER_PYTHON = "C:\Python27\python.exe"
$env:PEPPER_PYTHON3 = "C:\Python311\python.exe"
$env:PEPPER_ROBOT_IP = "192.168.0.100"
$env:DASHSCOPE_API_KEY = "请在本机自行填写"
$env:BAILIAN_API_BASE_URL = "https://<业务空间>.cn-beijing.maas.aliyuncs.com/api/v1"
```

本机 Windows 环境约定已经配置为：Pepper 地址为 `192.168.0.100:9559`，电脑 WLAN 地址为 `192.168.0.101`；`NAOQI_SDK_ROOT` 指向
`C:\Users\朱航\Documents\Codex\2026-09-04\windows-windoes-naoqi-pepper\runtime\pynaoqi-python2.7-2.5.5.5-win32-vs2013`，
Python 2.7 使用 Conda 的 `py27` 环境，即 `%UserProfile%\.conda\envs\py27\python.exe`。
项目中的所有 Windows Pepper 启动脚本都会优先读取 `PEPPER_SDK_ROOT`，其次读取 `NAOQI_SDK_ROOT`，
最后才使用项目旁边的默认 SDK 路径；Python 2.7 会优先自动选择 `%UserProfile%\.conda\envs\py27\python.exe`。
因此日常不需要重复填写 SDK 或 Python 2.7 路径。

`PEPPER_PYTHON` 必须指向 Python 2.7，`PEPPER_PYTHON3` 必须指向 Python 3；不要把两个环境混用。启动：

如果当前 PowerShell 窗口早于环境变量配置，可重新打开一个 PowerShell 窗口；Windows 启动脚本也会从当前用户环境注册表补读 `NAOQI_SDK_ROOT`，避免因为旧窗口没有刷新而重复询问。当前 WLAN 如果被 Windows 标记为 Public，必须用管理员 PowerShell 执行 `.\setup_windows_firewall.ps1 -RobotIp 192.168.0.100`，放行 TCP `54000`、`54001`、`54002`；否则 Pepper 能连接 NAOqi，但不能加载胸前平板页面。`PEPPER_PYTHON3` 建议明确设置为安装了 DashScope 的 Python 3；未设置时脚本会优先尝试 Conda base。

```powershell
Set-Location "C:\path\to\pepper_bailian_bridge"
.\run_wake_dialog.cmd
```

如果 Pepper 无法连接 Windows 上的回调端口，请以管理员身份执行一次：

```powershell
.\setup_windows_firewall.ps1 -RobotIp 192.168.0.100
```

Windows 不需要执行 `start_in_wsl.sh`、`setup_wsl_firewall.ps1`，也不需要配置 `.wslconfig`。Windows 主机的网络适配器必须与 Pepper 位于同一局域网，且 Pepper 能访问本机 TCP `54000`、`54001`、`54002`。

自动语音对话启动后，程序默认每 2～3 分钟随机播放一次 `alumni_welcome_options.json` 中的 7 段校友欢迎词，并尽量避免连续播放同一段。自动播报线程独立运行，因此 Pepper 在“小信”唤醒等待状态时也会继续播报；进入语音对话期间若恰好到点也可能播报。以后可直接在这个 JSON 数组中继续添加字符串，新增文本会自动参与随机播放。若临时关闭自动播报，可使用：

```powershell
.\run_wake_dialog.cmd --no-periodic-greeting
```

也可以通过 `--greeting-file` 指定其他文本文件或 JSON 文本数组，并用 `--greeting-minutes`、`--greeting-max-minutes` 调整间隔；两个参数相同即可固定间隔。

## 3. Linux/WSL 目标电脑的前置条件

### 操作系统与网络

- Linux x86_64 电脑；本项目随附的 `.runtime` 为 Linux x86_64 Python 2.7 运行时。
- 电脑与 Pepper 位于同一局域网，能够访问 Pepper 的 NAOqi 端口 `9559`。
- Pepper 能够反向访问电脑的 TCP `54000`、`54001` 和 `54002`。前两个端口用于实时麦克风回调和唤醒词事件，`54002` 用于胸前平板加载内置 SVG 表情页面。
- Pepper 已启用中文语音包，且系统中 `ALSpeechRecognition` 支持 Chinese。

### WSL2 必须使用镜像网络

`ALAudioDevice` 不是普通的“电脑请求机器人”接口：订阅后由 Pepper 主动调用电脑上的
`processRemote` 服务发送 PCM。WSL2 默认 NAT 地址（通常为 `172.x.x.x`）不能被局域网内的
Pepper 主动访问，因此会表现为唤醒和朗读正常、麦克风订阅一直超时。

Windows 11 22H2 及以上请在 Windows PowerShell 中执行：

```powershell
notepad $env:USERPROFILE\.wslconfig
```

写入并保存：

```ini
[wsl2]
networkingMode=mirrored
```

然后在 PowerShell 中关闭所有 WSL 实例：

```powershell
wsl --shutdown
```

以管理员身份打开 PowerShell，仅放行本项目需要的 Hyper-V 入站端口：

```powershell
New-NetFirewallHyperVRule `
  -Name "Pepper-NAOqi-Callbacks" `
  -DisplayName "Pepper NAOqi callbacks" `
  -Direction Inbound `
  -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' `
  -Protocol TCP `
  -LocalPorts 54000,54001,54002
```

重新进入 WSL 后，`ip -brief address` 应显示与 Pepper 同网段的 `192.168.1.x` 地址。
程序启动时也会自动拦截不兼容的 WSL2 NAT 配置，避免再把网络问题误报成音频占用。

### 必需软件

1. **Pepper NAOqi Python SDK 2.5.x**

   SDK 不包含在本项目中。请将官方 SDK 解压到目标电脑，并记住其绝对路径。例如：

   ```bash
   /opt/pynaoqi-python2.7-2.5.7.1-linux64
   ```

2. **Python 3 与 DashScope Python SDK**

   ```bash
   python3 -m pip install 'dashscope>=1.25.17'
   ```

3. **百炼资源**

   - 同一业务空间的 DashScope API Key；
   - 与该 Key 配套的 DashScope Base URL，格式为 `https://<业务空间>.cn-beijing.maas.aliyuncs.com/api/v1`；
   - 业务空间已开通 `qwen-flash`（或所选低延迟模型）与 `qwen-audio-3.0-asr-flash-streaming`。

## 4. 首次部署

假设项目被放在 `/opt/pepper_bailian_bridge`，SDK 位于 `/opt/pynaoqi-python2.7-2.5.7.1-linux64`：

```bash
cd /opt/pepper_bailian_bridge
chmod +x run_*.sh

export PEPPER_SDK_ROOT=/opt/pynaoqi-python2.7-2.5.7.1-linux64
export PEPPER_ROBOT_IP=192.168.0.100
```

请把 `PEPPER_ROBOT_IP` 改为实际 Pepper IP。下面命令可检查 NAOqi 网络连通性：

```bash
nc -zv "$PEPPER_ROBOT_IP" 9559
```

如果电脑使用 UFW 防火墙，应只允许 Pepper IP 访问必要端口：

```bash
sudo ufw allow from "$PEPPER_ROBOT_IP" to any port 54000 proto tcp
sudo ufw allow from "$PEPPER_ROBOT_IP" to any port 54001 proto tcp
sudo ufw allow from "$PEPPER_ROBOT_IP" to any port 54002 proto tcp
```

## 5. 启动与使用

日常只需运行下面一个入口：

```bash
cd /opt/pepper_bailian_bridge
./run_wake_dialog.sh
```

程序会在本地终端依次要求输入：

1. `DASHSCOPE_API_KEY`（输入不回显，不会写入文件）；
2. DashScope Base URL（必须以 `/api/v1` 结尾）。

也可在启动前以环境变量配置，避免重复输入：

```bash
export DASHSCOPE_API_KEY='请在本机自行填写'
export BAILIAN_API_BASE_URL='https://<业务空间>.cn-beijing.maas.aliyuncs.com/api/v1'
./run_wake_dialog.sh
```

使用流程：

1. 对 Pepper 说一次“**小信**”；
2. Pepper 说“我在，请说”后，直接说问题；
3. 说完后停顿约 0.6 秒，系统自动提交；
4. Pepper 朗读回答后，您可继续追问，无需再次唤醒；
5. 约 6 秒未听到新问题时，系统回到“小信”唤醒等待状态；
6. 在终端按 `Ctrl+C` 退出。

终端中 `识别中>` 表示实时 ASR 正在返回转写文本；`您>` 是最终识别结果；`Pepper>` 是百炼应用最终回答。

### 胸前平板表情

默认启动时会在胸前平板打开内置 SVG 表情页面，不需要下载 emoji 字体或图片。内置表情包括：微笑待机、聆听、思考、开心、眨眼、兴奋、星星、爱心、玫瑰花、挥手告别和异常提示。普通回答会轮换可爱表情，问候优先显示爱心，感谢优先显示玫瑰花。平板页面由电脑的 TCP `54002` 端口提供，因此首次启用功能前请重新执行对应的防火墙脚本。

表情显示支持两条通道。平板 Wi-Fi 为 `CONNECTED` 时，优先从电脑 `192.168.0.101:54002` 加载页面；平板 Wi-Fi 为 `DISCONNECTED` 或电脑页面不可达时，程序会自动打开 Pepper 自带的 `198.18.0.1` 内部页面，并通过 `executeJS` 注入完整 SVG。离线兜底不依赖现场 Wi-Fi、电脑入站端口、SSH 或外部图片资源。表情页面只初始化一次，后续状态切换只更新页面中的 SVG 容器；Python 2.7 NAOqi 客户端也会保持为一个常驻 worker，避免每次循环重新连接 Pepper 导致平板闪烁。

如果电脑有多个网卡，自动识别的地址不适合 Pepper 访问，可显式指定电脑在机器人所在局域网的地址：

```powershell
.\run_wake_dialog.cmd --display-host 192.168.1.20
```

临时关闭胸前平板表情：

```powershell
.\run_wake_dialog.cmd --no-emoji
```

### 说话时的小幅动作

Pepper 朗读时会从左手抬起、右手抬起和双手小幅展开中随机选择动作，每次完整执行“抬起、短暂停留、平滑放下、休息”，而不是让各关节持续转圈。抬手主要由肩部前抬完成，只搭配少量肩部外展和屈肘；单手最大前抬约 28 度。说话动作不控制头部，让 Pepper 保持面向听众，也不会与独立的人脸跟踪功能争抢头部控制。程序不会调用髋部、膝盖、脚踝、轮子或底盘控制，因此不会因为说话动作触发行走或下肢移动。多段语音也会串行播放，避免两个朗读任务同时驱动机器人。

如果现场需要完全静止的姿态，可在启动时关闭：

```powershell
.\run_wake_dialog.cmd --no-motion
```

直接调用 `run_pepper_say.cmd` 或 `run_pepper_say.sh` 时也支持 `--no-motion`。动作目标每秒连续更新约 20 次，动作线程异常不会影响语音朗读。

## 6. 百炼模型配置

默认直接调用 DashScope qwen 模型（`qwen-flash`，低延迟），不经过 Agent 应用，系统提示词从本地 `system_prompt.txt` 读取。请在部署前编辑该文件，填入“小信”的身份与活动介绍。

如需切换模型或提示词文件，可设置环境变量或启动参数：

```bash
export BAILIAN_LLM_MODEL='qwen-flash'            # 可选：qwen-flash / qwen3-flash / qwen-turbo
export BAILIAN_SYSTEM_PROMPT_FILE='/opt/pepper_bailian_bridge/system_prompt.txt'
./run_wake_dialog.sh --llm-model qwen-flash
```

如果仍要使用百炼控制台发布的 Agent 应用（模型和提示词都在控制台维护），加 `--use-agent`：

```bash
./run_wake_dialog.sh --use-agent
```

Agent 应用路径下默认应用 ID 写在 `voice_dialog.py`，可用 `BAILIAN_APP_ID` 覆盖；对应提示词请在百炼控制台应用配置中维护并发布。

### 本地快速回答

“你好”“你是谁”“几点了”“今天星期几”“谢谢”“再见”等短问题会在本地直接回答，
不会调用 qwen 或 Agent。语音转文字仍需使用实时 ASR。

现场高频问答可直接编辑 `local_replies.json`，左侧是可能识别出的完整问题，右侧是 Pepper 的回答：

```json
{
  "活动几点开始": "活动上午九点开始。",
  "活动在哪里": "活动在一楼报告厅举行。",
  "洗手间在哪里": "洗手间在大厅右侧。"
}
```

这是精确短句匹配，会自动忽略空格和常见标点。相同意思但说法不同，需要分别添加一项；
未命中的问题会自动交给百炼。

百炼成功回答后，程序会把本次问题和回答自动写入 `learned_replies.json`。下一次识别到同样的问题时，会直接使用本地缓存回答，不再调用 qwen 或 Agent。`local_replies.json` 的人工话术优先级更高，适合放标准迎宾词；`learned_replies.json` 适合活动现场自动积累。

若要临时关闭所有本地回答，可用：

```bash
./run_wake_dialog.sh --no-local-replies
```

若只想关闭自动学习，但保留人工话术，可用：

```bash
./run_wake_dialog.sh --no-learned-replies
```

## 7. 可调参数

通常无需修改。若现场噪声或说话习惯不同，可在启动命令后添加参数：

```bash
./run_wake_dialog.sh \
  --silence-seconds 0.7 \
  --start-threshold 300 \
  --silence-threshold 400 \
  --start-timeout 8 \
  --max-seconds 20
```

| 参数 | 默认值 | 作用 |
| --- | ---: | --- |
| `--wake-word` | `小信` | 唤醒词 |
| `--confidence` | `0.10` | 唤醒置信度阈值；越低越容易唤醒但更容易误唤醒；现场误唤醒较多时可调高 |
| `--silence-seconds` | `0.45` | 用户停顿多久后判定说完；为降低短问句延迟而缩短；若常截断句子可增至 `0.6`～`0.8` |
  | `--start-threshold` | `480` | 开始说话的音量阈值；现场很吵时适当调高 |
| `--silence-threshold` | `400` | 高于此音量视为仍在说话；现场底噪较大时应提高该值 |
| `--start-timeout` | `6` | Pepper 提示后等待用户开始说话的秒数 |
| `--max-seconds` | `15` | 单个问题允许的最长录音时长 |

默认起声阈值已调为 `480`，用于减少环境声误触发；默认静音判定为 `0.45` 秒，以缩短短问句的提交等待。识别结果为空或只有一个字符时会直接忽略，不会调用百炼或让 Pepper 回复。若发现用户在一句话中的短暂停顿被误判为结束，再将 `--silence-seconds` 调回 `0.6`。

## 8. 常见问题

### `InvalidApiKey` 或 HTTP 401

API Key 与 Base URL 不属于同一业务空间。请在百炼 API Key 页面重新复制该 Key 对应的 **DashScope** 地址；不要使用“OpenAI 兼容地址”。

### `未收到音频数据`、实时识别没有文字

检查以下项目：

1. Pepper IP 是否正确，`nc -zv <Pepper_IP> 9559` 是否成功；
2. Pepper 是否能访问电脑 TCP 54000、54001 和 54002；
3. 防火墙是否放行了来自 Pepper IP 的这两个端口；
4. 是否在 Pepper 正前方、距离约 0.5 至 1.5 米处正常说话；
5. Pepper 是否已启用中文语音与中文识别语言包。

### 说完后太快提交或一直不提交

- 回答被截断：提高 `--silence-seconds`，例如改为 `0.7`；
- 一直不提交：提高 `--silence-threshold`，例如改为 `300`；
- 很难开始收音：降低 `--start-threshold`，例如改为 `220`。

### `Too many requests` 或 `system capacity limits`

这是百炼实时 ASR 的服务端限流，通常不是 Pepper 或防火墙故障。程序会先等待 Pepper 本地 VAD 检测到确实有人声，再创建云端 ASR 请求；如果本轮发生限流，会保留已录到的语音并自动按 1.5 秒、3 秒重试，重试成功后继续对话；连续失败才会暂停 15 秒并回到唤醒等待。请确认只运行一个 `run_wake_dialog.cmd`，必要时等待几十秒后再试。

### Pepper 不说话

确认 Pepper 已安装中文语音包；再检查 `PEPPER_SDK_ROOT` 是否指向正确的官方 SDK 目录，并确认 NAOqi 端口 `9559` 可访问。

## 9. 安全注意事项

- 不要把 API Key、SSH 密码或 sudo 密码写入代码、README、截图或仓库。
- 如果密钥曾被公开发送或截图展示，请立即在百炼控制台禁用并重新创建。
- 本项目不保存 API Key；使用环境变量时，请避免把包含密钥的终端历史或配置文件提交到仓库。
