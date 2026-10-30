# -*- coding: utf-8 -*-
"""MaiSing · 麦麦想唱歌 WebUI 配置模型（MaiBot SDK 2.x）。

在 MaiBot 控制面板 / WebUI 插件设置中自动渲染图形化交互配置表单。
每个选项均配有详细的自然语言功能说明与调音原理。
"""

from maibot_sdk import Field, PluginConfigBase


class PluginSectionConfig(PluginConfigBase):
    """插件基础设置。"""

    __ui_label__ = "插件基础"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="是否启用唱歌插件",
        json_schema_extra={
            "label": "启用插件",
            "hint": "总开关。关闭后不再响应 /唱、/重唱 指令，也不会在自然聊天中调用唱歌工具。",
        },
    )
    config_version: str = Field(
        default="1.2.0",
        description="配置版本号",
        json_schema_extra={
            "label": "配置版本",
            "hint": "宿主根据此版本号热更新和迁移配置，请勿修改或删除。",
        },
    )


class SingServerConfig(PluginConfigBase):
    """服务与网络连接。"""

    __ui_label__ = "服务与网络"
    __ui_icon__ = "server"
    __ui_order__ = 1

    server_url: str = Field(
        default="http://127.0.0.1:9881",
        description="唱歌推理后端服务地址 (FastAPI)",
        json_schema_extra={
            "label": "唱歌服务地址 (FastAPI)",
            "hint": "同一网络命名空间内运行请保留默认值；跨机器时填写 GPU 电脑的 EasyTier 虚拟 IP 和端口。Docker 内的 127.0.0.1 指容器自身。设置后可发送 /唱歌状态 检查连接。模型在 GPU 电脑上配置，见 README。",
            "placeholder": "http://127.0.0.1:9881",
        },
    )
    server_token: str = Field(
        default="",
        description="唱歌服务访问令牌",
        json_schema_extra={
            "label": "唱歌服务令牌",
            "x-widget": "password",
            "input_type": "password",
            "hint": "与 GPU 端 settings.json 中的 api_token 或 SING_API_TOKEN 一致；未启用令牌时留空。配置仍会保存在本机，请勿分享。",
        },
    )
    timeout: int = Field(
        default=60,
        ge=10,
        le=300,
        description="单次点歌超时时间（秒）",
        json_schema_extra={
            "label": "点歌超时时间（秒）",
            "hint": "涵盖检索母带、智能定位副歌切片、UVR5 分离人声、RVC 演唱转换与母带重混的全流程最长等待时间。默认 60 秒足够充裕。",
            "placeholder": "60",
        },
    )
    audio_output_dir: str = Field(
        default="",
        description="临时音频输出目录",
        json_schema_extra={
            "label": "临时音频目录",
            "hint": "留空使用插件运行时目录；如适配器需要共享目录，可填写绝对路径。",
            "placeholder": "留空使用插件运行时目录",
        },
    )
    auto_clean_delay: int = Field(
        default=180,
        ge=30,
        le=3600,
        description="临时音频自动清理延迟（秒）",
        json_schema_extra={
            "label": "临时音频保留时间（秒）",
            "hint": "语音发出后等待多少秒自动删除本地临时 wav 文件以释放磁盘空间。默认 180 秒（3分钟）。",
            "placeholder": "180",
        },
    )


class AcousticTuningConfig(PluginConfigBase):
    """声学与调音默认设置。"""

    __ui_label__ = "声学与调音设置"
    __ui_icon__ = "sliders"
    __ui_order__ = 2

    default_male_pitch_shift: int = Field(
        default=8,
        ge=-12,
        le=12,
        description="音高检测失败时的备用变调（半音）",
        json_schema_extra={
            "label": "音高检测失败时的备用变调",
            "hint": (
                "RMVPE 未能检测音高时使用，默认 +8 半音。检测成功时，服务端按实际音高自动计算变调；"
                "可在点歌命令中显式指定变调。"
            ),
            "placeholder": "8",
        },
    )
    default_duration: float = Field(
        default=11.0,
        ge=6.0,
        le=16.0,
        description="默认演唱切片时长（秒）",
        json_schema_extra={
            "label": "默认演唱时长（秒）",
            "hint": (
                "【自然语言说明】：控制每次点歌生成的切片长度（6~16秒，默认 11 秒）。"
                "设为 11~14 秒可完整连贯演唱 2~3 句大副歌；若只想听 1 句精炼高潮可设为 6~8 秒。"
            ),
            "placeholder": "11.0",
        },
    )
    default_female_pitch_shift: int = Field(
        default=0,
        ge=-12,
        le=12,
        description="女声歌曲默认变调（半音）",
        json_schema_extra={
            "label": "女声歌曲默认变调（半音数）",
            "hint": (
                "【自然语言说明】：女歌手歌曲（如王菲、梁静茹、孙燕姿）天然处于女声音域，"
                "默认保持「0」（原调）即可获得最纯正自然、如官方单曲一般的抒情听感。"
            ),
            "placeholder": "0",
        },
    )
    default_index_rate: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="音色特征检索比（相似度）",
        json_schema_extra={
            "label": "音色相似度 (Index Rate)",
            "hint": "控制 RVC 检索特征的占比。不同模型的效果不同；默认 0.40，可试听后调整。",
            "placeholder": "0.40",
        },
    )
    default_protect: float = Field(
        default=0.45,
        ge=0.0,
        le=0.5,
        description="咬字与轻辅音保护比",
        json_schema_extra={
            "label": "咬字与气声保护 (Protect)",
            "hint": (
                "【自然语言说明】：保护歌声中的换气呼吸、轻柔气声细节与清辅音拼音开头（b, p, t, k, s 等），"
                "防止吞字、破音或产生金属哑音。推荐保持 0.40~0.48（默认 0.45）。"
            ),
            "placeholder": "0.45",
        },
    )
    default_filter_radius: int = Field(
        default=4,
        ge=0,
        le=7,
        description="音高中值滤波半径（平滑度）",
        json_schema_extra={
            "label": "音准平滑度 (Filter Radius)",
            "hint": (
                "【自然语言说明】：对音准曲线进行平滑去噪滤波。"
                "数值越大（4~7）：走调杂音越少、音准更平稳；"
                "数值越小（0~3）：越完整保留原唱歌手细微的真假声转换与微颤音。默认 4。"
            ),
            "placeholder": "4",
        },
    )
    default_rms_mix_rate: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="原唱音量动态融合比",
        json_schema_extra={
            "label": "原唱动态融合 (RMS Mix)",
            "hint": (
                "【自然语言说明】：将原唱的强弱起伏（如主歌轻声细语、副歌深情爆发）与模型音量融合的比例。"
                "1.0 为完全贴合原唱动态，0.70 为兼顾甜美与动态的柔化平衡点。"
            ),
            "placeholder": "0.70",
        },
    )


class RemoteServerSettings(PluginConfigBase):
    """需要服务端配合并重启后生效的设置。"""

    __ui_label__ = "推理服务配置"
    __ui_icon__ = "server"
    __ui_order__ = 3

    rvc_model: str = Field(default="", description="GPU 电脑上的 RVC v2 模型路径；留空不修改",
        json_schema_extra={"label": "RVC 音色模型", "hint": "填写 GPU 电脑上已有的 .pth 文件路径；留空不修改。保存到服务端后需重启推理服务。"})
    rvc_index: str = Field(default="", description="GPU 电脑上的 RVC 索引路径；留空不修改",
        json_schema_extra={"label": "RVC 索引", "hint": "填写与模型配套的 .index 路径；留空不修改。想移除索引请开启下方清除开关。"})
    clear_rvc_index: bool = Field(default=False, description="清除已配置的 RVC 索引",
        json_schema_extra={"label": "清除 RVC 索引", "hint": "开启后会清空服务端的索引路径；不能同时填写新索引。"})
    uvr_model: str = Field(default="", description="GPU 电脑上的 UVR5 模型路径；留空不修改",
        json_schema_extra={"label": "UVR5 分离模型", "hint": "仅在更换人声分离模型时填写 GPU 电脑的文件路径；留空不修改。"})
    uvr_tools_dir: str = Field(default="", description="GPU 电脑上的 UVR5 代码目录；留空不修改",
        json_schema_extra={"label": "UVR5 代码目录", "hint": "填写包含 vr.py 的 GPU 电脑目录；一般由安装器自动配置，留空不修改。"})
    host: str = Field(default="", description="服务监听地址；留空不修改",
        json_schema_extra={"label": "推理服务监听地址", "hint": "同机可用 127.0.0.1；跨机器填 GPU 电脑的可达地址。修改错误可能导致重启后无法连接。"})
    port: int = Field(default=0, ge=0, le=65535, description="服务监听端口；0 表示不修改",
        json_schema_extra={"label": "推理服务监听端口", "hint": "填 1–65535；0 表示不修改。重启后还需将“唱歌服务地址”中的端口改成相同值。"})

class InteractionConfig(PluginConfigBase):
    """聊天交互与功能开关。"""

    __ui_label__ = "交互与功能"
    __ui_icon__ = "music"
    __ui_order__ = 4

    send_song_card: bool = Field(
        default=False,
        description="点歌成功后是否发送调音信息卡片",
        json_schema_extra={
            "label": "发送调音信息卡片",
            "hint": "默认关闭。开启后，点歌或重唱成功时会额外发送歌名、歌手、变调和相似度等调音信息。",
        },
    )
    enable_tool_calling: bool = Field(
        default=True,
        description="允许大模型自然对话中自主唱歌",
        json_schema_extra={
            "label": "允许大模型自主唱歌",
            "hint": "开启后，麦麦在自然闲聊中察觉你想听歌（如：'唱首七里香吧'、'我想听你唱歌'）时，会主动调用唱歌工具为你发送语音。",
        },
    )
    enable_llm_auto_tuning: bool = Field(
        default=False,
        description="启用大模型风格参数辅助（微调相似度与保护比）",
        json_schema_extra={
            "label": "大模型风格参数辅助",
            "hint": (
                "【物理自适应与风格辅助】：\n"
                "• 音高变调已全面交由底层 RMVPE 物理基频算法实时自适应对齐（男声自动对齐至专属 +8 黄金区，女声自动保留 0 原调，低女声过渡微调 +3）；\n"
                "• 关闭（默认推荐）：严格锁定你配置的基准线参数，绝不偏离，听感稳定平衡；\n"
                "• 开启：麦麦在自主点歌时仅针对歌曲风格微调相似度或咬字保护，单次用完立刻恢复基准。"
            ),
        },
    )


class SingingPluginConfig(PluginConfigBase):
    """MaiSing 插件总配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    singing: SingServerConfig = Field(default_factory=SingServerConfig)
    remote_server: RemoteServerSettings = Field(default_factory=RemoteServerSettings)
    acoustic: AcousticTuningConfig = Field(default_factory=AcousticTuningConfig)
    interaction: InteractionConfig = Field(default_factory=InteractionConfig)
