# 模型准备

模型要放在运行推理服务的 GPU 机器上，不是填进 MaiBot WebUI。本项目不包含或提供爱莉希雅音色权重；Windows 安装器会下载 UVR5、RMVPE 和 HuBERT 基础模型，但 RVC 音色模型需要自行准备。

实测使用爱莉希雅 RVC v2 音色模型（`.pth`）和配套 `.index`，以及 HP5、RMVPE、HuBERT 基础模型。角色模型仅作为测试参考，项目不提供下载，其他获得授权的 RVC v2 模型也可尝试，效果需要自行试听。显存观察及其限制见 [README](../../README.md#硬件与模型参考)。

| 模型 | 获取方式 | 放置或配置 |
| --- | --- | --- |
| RVC v2 声线模型 `.pth` | 自训练或获授权的兼容模型；本项目不提供角色模型下载 | `settings.json` 中的 `rvc_model`，或 `models/elysiav3.pth` |
| 配套 `.index` | 与声线模型配套，可选 | `rvc_index`，没有则留空 |
| UVR5 HP5 权重 | [RVC 官方 UVR5 资源](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main/uvr5_weights)，请核对名称与使用条件 | `uvr_model`，或 `models/HP5_only_main_vocal.pth` |
| RMVPE `rmvpe.pt` | [RVC 官方资源仓库](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main) | 当前 `rvc-python` 安装目录的 `base_model/rmvpe.pt` |
| HuBERT `hubert_base.pt` | [RVC 官方资源仓库](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main) | 同一 `base_model/hubert_base.pt` |

还需要 GPT-SoVITS 的 `tools/uvr5` 下的 `vr.py` 和配套模块；Windows 安装器会下载并配置，手动安装时将该目录写入 `uvr_tools_dir`。不需要启动 GPT-SoVITS 的 TTS 服务，但需要兼容的 UVR5 代码及其依赖。不要修改现有生产环境的依赖；一键安装器尚未在另一台全新 Windows 电脑独立验证。

查找当前 Python 环境里的 `rvc-python` 目录，用启动服务的同一个 Python 运行：

```bash
python -s -c "from importlib.metadata import distribution; print(distribution('rvc-python').locate_file('rvc_python'))"
```

在打印的目录中找到或创建 `base_model`，放入 `rmvpe.pt` 和 `hubert_base.pt`。从受信任的来源获取文件，并确认模型、角色音色及素材的使用和分发授权；不要加载来源不明的权重。详见[部署指南](../../docs/deployment.md)。
