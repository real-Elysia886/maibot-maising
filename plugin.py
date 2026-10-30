# -*- coding: utf-8 -*-
"""MaiSing · 麦麦想唱歌（MaiBot SDK 2.x）

功能与管理特性：
- WebUI 界面可视化调音配置与参数原理说明（支持热更新）
- 用户通过 `/唱 <歌名/歌词> [参数]`（如：/唱 晴天 +12 或 /唱 后来）点播歌曲
- 用户通过 `/重唱 [参数]`（如：/重唱 +12 或 /重唱 相似度=0.45）重新生成并调参
- 用户通过 `/唱 帮助` 查看所有调音选项的自然语言说明
- 插件在发送后自动清理临时音频
- LLM 在自然聊天中可通过 `sing_song` 工具自主演唱
"""

import os
import re
import uuid
import asyncio
import logging
import aiohttp
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from maibot_sdk import MaiBotPlugin, Command, Tool
from maibot_sdk.config_widgets import ConfigWidget, ConfigWidgetState
from maibot_sdk.types import ToolParameterInfo, ToolParamType
from .config import SingingPluginConfig

logger = logging.getLogger("plugin.elysia_sing")

PARAM_HELP_TEXT = """🎛️【MaiSing 调音台 · 参数指南】
您可以在「/唱」或「/重唱」后面自由追加调音参数，就像在专业录音棚调音一样：

1️⃣ 变调 (pitch / 音调)
• 取值范围：-12 到 +12 个半音（默认基准：男声+8，女声0）
• 原理解析：默认备用变调为 +8 半音；音高检测成功时会根据音源自动调整，也可手动指定。不同音色模型适合的变调可能不同。
• 常用示例：/重唱 +8  或  /唱 晴天 变调=+8  或  /重唱 0

2️⃣ 相似度 (index / 音色)
• 取值范围：0.0 ~ 1.0（默认 0.40，推荐 0.35 ~ 0.50）
• 原理解析：控制 RVC 索引特征的占比，效果取决于模型和音源，可通过试听调整。
• 常用示例：/重唱 相似度=0.45

3️⃣ 咬字保护 (protect / 呼吸)
• 取值范围：0.0 ~ 0.5（默认 0.45）
• 原理解析：保护歌手换气声、轻柔气声细节与清辅音拼音开头（b, p, t, k, s 等），防止吞字破音。
• 常用示例：/重唱 保护=0.48

4️⃣ 平滑度 (filter / 平滑)
• 取值范围：0 ~ 7（默认 4）
• 原理解析：过滤音高杂音与走调。数值越大音准曲线越平稳；数值小更保留原歌手真假音微颤。
• 常用示例：/重唱 平滑=5

5️⃣ 动态融合 (rms / 响度)
• 取值范围：0.0 ~ 1.0（默认 0.70）
• 原理解析：控制原唱音量起伏与模型输出音量的融合比例。

6️⃣ 演唱时长 (duration / 秒数)
• 取值范围：6 ~ 16 秒（默认 11 秒）
• 原理解析：控制切出的副歌长度。想要听完整大副歌（连唱两三句）可加「时长=13」或「秒=14」；若想精炼一句可加「时长=7」。
• 常用示例：/重唱 时长=14  或  /唱 起风了 秒=13

💡 常用快捷操作：
• /重唱 +8 （切回专属男声音域最佳黄金点）
• /重唱 +12 （一键转甜美女高音）
• /重唱 0 （一键切回原调抒情音）
• /重唱 变调=+8 时长=13
• /唱歌状态 （检查推理服务能否连接）"""


def parse_sing_args(raw_args: str) -> Tuple[str, Dict[str, Any]]:
    """解析点歌与重唱参数。"""
    params: Dict[str, Any] = {}
    tokens = raw_args.strip().split()
    text_parts = []

    for t in tokens:
        # 纯数字/符号变调简写（如 +12, -2, 0, 12, +8）
        if re.match(r"^[+-]?\d+$", t):
            params["pitch_shift"] = int(t)
            continue

        # 键值对解析（如 变调=8, pitch=8, 相似度=0.4, index=0.4）
        if "=" in t or "：" in t:
            sep = "=" if "=" in t else "："
            k, v = t.split(sep, 1)
            k = k.strip().lower()
            v = v.strip()

            if k in ["变调", "音调", "升调", "降调", "pitch", "p", "key"]:
                try:
                    params["pitch_shift"] = int(v)
                except ValueError:
                    pass
            elif k in ["时长", "秒数", "时间", "秒", "duration", "len", "length"]:
                try:
                    params["duration"] = float(v)
                except ValueError:
                    pass
            elif k in ["相似度", "音色", "还原度", "index", "index_rate", "i"]:
                try:
                    params["index_rate"] = float(v)
                except ValueError:
                    pass
            elif k in ["保护", "呼吸", "咬字", "protect", "r"]:
                try:
                    params["protect"] = float(v)
                except ValueError:
                    pass
            elif k in ["平滑", "滤波", "filter", "radius"]:
                try:
                    params["filter_radius"] = int(v)
                except ValueError:
                    pass
            elif k in ["响度", "动态", "rms", "rms_mix"]:
                try:
                    params["rms_mix_rate"] = float(v)
                except ValueError:
                    pass
            else:
                text_parts.append(t)
        else:
            text_parts.append(t)

    text = " ".join(text_parts).strip()
    return text, params


class ElysiaSingPlugin(MaiBotPlugin):
    """MaiSing 唱歌插件。"""

    config_model = SingingPluginConfig
    config_widgets = [
        ConfigWidget(id="remote_config_status", kind="status", label="推理服务配置状态"),
        ConfigWidget(id="remote_config_apply", kind="action", label="应用推理服务配置",
                     confirmation="将已保存的非空配置写入推理服务；服务需重启后生效。是否继续？"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._session: Optional[aiohttp.ClientSession] = None
        self._cleanup_tasks: set = set()
        self._remote_config_result = "尚未提交推理服务配置。"
        self._remote_config_tone = "neutral"
        # 记录每个会话最后一次点播的歌词/歌名与参数字典
        self._last_song: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    async def on_load(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self.config.singing.timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info("[ElysiaSing] MaiSing 唱歌插件已就绪！服务地址: %s", self.config.singing.server_url)

    async def on_unload(self) -> None:
        for task in list(self._cleanup_tasks):
            task.cancel()
        self._cleanup_tasks.clear()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("[ElysiaSing] MaiSing 唱歌插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """WebUI 配置热更新回调。"""
        logger.info("[ElysiaSing] 唱歌插件配置已从 WebUI 更新: scope=%s version=%s", scope, version)
        if self._session and not self._session.closed:
            await self._session.close()
        timeout = aiohttp.ClientTimeout(total=self.config.singing.timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def get_config_widget_state(self) -> Dict[str, ConfigWidgetState]:
        return {
            "remote_config_status": ConfigWidgetState(text=self._remote_config_result, tone=self._remote_config_tone),
            "remote_config_apply": ConfigWidgetState(),
        }

    async def on_config_widget_action(self, action_id: str) -> None:
        if action_id != "remote_config_apply":
            raise ValueError("未知操作")
        await self._apply_remote_settings(self.config.remote_server)

    async def _apply_remote_settings(self, remote: Any) -> None:
        """只在 WebUI 显式触发时向新服务提交配置。"""
        self._remote_config_tone = "error"
        if not self.config.singing.server_token:
            self._remote_config_result = "未提交：请先在推理服务和插件两端配置相同的服务令牌。"
        elif remote.clear_rvc_index and remote.rvc_index:
            self._remote_config_result = "未提交：不能同时填写新索引并开启清除索引。"
        else:
            changes = {key: getattr(remote, key) for key in
                       ("rvc_model", "rvc_index", "uvr_model", "uvr_tools_dir", "host", "port")
                       if getattr(remote, key)}
            if remote.clear_rvc_index:
                changes["rvc_index"] = ""
            if not changes:
                self._remote_config_result = "未提交：没有填写要修改的推理服务配置。"
            else:
                try:
                    url = self.config.singing.server_url.rstrip("/") + "/admin/settings"
                    async with self._session.post(url, json=changes, headers=self._headers(),
                                                  timeout=aiohttp.ClientTimeout(total=6)) as response:
                        if response.status == 200:
                            data = await response.json()
                            self._remote_config_result = (
                                "推理服务配置已保存，请在 GPU 电脑重启推理服务；"
                                "如修改了地址或端口，还需同步修改插件的唱歌服务地址。"
                                if data.get("status") == "saved" else "推理服务返回异常，请检查服务日志。"
                            )
                            if data.get("status") == "saved":
                                self._remote_config_tone = "success"
                        elif response.status == 404:
                            self._remote_config_result = "推理服务不支持远程配置；旧服务未被修改，请先升级并验证服务。"
                        else:
                            data = await response.json(content_type=None)
                            self._remote_config_result = f"推理服务未保存配置（HTTP {response.status}）：{data.get('detail', '请检查服务日志')}"
                except Exception as exc:
                    logger.warning("[ElysiaSing] 推理服务配置提交失败: %s", type(exc).__name__)
                    self._remote_config_result = "无法提交推理服务配置，请检查服务地址、令牌和网络。"
        logger.info("[ElysiaSing] %s", self._remote_config_result)

    @Command("sing_config_status", description="查看最近一次推理服务配置提交结果",
             pattern=r"^/(?:sing_config_status|唱歌配置状态)$")
    async def handle_config_status(self, stream_id: str = "", **kwargs: Any) -> Tuple[bool, str, bool]:
        if not stream_id:
            return False, "缺少 stream_id", True
        await self.ctx.send.text(self._remote_config_result, stream_id)
        return True, self._remote_config_result, True

    def _audio_dir(self) -> str:
        return self.config.singing.audio_output_dir or str(self.ctx.paths.runtime_dir)

    def _headers(self) -> Dict[str, str]:
        token = self.config.singing.server_token
        return {"X-Sing-Token": token} if token else {}

    # ─── 命令 1：用户点歌（支持参数调音） ────────────────────────────────

    @Command(
        "sing",
        description="点播麦麦唱一句歌（支持参数，如：/唱 晴天 +8 或 /唱 后来）",
        pattern=r"^/(?:sing|唱|唱歌)(?:\s+(?P<args>.+))?$",
    )
    async def handle_sing_command(
        self,
        stream_id: str = "",
        text: str = "",
        matched_groups: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str, bool]:
        if not self.config.plugin.enabled:
            return False, "唱歌插件已在配置中禁用", True
        if not stream_id:
            return False, "缺少 stream_id", True

        groups = matched_groups or {}
        raw_args = (groups.get("args") or "").strip()

        if not raw_args or raw_args in ["帮助", "help", "?", "？"]:
            await self.ctx.send.text(PARAM_HELP_TEXT, stream_id)
            return True, "显示调音帮助", True

        song_text, extra_params = parse_sing_args(raw_args)
        if not song_text:
            await self.ctx.send.text("想听我唱什么歌呀？比如发「/唱 晴天」或「/唱 听妈妈的话 +8」，发送「/唱 帮助」可查看调音指南！", stream_id)
            return False, "缺少歌名", True

        success, msg = await self._do_sing(stream_id, song_text, custom_params=extra_params, is_tool=False)
        return success, msg, True

    # ─── 命令 2：重新生成上一首片段（自由调参） ─────────────────────────

    @Command(
        "resing",
        description="重新生成上一首歌（支持自定义调音参数，如：/重唱 +8 或 /重唱 相似度=0.45）",
        pattern=r"^/(?:resing|重唱|重新唱)(?:\s+(?P<args>.+))?$",
    )
    async def handle_resing_command(
        self,
        stream_id: str = "",
        text: str = "",
        matched_groups: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str, bool]:
        if not self.config.plugin.enabled:
            return False, "唱歌插件已在配置中禁用", True
        if not stream_id:
            return False, "缺少 stream_id", True

        last_info = self._last_song.get(stream_id)
        if not last_info:
            await self.ctx.send.text("最近还没有点过歌呢，先发「/唱 歌名」点一首试试吧！", stream_id)
            return False, "无上一首记录", True

        last_query, last_params = last_info
        groups = matched_groups or {}
        raw_args = (groups.get("args") or "").strip()

        if raw_args in ["帮助", "help", "?", "？"]:
            await self.ctx.send.text(PARAM_HELP_TEXT, stream_id)
            return True, "显示调音帮助", True

        _, new_params = parse_sing_args(raw_args)
        merged_params = dict(last_params)
        merged_params.update(new_params)

        # 若未指定变调且上一首是 0，自动切为 +8 方便快速试听对比
        if "pitch_shift" not in new_params and "pitch_shift" in merged_params:
            if merged_params["pitch_shift"] == 0:
                merged_params["pitch_shift"] = 8

        param_desc_list = []
        if "pitch_shift" in merged_params:
            p = merged_params["pitch_shift"]
            param_desc_list.append(f"变调: {'+' if p > 0 else ''}{p}")
        if "index_rate" in merged_params:
            param_desc_list.append(f"相似度: {merged_params['index_rate']}")
        if "protect" in merged_params:
            param_desc_list.append(f"咬字保护: {merged_params['protect']}")
        if "filter_radius" in merged_params:
            param_desc_list.append(f"平滑度: {merged_params['filter_radius']}")
        desc_str = "，".join(param_desc_list) if param_desc_list else "默认参数"

        await self.ctx.send.text(f"🔄 正在为您重新生成《{last_query}》（{desc_str}）...", stream_id)

        success, msg = await self._do_sing(stream_id, last_query, custom_params=merged_params, is_tool=False)
        return success, msg, True

    @Command(
        "sing_status",
        description="检查唱歌推理服务的连接状态",
        pattern=r"^/(?:sing_status|唱歌状态)$",
    )
    async def handle_status_command(self, stream_id: str = "", **kwargs: Any) -> Tuple[bool, str, int]:
        """检查服务状态，不触发歌曲生成。"""
        if not self.config.plugin.enabled:
            return False, "唱歌插件已在配置中禁用", 1
        if not stream_id:
            return False, "缺少 stream_id", 1
        if not self._session or self._session.closed:
            message = "唱歌插件连接尚未初始化，请检查插件状态。"
            await self.ctx.send.text(message, stream_id)
            return False, message, 1
        try:
            server_url = self.config.singing.server_url.rstrip("/")
            async with self._session.get(
                f"{server_url}/health", headers=self._headers(), timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 401:
                    message = "唱歌服务令牌不正确，请核对插件和推理服务配置。"
                elif response.status != 200:
                    message = f"唱歌服务暂不可用（HTTP {response.status}）。"
                else:
                    data = await response.json()
                    if not isinstance(data, dict) or data.get("status") != "ok":
                        message = "唱歌服务返回了异常状态，请查看推理服务日志。"
                    else:
                        message = "唱歌服务已连接，可以点歌。"
                        await self.ctx.send.text(message, stream_id)
                        return True, message, 1
        except Exception as exc:
            logger.warning("[ElysiaSing] 唱歌服务状态检查失败: %s", exc)
            message = "无法连接唱歌服务，请检查服务地址、网络和推理服务是否启动。"
        await self.ctx.send.text(message, stream_id)
        return False, message, 1

    # ─── 工具：LLM 自然对话中自主调用 ────────────────────────────────────

    @Tool(
        "sing_song",
        description=(
            "演唱歌曲片段，使用用户配置的 RVC 音色模型。"
            "调用此工具时请指定歌名或代表歌词。\n"
            "• 音准与变调由底层 RMVPE 物理基频神经网络自动实时探测与对齐（男声自动对齐至专属 +8 黄金区，女声自动保持原调），无需猜测变调；\n"
            "• 你可根据曲风节奏可选提供：\n"
            "  - index_rate（音色比 0.2~0.8）：快歌元气（0.5~0.6），慢歌丝滑（0.3~0.4）；\n"
            "  - protect（保护比 0.2~0.5）：抒情留气声（0.45~0.48），快歌吐字利落（0.38~0.42）；\n"
            "  - duration（时长 6~16秒）：连贯大副歌（12~14秒），短精炼一句（8秒）。"
        ),
        parameters=[
            ToolParameterInfo(
                name="song_or_lyric",
                param_type=ToolParamType.STRING,
                description="要演唱的歌曲名或代表歌词（例如：起风了、晴天、七里香、后来、勇气）",
                required=True,
            ),
            ToolParameterInfo(
                name="index_rate",
                param_type=ToolParamType.FLOAT,
                description="针对该曲风建议的音色特征比（0.2~0.8，可选）",
                required=False,
            ),
            ToolParameterInfo(
                name="protect",
                param_type=ToolParamType.FLOAT,
                description="针对该歌曲节奏建议的咬字与呼吸保护（0.2~0.5，可选）",
                required=False,
            ),
            ToolParameterInfo(
                name="duration",
                param_type=ToolParamType.FLOAT,
                description="期望演唱切片时长秒数（6~16秒，可选，默认11秒）",
                required=False,
            ),
        ],
    )
    async def handle_sing_tool(
        self,
        stream_id: str = "",
        song_or_lyric: str = "",
        index_rate: Optional[float] = None,
        protect: Optional[float] = None,
        duration: Optional[float] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """处理大模型自主调用的唱歌工具。"""
        if not self.config.plugin.enabled:
            return False, "唱歌插件已在配置中禁用"
        if not self.config.interaction.enable_tool_calling:
            return False, "大模型自主唱歌功能已在插件配置中关闭"
        if not stream_id:
            return False, "缺少 stream_id"

        # 判断是否开启了大模型自适应风格参数开关
        custom_params: Dict[str, Any] = {}
        if self.config.interaction.enable_llm_auto_tuning:
            if index_rate is not None:
                custom_params["index_rate"] = index_rate
            if protect is not None:
                custom_params["protect"] = protect
            if duration is not None:
                custom_params["duration"] = duration
            if custom_params:
                logger.info("[ElysiaSing] LLM 风格辅助参数单次生效: %s (基准配置不受影响)", custom_params)
        else:
            logger.debug("[ElysiaSing] 大模型自适应调音开关关闭，严格使用用户设定的基准配置")

        return await self._do_sing(stream_id, song_or_lyric, custom_params=custom_params if custom_params else None, is_tool=True)

    # ─── 核心处理逻辑 ────────────────────────────────────────────────────

    async def _do_sing(
        self,
        stream_id: str,
        query_text: str,
        custom_params: Optional[Dict[str, Any]] = None,
        is_tool: bool = False,
    ) -> Tuple[bool, str]:
        if not self._session or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.singing.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

        server_url = self.config.singing.server_url.rstrip("/")
        sing_api = f"{server_url}/sing"

        # 默认参数继承 WebUI 配置
        params: Dict[str, Any] = {
            "text": query_text,
            "format": "json",
            "duration": self.config.acoustic.default_duration,
            "male_pitch": self.config.acoustic.default_male_pitch_shift,
            "female_pitch": self.config.acoustic.default_female_pitch_shift,
            "index_rate": self.config.acoustic.default_index_rate,
            "protect": self.config.acoustic.default_protect,
            "filter_radius": self.config.acoustic.default_filter_radius,
            "rms_mix_rate": self.config.acoustic.default_rms_mix_rate,
        }

        # 用户显式传入参数覆盖默认值
        if custom_params:
            for k, v in custom_params.items():
                if v is not None:
                    params[k] = v

        logger.info("[ElysiaSing] 开始点唱: query='%s', params=%s, stream=%s", query_text, params, stream_id)
        try:
            async with self._session.get(sing_api, params=params, headers=self._headers()) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    logger.error("[ElysiaSing] 唱歌服务端返回错误 %d: %s", resp.status, err_text)
                    if not is_tool:
                        await self.ctx.send.text(f"哎呀，这首歌没搜到或者点唱失败了呢：{err_text}", stream_id)
                    return False, f"点歌失败: {err_text}"
                data = await resp.json()

            song_name = data.get("song_name", "未知歌曲")
            artist = data.get("artist", "未知歌手")
            matched_lyric = data.get("matched_lyric", "")
            actual_pitch = data.get("pitch_shift", 0)
            detected_f0 = data.get("detected_f0", 0.0)
            f0_category = data.get("f0_category", "")
            actual_index = data.get("index_rate", self.config.acoustic.default_index_rate)
            download_url = data.get("download_url", "")
            if not download_url:
                return False, "服务端未返回音频下载链接"

            # 下载合成音频到 temp_audio
            audio_url = f"{server_url}{download_url}"
            out_dir = self._audio_dir()
            os.makedirs(out_dir, exist_ok=True)
            temp_filename = f"sing_elysia_{uuid.uuid4().hex[:12]}.wav"
            local_path = os.path.join(out_dir, temp_filename)

            async with self._session.get(audio_url, headers=self._headers()) as resp:
                if resp.status != 200:
                    return False, "下载合成音频文件失败"
                audio_bytes = await resp.read()

            with open(local_path, "wb") as f:
                f.write(audio_bytes)

            logger.info("[ElysiaSing] 音频已成功保存: %s (%d 字节)", local_path, len(audio_bytes))

            # 通过支持 voiceurl 的适配器发送语音。
            sent = False
            try:
                if hasattr(self.ctx.send, "custom"):
                    sent = bool(await self.ctx.send.custom("voiceurl", local_path, stream_id))
            except Exception as e:
                logger.warning("[ElysiaSing] send.custom failed: %s", e)

            if not sent:
                os.remove(local_path)
                if not is_tool:
                    await self.ctx.send.text("音频已生成，但语音发送失败，请检查适配器配置。", stream_id)
                return False, "语音发送失败，请检查适配器配置"

            # 仅在发送成功后更新重唱记录。
            saved_params = dict(custom_params or {})
            saved_params["pitch_shift"] = actual_pitch
            saved_params["index_rate"] = actual_index
            self._last_song[stream_id] = (query_text, saved_params)

            # 如果开启了卡片提示且非纯工具调用，发送调音信息卡片
            if not is_tool and self.config.interaction.send_song_card:
                pitch_tag = f"+{actual_pitch}" if actual_pitch > 0 else str(actual_pitch)
                f0_tag = f"，基频探测: {detected_f0}Hz [{f0_category}]" if detected_f0 > 0 else ""
                text_notice = (
                    f"🎵 为你演唱《{song_name}》- {artist}（变调: {pitch_tag}{f0_tag}，音色相似度: {actual_index}）\n"
                    f"“{matched_lyric}”\n"
                    f"💡 觉得太高或太低？可随时发「/重唱 +8」或「/重唱 0」重新生成！发「/唱 帮助」看全部调音选项。"
                )
                await self.ctx.send.text(text_notice, stream_id)

            # 注册延迟自动清理
            clean_delay = self.config.singing.auto_clean_delay
            task = asyncio.create_task(self._cleanup_file(local_path, delay=clean_delay))
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)

            return True, f"已用语音为你演唱《{song_name}》中的片段：“{matched_lyric}”"

        except Exception as e:
            logger.exception("[ElysiaSing] 演唱执行异常: %s", e)
            if not is_tool:
                await self.ctx.send.text(f"唱歌时出了点小状况呢：{str(e)}", stream_id)
            return False, f"演唱失败: {str(e)}"

    async def _cleanup_file(self, path: str, delay: int = 180) -> None:
        try:
            await asyncio.sleep(delay)
            if os.path.exists(path):
                os.remove(path)
                logger.debug("[ElysiaSing] 已自动清理临时音频: %s", path)
        except Exception:
            pass


def _repair_empty_host_config() -> None:
    """修复宿主开关在首次加载前生成的仅含 enabled 的无版本配置。"""
    path = Path(__file__).resolve().parent / "config.toml"
    try:
        if not path.is_file() or path.is_symlink():
            return
        with path.open("r+b") as f:
            original = f.read()
            text = original.decode("utf-8-sig")
            if not re.fullmatch(
                r"[ \t\r\n]*\[plugin\][ \t]*\r?\n[ \t]*enabled[ \t]*=[ \t]*(?:true|false)[ \t\r\n]*",
                text,
            ):
                return
            f.seek(0)
            if f.read() != original:
                return
            f.seek(0, os.SEEK_END)
            prefix = b"" if original.endswith((b"\n", b"\r")) else b"\n"
            f.write(prefix + b'config_version = "1.2.0"\n')
    except (OSError, UnicodeError):
        logger.warning("[ElysiaSing] 无法自动修复初始插件配置，请查看 README。")


def create_plugin() -> ElysiaSingPlugin:
    """创建 MaiSing 插件实例（MaiBot SDK 2.x 入口）。"""
    _repair_empty_host_config()
    return ElysiaSingPlugin()
