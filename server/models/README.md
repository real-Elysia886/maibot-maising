# 模型准备

模型要放在运行推理服务的 GPU 机器上，不是填进 MaiBot WebUI。本项目不包含或提供爱莉希雅音色权重，也不自动下载模型。

| 模型 | 获取方式 | 放置或配置 |
| --- | --- | --- |
| RVC v2 声线模型 `.pth` | 自训练或获授权的兼容模型；本项目不提供角色模型下载 | `settings.json` 中的 `rvc_model`，或 `models/elysiav3.pth` |
| 配套 `.index` | 与声线模型配套，可选 | `rvc_index`，没有则留空 |
| UVR5 HP5 权重 | [RVC 官方 UVR5 资源](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main/uvr5_weights)，请核对名称与使用条件 | `uvr_model`，或 `models/HP5_only_main_vocal.pth` |
| RMVPE `rmvpe.pt` | [RVC 官方资源仓库](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main) | 当前 `rvc-python` 安装目录的 `base_model/rmvpe.pt` |
| HuBERT `hubert_base.pt` | [RVC 官方资源仓库](https://huggingface.co/lj1995/VoiceConversionWebUI/tree/main) | 同一 `base_model/hubert_base.pt` |

还需要 GPT-SoVITS 的 `tools/uvr5` 下的 `vr.py` 和配套模块；将该目录写入 `uvr_tools_dir`。不需要启动 GPT-SoVITS 的 TTS 服务，但需要兼容的 UVR5 代码及其依赖。不要修改现有生产环境的依赖；项目尚未完成全新环境的一键安装验证。

查找当前 Python 环境里的 `rvc-python` 目录，用启动服务的同一个 Python 运行：

```bash
python -s -c "from importlib.metadata import distribution; print(distribution('rvc-python').locate_file('rvc_python'))"
```

在打印的目录中找到或创建 `base_model`，放入 `rmvpe.pt` 和 `hubert_base.pt`。从受信任的来源获取文件，并确认模型、角色音色及素材的使用和分发授权；不要加载来源不明的权重。详见[部署指南](../../docs/deployment.md)。
