# Lux Ubuntu 24.04 实验交接说明

更新日期：2026-09-22

## 0. 给接手会话的任务

用户要在另一台/另一个会话中的 **物理 Ubuntu 24.04** 环境验证 Lux 项目。
请先完整阅读本文件，再检查仓库的实时状态。你的任务不是只给命令，而是：

1. 在真实 Ubuntu 24.04 桌面环境安装并运行项目。
2. 验证 GUI、摄像头、MediaPipe、麦克风、扬声器、PyBullet、Whisper、Kokoro 和 GPT 交互。
3. 记录安装问题、修复、测试输出、硬件信息和真实测量结果。
4. 发现 Linux 兼容性问题时，在当前项目范围内修复并回归测试。
5. 只有实际测试通过后，才能把文档中的 “Ubuntu 未验证” 改为 “已验证”。

严禁根据 Windows 结果推断 Linux 已通过，也不要编造截图、测试次数、延迟或资源数据。

## 1. 项目位置和仓库状态

- 项目名称：Lux: Live Lamp Character
- GitHub：<https://github.com/33Geniusss/lux-lamp-character>
- Windows 本地项目：`D:\Study\SWCVChallenge`
- 不要误用相邻的 `D:\Study\MLChallenge`；那是另一个 challenge。
- `94d4e77` (`Add full application resource benchmark`) 是本轮 Linux 兼容性工作之前的
  基线提交。开始实验前应执行 `git pull`，并以远程 `main` 的最新提交为准。
- 当前仓库版本应包含 WSL2 摄像头/音频支持、原生 Ubuntu 安装指南，以及修正后的
  Technical Note。该 Note 修正了 GPT 上下文、动作循环、线程所有权和 JSON 提交顺序。
  如果克隆结果缺少这些文件或内容，先确认当前分支与远程同步，不要用旧 PDF 覆盖它。

开始工作时必须先运行：

```bash
pwd
git status --short
git branch --show-current
git log -3 --oneline
git remote -v
```

保留用户已有修改。不要使用 `git reset --hard`、`git clean -fd` 或其他破坏性命令。

## 2. Challenge 和交付要求

项目依据：

- `CHALLENGE.md`
- `SUBMISSION.md`
- `SW_CV Challenge.pdf`

目标是在提供的五自由度灯形机器人 URDF 上构建一个连贯的角色体验。完整演示应覆盖：

- Engagement / disengagement
- 动作、灯光、语音、音效和音乐的角色化响应
- 麦克风输入和扬声器回复
- 摄像头场景记忆及之后的语音回忆
- 由语言目标和实时视觉共同决定的目标驱动动作

目标机器：Ubuntu 24.04 LTS、4 CPU cores、8 GB RAM、无 CUDA、摄像头、麦克风、
扬声器和 Wi-Fi。项目可以使用云端 GPT，但必须说明发送的数据及本地/云端边界。

最终材料包括源码、依赖、Ubuntu 安装/运行说明，以及不超过两页的 Technical Note。

## 3. 当前实现架构

当前跟踪的最终 variant：

- STT：本地 `faster-whisper` + Whisper Small，CPU `int8`
- Language/Vision：OpenAI Responses API，当前默认模型 `gpt-5.6-luna`
- TTS：本地 `hexgrad/Kokoro-82M`，默认 voice `af_heart`
- GUI：PySide6
- 机器人仿真：PyBullet CPU TinyRenderer
- Engagement：MediaPipe Face Landmarker
- 摄像头：OpenCV
- 音频输入/输出：SoundDevice / PortAudio

只有 GPT 文字与视觉推理需要 `OPENAI_API_KEY`；麦克风音频不会上传。每次 GPT 请求会
发送语音转录文本、低清摄像头图片和完整 session JSON；同一回合的后续观察还会发送
`decision_history`。请求使用 `store=False`。

### 会话记忆

- 文件：`data/session_memory.json`（已被 `.gitignore` 忽略）
- 每次程序启动会清空旧会话并创建新的 `session_id`。
- 内容包括 `conversation_summary`、最多 20 条 `scene_memories`、`turn_count` 等。
- GPT 返回完整 `updated_memory`，Pydantic 负责结构校验。
- 应用保留自己控制的 metadata，只接受与当前 `observation_id` 对应的视觉记忆。
- 只有完整回合最终结果才通过临时文件和 `os.replace()` 原子提交。
- 中间 planning reply 和 proposed memory 不朗读、不落盘。

### GPT 动作协议

结构化返回：

```text
reply
motion_labels                 # 0 或 1 个
request_another_observation   # boolean
updated_memory
```

GPT 可选择的动作只有：

```text
inspect_left
inspect_right
nod_yes
shake_no
```

GPT 不输出关节角度。应用再次执行白名单和单动作校验，再把标签映射到固定 PyBullet
关键帧。

- `request_another_observation=true`：执行所选动作（也可以无动作），等待动作结束后的
  新摄像头帧，再调用 GPT。
- `false`：规范化并原子提交 memory，执行最终动作，生成并播放语音，播放结束后重新
  进入 Listening。
- 每个用户回合最多三张摄像头图片。
- 无效 schema、未知/多动作、超出观察次数的请求会 fail closed，不修改旧 JSON。

### 关键状态行为

- 看向摄像头约 0.7 秒后进入 engagement。
- 连续不朝向摄像头 3 秒后才 disengage。
- Think/Answer 和完整语音播放期间 engagement 被锁定，不会中断当前回合。
- Listening 阶段没有提示音，但机器人有轻微摇摆。
- Greeting 阶段会等待 greeting 音效播放完整。
- 用户开始说话后，连续静音 2 秒才提交给 Whisper。
- 每一次等待 GPT（首次、二次或三次观察）都显示 Think 状态。

## 4. Windows 已验证基线（不可冒充 Linux 结果）

Windows 开发机：AMD Ryzen 9 8945HX，16C/32T，31.8 GiB RAM。

- 自动化测试：67/67 通过。
- 真实摄像头 engagement：30 次看向 + 30 次转开，60/60 成功。
- Warm STT 平均：4.7 s，n=30。
- Warm TTS 平均：2.6 s，n=30。
- GPT 首次请求平均：8.2 s，n=30。
- GPT 后续请求平均：2.7 s，n=30。
- Cold local model latency 平均：30.0 s，n=30。
- 完整程序 90 秒资源 profile（未执行 GPT 回合）：
  - 内存峰值 2.01 GiB
  - 稳态平均内存 1.56 GiB（45-90 s）
  - CPU 稳态平均 1.68 core-equivalents
  - CPU 峰值 5.35 core-equivalents

这些数字只用于对比。Linux 必须单独测量并标记硬件、样本数和测量范围。

## 5. Ubuntu 实验流程

### A. 记录真实测试环境

先创建一个不会提交密钥的日志目录：

```bash
mkdir -p tmp/linux-validation
{
  date -Is
  uname -a
  lsb_release -a 2>/dev/null || cat /etc/os-release
  lscpu
  free -h
  df -h .
  printf 'DISPLAY=%s\nWAYLAND_DISPLAY=%s\nXDG_SESSION_TYPE=%s\n' \
    "${DISPLAY-}" "${WAYLAND_DISPLAY-}" "${XDG_SESSION_TYPE-}"
  ls -l /dev/video* 2>/dev/null || true
} | tee tmp/linux-validation/system-info.txt
```

如果 `arecord`、`aplay`、`v4l2-ctl` 或 `pactl` 不存在，可仅为诊断安装：

```bash
sudo apt-get update
sudo apt-get install -y alsa-utils v4l-utils pulseaudio-utils
```

然后记录：

```bash
{
  arecord -l || true
  aplay -l || true
  pactl info || true
  pactl list short sources || true
  pactl list short sinks || true
  v4l2-ctl --list-devices || true
} | tee tmp/linux-validation/devices.txt
```

### B. 从干净环境验证一键安装

优先在物理 Ubuntu 桌面运行，不要把 WSL/headless 成功报告成物理硬件成功。

```bash
bash setup.sh 2>&1 | tee tmp/linux-validation/setup.log
```

安装脚本应该：

1. 安装 Qt/XCB、OpenGL/EGL、PortAudio 和 eSpeak NG 等系统库。
2. 使用现有 Conda，或把 Miniforge 安装到 `.tools/miniforge3`。
3. 从 `environment.yml` 创建 `.conda-env`（Python 3.11）。
4. 下载并预热 Whisper Small 和 Kokoro-82M。
5. 运行自动化测试和 PyBullet smoke test。

如果失败，保存完整日志，定位根因后做最小修复，并从干净/可复现状态重新运行。
不要只执行一次临时 `pip install` 后就声称一键安装通过；必要依赖必须写回安装声明。

### C. 已知的打包检查点

当前 `requirements.txt` 包含 `psutil>=7,<8`，但 `setup.sh` 实际读取的
`environment.yml` 还没有 `psutil`。因此 Linux 端运行
`scripts/benchmark_full_app.py` 前很可能缺包。

正确处理方式：确认问题后，把 `psutil>=7,<8` 加入 `environment.yml` 的 pip 列表，
重新运行 `bash setup.sh`，再验证 benchmark；不要只把它作为未记录的机器级依赖。

`scripts/benchmark_full_app.py` 的 `excludes` 说明目前硬编码为
“OPENAI_API_KEY was not present”。如果 Linux 测试设置了 API key，这个字段可能不准确。
在使用结果前应修正脚本，使输出明确记录：是否配置 key、是否实际执行成功 GPT 回合、
本次 profile 包含哪些人工交互。

### D. 自动检查

```bash
./.conda-env/bin/python -m unittest discover -s tests -v \
  2>&1 | tee tmp/linux-validation/unit-tests.log

./.conda-env/bin/python run.py --smoke-test \
  2>&1 | tee tmp/linux-validation/pybullet-smoke.log

./.conda-env/bin/python run.py --camera-smoke-test \
  2>&1 | tee tmp/linux-validation/camera-smoke.log

./.conda-env/bin/python run.py --speech-smoke-test \
  2>&1 | tee tmp/linux-validation/speech-smoke.log

QT_QPA_PLATFORM=offscreen ./.conda-env/bin/python run.py \
  --screenshot tmp/linux-validation/motion-studio.png \
  2>&1 | tee tmp/linux-validation/offscreen-screenshot.log
```

对生成的 PNG 做实际视觉检查，不能只确认文件存在。

### E. 配置 API key 并运行完整 GUI

不要把 key 写入 Markdown、日志、截图、Git 或 `.env`：

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY && echo
export OPENAI_API_KEY
./.conda-env/bin/python run.py
```

等待界面显示 `READY · LOCAL MODELS`。检查：

- PyBullet 灯形机器人画面清晰且主窗口布局正常。
- 摄像头小窗正常，真实脸部状态会更新。
- Greeting 音效不会被提前截断。
- Listening 没有提示音，机器人轻微摇摆。
- 说完后必须连续静音约 2 秒才提交。
- Whisper 转录正确，GPT 等待期间保持 Think。
- 回复音频完全播放后才重新 Listening。
- 思考/回答期间即使用户转开，当前回合也不会被 disengagement 中断。
- 转开超过约 3 秒后，在空闲/可转换状态进入 disengagement。

### F. 端到端场景测试

将一个绿色杯子放在摄像头画面左侧，面对摄像头并说：

```text
Look toward the green cup on the left side of your camera view. If you can see
it, nod, and remember its color and location.
```

预期流程：

1. 第一次 GPT 返回 `inspect_left`，且 `request_another_observation=true`。
2. 软件执行左看动作后等待一个更新的摄像头帧。
3. 第二次 GPT 根据新画面返回 `nod_yes` 或 `shake_no`；通常结束观察循环。
4. 只朗读最终回复；第一条 planning reply 不朗读、不写入 memory。
5. 成功识别并被要求记忆时，最终 JSON 增加当前 observation ID 的场景记忆。

随后问：

```text
What object did I ask you to remember, and where was it?
```

确认回复来自 session memory。再检查 `data/session_memory.json` 的字段与内容，但不要把
包含私人信息的真实对话提交到 Git。

还应测试以下分支：

- 目标不可见：最终诚实返回并执行 `shake_no`，不虚构物体。
- 新画面仍不足：选择另一个有意义的单一动作，再观察一次。
- 第三张画面后不允许继续请求第四次观察。
- 关闭并重启应用后，旧 session memory 被清空。
- 断网或无效模型输出时，旧 JSON 保持不变，界面进入安全 fallback。

### G. Linux 资源测量

先确保项目环境已经包含 `psutil`。运行：

```bash
./.conda-env/bin/python scripts/benchmark_full_app.py \
  --duration 90 \
  --steady-after 45 \
  --interval 0.5 \
  --output tmp/linux-validation/full-app-resources.json
```

该脚本会打开完整 GUI 约 90 秒并自动关闭。记录测试期间是否进行了 GPT 对话；不要把
“GUI 空闲 profile”和“完整对话 profile”混为一谈。如果要测含 GPT 的端到端响应，至少
分别记录：

- 2 秒 endpoint silence
- STT
- GPT 首次调用
- GPT 后续观察调用
- TTS 生成
- 实际语音播放完成

报告样本数、均值，并在可能时记录 median/P95。网络服务延迟和本地 CPU/RAM 必须分开。

## 6. 设备选择与常见问题

列出 SoundDevice 设备：

```bash
./.conda-env/bin/python -c 'import sounddevice as sd; print(sd.query_devices())'
```

指定设备：

```bash
./.conda-env/bin/python run.py --camera-index 1
./.conda-env/bin/python run.py --audio-device 2 --audio-output-device 4
```

可用降级模式：

```bash
./.conda-env/bin/python run.py --no-llm
./.conda-env/bin/python run.py --local-voice
./.conda-env/bin/python run.py --no-character-audio
./.conda-env/bin/python run.py --no-camera --no-speech --no-llm
```

常见问题：

- Qt `xcb` plugin 错误：确认运行在图形桌面中并重新执行 `setup.sh`；记录
  `DISPLAY`、`WAYLAND_DISPLAY` 和 `XDG_SESSION_TYPE`。
- 摄像头打不开：关闭占用程序，检查 `/dev/video*`，尝试其它 camera index；必要时
  把用户加入 `video` 组并重新登录。
- 麦克风/扬声器错误：先在 Ubuntu Settings -> Sound 中确认，再用 SoundDevice index。
- Hugging Face 下载失败：确认能访问 Hugging Face；HF token 只用于下载限流优化，
  不要提交 token。
- 8 GB 内存：关闭浏览器等大型程序，不要同时运行 preload、测试和 GUI。
- Wayland 特有问题：先记录默认 Wayland 结果，再尝试 `QT_QPA_PLATFORM=xcb`；不要只
  报告 fallback 结果。

## 7. 关键代码入口

- `run.py`：应用入口
- `src/lamp_character/app.py`：GUI、状态机、worker 协调、动作后新帧采集
- `src/lamp_character/language.py`：GPT prompt、结构化返回、二/三次观察循环
- `src/lamp_character/memory.py`：Pydantic memory、observation ID 过滤、原子替换
- `src/lamp_character/actions.py`：动作白名单、固定关键帧、URDF 硬限制
- `src/lamp_character/speech.py`：Whisper、Kokoro、2 秒静音 endpoint
- `src/lamp_character/engagement.py`：0.7 秒进入 / 3 秒退出 engagement
- `src/lamp_character/simulator.py`：PyBullet 与 CPU rendering
- `src/lamp_character/audio.py`：本地音乐和音效
- `scripts/preload_models.py`：模型预下载和 TTS warm-up
- `scripts/benchmark_full_app.py`：完整程序进程树 CPU/RAM profile
- `setup.sh`、`environment.yml`：Ubuntu 安装入口和实际依赖来源
- `docs/INSTALL_NATIVE_UBUNTU.md`：面向物理 Ubuntu 24.04 的安装指南
- `docs/INSTALL_UBUNTU.md`：面向 Windows 11 WSL2 Ubuntu 24.04 的安装指南
- `scripts/build_technical_note.py`：Technical Note 生成器
- `output/pdf/TECHNICAL_NOTE.pdf`：最终两页技术说明

## 8. 完成条件与交付记录

Linux 实验结束时，至少向用户报告：

1. Ubuntu 版本、kernel、桌面协议、CPU、RAM、摄像头和音频设备。
2. `setup.sh` 是否在干净环境一次成功；若失败，原始错误和最终修复。
3. 自动测试数量与结果。
4. PyBullet、摄像头、麦克风、扬声器和可见 GUI 的实际结果。
5. 端到端场景测试每一步的可观察行为。
6. Linux STT/GPT/TTS 延迟和完整程序 CPU/RAM，连同样本数与测量范围。
7. 与 Windows 基线的差异。
8. 仍未解决的问题和复现命令。

建议把真实结果写入新的 `docs/LINUX_TEST_RESULTS.md`。更新 README 或 Technical Note
前先核对代码与数据；Technical Note 必须保持不超过两页，并重新生成、提取文字、渲染
每一页做视觉检查。

除非用户明确要求，不要自行推送 GitHub。提交前确认没有 API key、模型缓存、
`session_memory.json`、私人摄像头图片、原始录音或不应公开的日志。
