# 部署唱歌服务

**本地一体化**是在同一台电脑运行 MaiBot 和 GPU 服务；**跨机器**是在有 GPU 的电脑运行服务，由另一台机器的 MaiBot 通过网络连接。两种方式都需要用户自行准备有权使用的音色模型。

插件市场的一键安装只把插件安装到 MaiBot 所在机器，不会自动在 GPU 电脑部署服务。项目发布后，跨机器用户需在 GPU 电脑从 [GitHub 仓库](https://github.com/real-Elysia886/sing)下载发布版本源码包，解压后运行包内的 `server/install_windows.bat`；同机用户可以运行插件目录中的同一安装器。安装器不会启动或修改 MaiBot，也不会自动连接 EasyTier。

## 1. 安装前准备

- NVIDIA 显卡、驱动和充足显存；已在 RTX 4070 Laptop 上做过单机测试，其他显卡和实际显存需求尚未完成兼容性测试。
- Windows 安装器会为 GPU 端准备 Python、Node.js、FFmpeg 和 PyTorch CUDA 环境；手动安装时需自行准备。MaiBot 端使用其自身的 Python，不要求两端共用环境。
- 测试过的推理环境使用 Python 3.9、`rvc-python==0.1.5`、NumPy 1.23.x 和 GPT-SoVITS 的 UVR5 代码。安装器已在本机隔离环境运行；另一台全新 Windows 电脑和 Linux 安装仍需进一步验证。
- 参照[模型准备](../server/models/README.md)获取有权使用的 RVC 音色模型；Windows 安装器会准备基础模型和 UVR5 代码。

## 2. Windows 安装器（验证中）

在 64 位 Windows NVIDIA GPU 电脑上，双击 `server/install_windows.bat`。安装器尝试自动准备独立 Python 3.9、CUDA 版 PyTorch、UVR5 代码、RMVPE/HuBERT/HP5 基础模型、Node.js 依赖和 FFmpeg，然后让你选择有权使用的 **RVC v2** `.pth` 音色模型与可选的 `.index`。GPT-SoVITS 的 TTS 模型不是 RVC 唱歌音色模型，不能直接选用；本项目不替你下载或分发角色模型。

安装器使用 `server/.runtime`、`server/.venv` 和本地 `settings.json`，不会修改现有 GPT-SoVITS 环境；已有 `settings.json` 不会覆盖。请预留至少 15 GB 空间并保持网络畅通。下载依赖较大，可能耗时；Windows 防火墙或代理可能影响下载。PyTorch CUDA 11.8 构建不保证支持所有较新 GPU，驱动和显卡须兼容。

安装器会从项目的 `v1.2.0` Release 下载并校验 Windows x64 / Python 3.9 的 Fairseq 预编译包，避免在用户机器编译；来源和校验值见[第三方组件说明](fairseq-build.md)。预编译包已在隔离环境验证安装与导入，但尚未在另一台没有 C++ 工具的全新 Windows 上验证完整流程。

安装器不会启动服务，也不会读取或填写任何网易云凭据。完成后参见下文的“启动并连接”；跨机器运行请阅读 [EasyTier 教程](easytier.md)。

## 3. 手动准备服务端依赖

在 GPU 电脑获得本仓库并进入 `server`。建议创建独立虚拟环境，避免改变其他生产服务的依赖。Windows 示例：

```powershell
cd 路径\sing\server
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm install
```

Linux 可使用 `python3.9 -m venv .venv`、`source .venv/bin/activate`，然后执行相同的 pip 和 npm 命令。确保安装的 PyTorch 与显卡、驱动及 Python 环境兼容；按 [PyTorch 官方安装指南](https://pytorch.org/get-started/locally/)选择 CUDA 构建。安装后执行 `python -c "import torch; print(torch.cuda.is_available())"`；如输出 `False`，先检查 CUDA 环境。

`rvc-python` 和 GPT-SoVITS UVR5 有额外依赖与版本约束；安装失败时不要修改已有生产环境来强行解决，应在独立环境中排查。`npm install` 安装歌曲检索所需 Node 依赖。

## 4. 配置模型和服务

复制 `settings.example.json` 为同目录下的 `settings.json`，用文本编辑器填写模型路径及 `uvr_tools_dir`。例如 Windows 在 `server` 目录执行：

```powershell
if (-not (Test-Path settings.json)) { Copy-Item settings.example.json settings.json }
notepad settings.json
```

Linux 可在确认 `settings.json` 不存在后执行 `cp settings.example.json settings.json`，再用文本编辑器打开。模型和 UVR5 目录可用绝对路径，也可相对于 `server` 目录；Windows JSON 路径可使用正斜杠（如 `D:/models/voice.pth`）或双反斜杠。没有索引文件时，`rvc_index` 留空；可执行文件字段留空会使用 PATH。

同一台机器且同一网络命名空间的默认设置为 `127.0.0.1:9881`。不同机器请按 [EasyTier 教程](easytier.md)设置监听 IP 和令牌。环境变量 `SING_RVC_MODEL`、`SING_RVC_INDEX`、`SING_UVR5_MODEL`、`UVR5_TOOLS_DIR`、`SING_HOST`、`SING_PORT`、`SING_API_TOKEN` 会覆盖对应的 JSON 设置。

网易云 `MUSIC_U` 凭据可自行写入 `server/.music_u`，或通过 `NETEASE_MUSIC_U` 环境变量提供。匿名和普通账号也可使用其可播放的曲目；是否有完整音源取决于版权和账号权益。`.music_u`、`settings.json` 和 MaiBot 生成的 `config.toml` 均不得提交或分享。登录凭据不是服务令牌，也不是 EasyTier 密钥。

## 5. 启动并连接

在 `server` 下运行 Windows 的 `start_server.bat` 或 Linux 的 `bash start_server.sh`。启动脚本优先使用 `server/.venv`，也可设置 `SING_PYTHON` 指定其他 Python。保持服务运行，启动失败时先看第一条报错；不要把账号信息或令牌发到公开场合。

本地单机时，在同一网络命名空间内访问 `http://127.0.0.1:9881/health`。配置了令牌的服务需要请求头 `X-Sing-Token`；无令牌时可直接用浏览器。把插件安装到 MaiBot 的 `plugins/` 后，在 WebUI 插件配置中填写服务地址及令牌。发送 `/唱歌状态` 可检查服务连接，使用 `/唱 歌名` 点歌或 `/唱 帮助` 查看命令。适配器需支持 `voiceurl` 且能读取音频路径。

## 6. 常见问题

- 找不到模型：检查 JSON 路径是否存在，确认是在 GPU 机器而不是 MaiBot 云服务器上配置。
- 无法导入 `vr`：`uvr_tools_dir` 必须包含 `vr.py`，且配套代码与依赖必须完整。
- NumPy、SciPy、Numba 或 PyTorch 导入错误：检查是否混用了多个 Python 环境。启动脚本禁用 user-site；不要向其他现有程序的环境随意安装或降级包。
- 返回 401：两端服务令牌不一致；连接失败则检查监听地址、进程和网络。
- 返回其他版本的歌曲：平台没有目标原唱或无播放权限时，可能找到同名版本；检查返回的歌手，不等同于已获得原唱版权。
- Docker：容器内的 `127.0.0.1` 是容器自身；按照容器网络配置可达地址，并为适配器提供可访问的音频文件路径。

发布前需在目标环境验证实际加载、语音发送和模型效果；模型、歌曲及角色音色的使用应符合各自授权。
