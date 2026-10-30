# -*- coding: utf-8 -*-
"""AI 唱歌推理后端引擎 (FastAPI)
包含模块：
1. 网易云可用音源获取与歌词片段定位
2. UVR5 人声与伴奏高保真无损分离 (HP5_only_main_vocal)
3. RMVPE 物理基频神经网络实时探测与自适应变调对齐 (F0 Median Analysis)
4. RVC v2 旗舰级声学模型干声演唱转换
5. 伴奏物理能量自适应母带混音引擎 (RMS-Adaptive Mix)
6. 自动轻量磁盘缓存清理
"""

import os
import re
import sys
import time
import json
import glob
import shutil
import requests
import subprocess
import threading
import hmac
import ipaddress
import tempfile
from functools import wraps
import numpy as np
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

# 基础目录与本机配置（环境变量优先）。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")
if os.path.exists(SETTINGS_PATH):
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as settings_file:
            SETTINGS = json.load(settings_file)
        if not isinstance(SETTINGS, dict):
            raise ValueError("顶层必须是 JSON 对象")
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"无法读取服务配置 {SETTINGS_PATH}: {exc}") from exc
else:
    SETTINGS = {}


def setting(env_name, key, default=""):
    return os.environ.get(env_name, SETTINGS.get(key, default))


def setting_path(env_name, key, default=""):
    value = setting(env_name, key, default)
    if not isinstance(value, str):
        raise ValueError(f"服务配置 {key} 必须是字符串")
    return os.path.normpath(os.path.join(BASE_DIR, value)) if value else ""

app = FastAPI(title="AI Singing Inference Engine SVIP Master Pro")
API_TOKEN = setting("SING_API_TOKEN", "api_token")
if not isinstance(API_TOKEN, str):
    raise ValueError("服务配置 api_token 必须是字符串")
_pipeline_lock = threading.RLock()


@app.middleware("http")
async def authenticate(request, call_next):
    if API_TOKEN and not hmac.compare_digest(request.headers.get("X-Sing-Token", "").encode(), API_TOKEN.encode()):
        return JSONResponse(status_code=401, content={"detail": "无效的服务令牌"})
    return await call_next(request)


def serialized(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _pipeline_lock:
            return func(*args, **kwargs)
    return wrapped

# 1. Node.js 执行文件与脚本定位
NODE_EXE = setting("NODE_EXE", "node_executable") or shutil.which("node") or "node"
VIP_SEARCH_SCRIPT = os.path.join(BASE_DIR, "vip_search.js")

NODE_MODULES = setting_path("SING_NODE_MODULES", "node_modules", "node_modules")

# 2. FFmpeg 路径检测
FFMPEG_PATH = setting("FFMPEG_PATH", "ffmpeg_executable") or shutil.which("ffmpeg") or "ffmpeg"

# 3. RVC 模型权重定位（优先 models/ 目录，其次回退本地工作区）
MODEL_DIR = os.path.join(BASE_DIR, "models")
V3_MODEL = os.path.join(MODEL_DIR, "elysiav3.pth")
V3_INDEX = os.path.join(MODEL_DIR, "added_IVF345_Flat_nprobe_1_elysiav3_v2.index")

custom_model = setting_path("SING_RVC_MODEL", "rvc_model")
MODEL_PATH = custom_model or V3_MODEL
INDEX_PATH = setting_path("SING_RVC_INDEX", "rvc_index") if custom_model else (V3_INDEX if os.path.exists(V3_INDEX) else "")
MODEL_VER = Path(MODEL_PATH).stem

# 4. UVR5 模型与脚本路径
UVR5_PATH = os.path.join(MODEL_DIR, "HP5_only_main_vocal.pth")
UVR5_PATH = setting_path("SING_UVR5_MODEL", "uvr_model") or UVR5_PATH

# 缓存与输出目录
TEMP_DIR = os.path.join(BASE_DIR, "temp")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(TEMP_DIR, "vocal"), exist_ok=True)
os.makedirs(os.path.join(TEMP_DIR, "ins"), exist_ok=True)

# 全局推理模型句柄
_rvc = None
_uvr = None
_rmvpe = None


def cleanup_disk(max_keep=20, max_age_hours=2):
    """自动清理临时切片和过期音频，防止硬盘膨胀。"""
    try:
        # 1. 清理临时切片和分离音轨
        for f in glob.glob(os.path.join(TEMP_DIR, "*.wav")):
            try:
                os.remove(f)
            except Exception:
                pass
        for f in glob.glob(os.path.join(TEMP_DIR, "vocal", "*.wav")):
            try:
                os.remove(f)
            except Exception:
                pass
        for f in glob.glob(os.path.join(TEMP_DIR, "ins", "*.wav")):
            try:
                os.remove(f)
            except Exception:
                pass

        # 2. 清理超过 2 小时的历史输出文件，且最多保留最新 20 个
        now = time.time()
        out_files = sorted(
            glob.glob(os.path.join(OUTPUT_DIR, "elysia_svip_*.wav")),
            key=os.path.getmtime,
            reverse=True,
        )
        for i, filepath in enumerate(out_files):
            file_age_hours = (now - os.path.getmtime(filepath)) / 3600.0
            if i >= max_keep or file_age_hours > max_age_hours:
                try:
                    os.remove(filepath)
                except Exception:
                    pass
    except Exception as e:
        print(f"[Cleanup] 磁盘清理异常: {e}")


@app.on_event("startup")
def startup_event():
    global _rvc, _uvr, _rmvpe
    print("=" * 60)
    print(f"[AI-Singing] 正在预热加载 RVC ({MODEL_VER})、UVR5 与 RMVPE 基频模型...")
    t0 = time.time()

    if not os.path.isfile(MODEL_PATH):
        raise RuntimeError(f"找不到 RVC 模型：{MODEL_PATH}；请在 server/settings.json 设置 rvc_model。")
    if INDEX_PATH and not os.path.isfile(INDEX_PATH):
        raise RuntimeError(f"找不到 RVC 索引：{INDEX_PATH}；请检查 rvc_index，或留空不用索引。")
    if not os.path.isfile(UVR5_PATH):
        raise RuntimeError(f"找不到 UVR5 模型：{UVR5_PATH}；请在 server/settings.json 设置 uvr_model。")

    # 1. RVC 初始化（专为唱歌调优的声学参数）
    from rvc_python.infer import RVCInference

    _rvc = RVCInference(
        device="cuda:0",
        model_path=MODEL_PATH,
        index_path=INDEX_PATH,
        version="v2",
    )
    _rvc.f0method = "rmvpe"
    _rvc.index_rate = 0.40  # 0.40 彻底消除说话音素的机械抽搐，让长音与颤音极致丝滑
    _rvc.protect = 0.45  # 保护气音与清辅音
    _rvc.filter_radius = 4  # 平滑音高抖动
    _rvc.rms_mix_rate = 0.70  # 动态响度柔化

    # 2. UVR5 初始化
    uvr_tools_path = setting_path("UVR5_TOOLS_DIR", "uvr_tools_dir")
    if os.path.exists(uvr_tools_path):
        sys.path.insert(0, uvr_tools_path)
    try:
        from vr import AudioPre
    except ImportError as exc:
        raise RuntimeError("无法导入 UVR5 分离代码；请设置包含 vr.py 的 uvr_tools_dir 并安装其依赖。") from exc

    _uvr = AudioPre(
        agg=10,
        model_path=UVR5_PATH,
        device="cuda:0",
        is_half=True,
    )

    # 3. RMVPE 物理基频探测模型预热（物理自适应对齐）
    from rvc_python.lib.rmvpe import RMVPE

    rmvpe_path = Path(_rvc.vc.lib_dir) / "base_model" / "rmvpe.pt"
    _rmvpe = RMVPE(str(rmvpe_path), is_half=_rvc.vc.config.is_half, device=_rvc.vc.config.device)
    _rvc.vc.pipeline.model_rmvpe = _rmvpe

    # 启动时执行一次磁盘垃圾清理
    cleanup_disk()

    print(f"[AI-Singing] 三大引擎（RVC + UVR5 + RMVPE）加载完成！当前模型: {MODEL_VER}，耗时: {time.time() - t0:.2f}s")
    print("[AI-Singing] 网易云检索模块已就绪，实际可用音质取决于歌曲和账号权益。")
    print("[AI-Singing] 物理基频自适应探测已激活（RMVPE F0 实时分析 + 黄金声线对齐）！")
    print("[AI-Singing] 伴奏能量自适应混音引擎 (RMS-Adaptive Mix) 已激活！")
    print("[AI-Singing] 引擎加载完成，HTTP 服务正在启动")
    print("=" * 60)


def search_song_and_lrc(keyword: str, duration: float = 11.0):
    print(f"[Music-Search] 正在检索网易云可用音源 (期望时长: {duration}s)...")
    cmd = [NODE_EXE, VIP_SEARCH_SCRIPT, keyword, str(duration)]
    env = os.environ.copy()
    env["NODE_PATH"] = NODE_MODULES
    try:
        res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("歌曲搜索服务超时，请稍后重试") from exc
    if res.returncode != 0:
        err = res.stderr or res.stdout
        raise ValueError(f"歌曲检索失败: {err}")
    data = json.loads(res.stdout)
    return data


def slice_audio(media_url: str, start_time: float, end_time: float, output_wav: str):
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-ss",
        f"{start_time:.2f}",
        "-to",
        f"{end_time:.2f}",
        "-i",
        media_url,
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        output_wav,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg slice error: {res.stderr.decode('utf-8', errors='ignore')}")


def separate_vocal(input_wav: str):
    global _uvr
    vocal_dir = os.path.join(TEMP_DIR, "vocal")
    ins_dir = os.path.join(TEMP_DIR, "ins")
    _uvr._path_audio_(
        music_file=input_wav,
        ins_root=ins_dir,
        vocal_root=vocal_dir,
        format="wav",
    )
    base = os.path.basename(input_wav)
    clean_vocal = os.path.join(vocal_dir, f"vocal_{base}_10.wav")
    clean_ins = os.path.join(ins_dir, f"instrument_{base}_10.wav")
    return clean_vocal, clean_ins


def mix_audio(vocal_wav: str, ins_wav: str, output_wav: str):
    """【伴奏能量自适应母带混音 (RMS-Adaptive Mix)】
    根据伴奏物理能量真实电平动态调整比例：
    伴奏轰头强音自动压制避让，轻柔慢歌保留温润饱满。
    """
    ins_db = -18.0
    try:
        import wave

        with wave.open(ins_wav, "rb") as w:
            data = w.readframes(w.getnframes())
            arr = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if len(arr) > 0:
                rms = np.sqrt(np.mean(arr**2))
                ins_db = 20 * np.log10(max(1.0, rms) / 32768.0)
    except Exception as e:
        print(f"[Mix] 伴奏电平读取异常，使用默认值: {e}")

    # 自适应计算伴奏与人声音量比：
    # 极轻柔慢歌 (ins_db <= -22dBFS): ins_vol = 0.85, vocal_vol = 1.18 (原汁原味)
    # 高能重编曲 (ins_db >= -13dBFS): ins_vol = 0.62, vocal_vol = 1.25 (压制轰头伴奏，人声凸显)
    # 中间曲风: 平滑线性映射
    if ins_db <= -22.0:
        ins_vol = 0.85
        vocal_vol = 1.18
    elif ins_db >= -13.0:
        ins_vol = 0.62
        vocal_vol = 1.25
    else:
        ratio = (ins_db - (-22.0)) / ((-13.0) - (-22.0))
        ins_vol = 0.85 - ratio * (0.85 - 0.62)
        vocal_vol = 1.18 + ratio * (1.25 - 1.18)

    print(f"[Mix-Adaptive] 伴奏物理能量: {ins_db:.1f} dBFS -> 动态混音比: 伴奏={ins_vol:.2f}, 人声={vocal_vol:.2f}")

    cmd = [
        FFMPEG_PATH,
        "-y",
        "-i",
        vocal_wav,
        "-i",
        ins_wav,
        "-filter_complex",
        (
            f"[0:a]aformat=channel_layouts=stereo,volume={vocal_vol:.2f}[v];"
            f"[1:a]aformat=channel_layouts=stereo,volume={ins_vol:.2f}[i];"
            "[v][i]amix=inputs=2:duration=first:dropout_transition=2[mixed];"
            "[mixed]alimiter=limit=0.95:level=true:attack=5:release=50[out]"
        ),
        "-map",
        "[out]",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "48000",
        output_wav,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg mix error: {res.stderr.decode('utf-8', errors='ignore')}")


def detect_vocal_pitch(clean_vocal_path: str, default_male: int = 8, default_female: int = 0):
    """【RMVPE 物理基频自适应探测】
    直接分析 UVR5 分离出的纯净人声切片波形，提取基频 (F0) 分布曲线，
    根据中位数 F0 自动对齐至爱莉希雅甜美声线黄金区。
    """
    global _rmvpe
    if _rmvpe is None:
        return (default_male if default_male is not None else 8), 0.0, "rmvpe_not_ready"
    try:
        from rvc_python.modules.vc.modules import load_audio

        audio = load_audio(clean_vocal_path, 16000)
        f0 = _rmvpe.infer_from_audio(audio, thred=0.03)
        voiced = f0[f0 > 0]
        if len(voiced) < 10:
            print(f"[F0-Detect] 未检测到足够有效有声帧 (voiced={len(voiced)})，回退至基准默认变调")
            return (default_male if default_male is not None else 8), 0.0, "unvoiced_fallback"

        med_f0 = float(np.median(voiced))

        # 爱莉希雅专属甜美基频目标点 (Target Sweet F0)
        # 专属男声基准为 +8，标准男声中位数 ~175Hz 对应目标约 278Hz (C#4/D4)
        target_sweet = 278.0

        if med_f0 >= 270.0:
            # 女高音/正常女声/高男假音（如田馥甄、梁静茹、王菲、周深）
            # 保持原调 0（自然甜美通透），绝不盲目降调或升调
            calc_pitch = default_female if default_female is not None else 0
            category = "女声/高音原调"
        elif med_f0 >= 220.0:
            # 女中音/深沉低女声/男高音过渡区（如买辣椒也用券《起风了》、低沉主歌）
            # 适度微升调 (+2 ~ +4)，摆脱沉闷粗暗，融入爱莉甜美区
            raw = int(round(12 * np.log2(target_sweet / med_f0)))
            calc_pitch = max(2, min(4, raw))
            category = "低女声/过渡微调"
        else:
            # 标准男声胸声区（如周杰伦、陈奕迅、薛之谦，中位数约 150~195Hz）
            # 动态计算并紧紧锚定在专属 +8 黄金基准附近 (+6 ~ +10)
            raw = int(round(12 * np.log2(target_sweet / med_f0)))
            calc_pitch = max(6, min(10, raw))
            category = "男声标准升调"

        print(
            f"[F0-Detect] 物理基频探测完成: 中位数 F0={med_f0:.1f} Hz (有声帧 {len(voiced)}/{len(f0)}) -> 自适应变调: {calc_pitch:+d} ({category})"
        )
        return calc_pitch, med_f0, category
    except Exception as e:
        print(f"[F0-Detect] 基频分析异常: {e}，回退至基准默认变调")
        return (default_male if default_male is not None else 8), 0.0, f"error: {e}"


@app.get("/sing")
@serialized
def api_sing(
    text: str = Query(..., description="要演唱的一句歌词"),
    duration: Optional[float] = Query(11.0, ge=6, le=16),
    pitch_shift: Optional[int] = Query(None, ge=-12, le=12),
    male_pitch: Optional[int] = Query(8, ge=-12, le=12),
    female_pitch: Optional[int] = Query(0, ge=-12, le=12),
    index_rate: Optional[float] = Query(None, ge=0, le=1),
    protect: Optional[float] = Query(None, ge=0, le=0.5),
    filter_radius: Optional[int] = Query(None, ge=0, le=7),
    rms_mix_rate: Optional[float] = Query(None, ge=0, le=1),
    format: str = Query("audio", description="返回格式: audio 或 json"),
):
    global _rvc, _uvr
    if _rvc is None or _uvr is None:
        raise HTTPException(status_code=503, detail="引擎尚未就绪")

    t0 = time.time()
    try:
        info = search_song_and_lrc(text, duration=duration if duration is not None else 11.0)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"歌词检索失败: {str(e)}")

    print(
        f"[AI-Singing] 命中歌曲: 《{info['song_name']}》 - {info['artist']} ({info.get('format', 'unknown').upper()}, 码率 {info.get('bitrate', 0)//1000}kbps)"
    )
    print(f"[AI-Singing] 已定位唱段 ({info['start_time']:.2f}s ~ {info['end_time']:.2f}s)")

    # 1. 切片官方母带
    raw_clip = os.path.join(TEMP_DIR, f"master_{info['song_id']}_{int(info['start_time'])}.wav")
    try:
        slice_audio(info["media_url"], info["start_time"], info["end_time"], raw_clip)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"母带切片失败: {str(e)}")

    # 2. UVR5 人声伴奏分离
    t_sep = time.time()
    try:
        clean_vocal, clean_ins = separate_vocal(raw_clip)
        print(f"[UVR5] 人声伴奏分离完成，耗时: {time.time() - t_sep:.2f}s")
    except Exception as e:
        print(f"[UVR5] 分离异常回退: {e}")
        clean_vocal = raw_clip
        clean_ins = None

    # 3. 确定变调：若显式指定了 pitch_shift 则严格尊重；若未指定则启动 RMVPE 物理基频自适应探测
    detected_f0 = 0.0
    f0_category = "manual_override"
    if pitch_shift is not None:
        print(f"[AI-Singing] 用户显式指定变调: {pitch_shift:+d} 半音（优先尊重人工指令，跳过自动探测）")
    else:
        pitch_shift, detected_f0, f0_category = detect_vocal_pitch(
            clean_vocal,
            default_male=male_pitch if male_pitch is not None else 8,
            default_female=female_pitch if female_pitch is not None else 0,
        )

    safe_name = re.sub(r'[\\/*?:"<>|]', "", info["song_name"])
    vocal_converted = os.path.join(TEMP_DIR, f"vocal_converted_{info['song_id']}_{int(time.time())}.wav")
    out_filename = f"elysia_svip_{safe_name}_{int(time.time())}.wav"
    out_wav = os.path.join(OUTPUT_DIR, out_filename)

    # 4. RVC 纯净干声演唱转换
    t_rvc = time.time()
    _rvc.f0up_key = pitch_shift
    _rvc.index_rate = float(index_rate) if index_rate is not None else 0.40
    _rvc.protect = float(protect) if protect is not None else 0.45
    _rvc.filter_radius = int(filter_radius) if filter_radius is not None else 4
    _rvc.rms_mix_rate = float(rms_mix_rate) if rms_mix_rate is not None else 0.70
    _rvc.infer_file(clean_vocal, vocal_converted)
    print(
        f"[RVC] 演唱转换完成，耗时: {time.time() - t_rvc:.2f}s (变调={pitch_shift}, 特征比={_rvc.index_rate}, 保护={_rvc.protect})"
    )

    # 5. 高保真母带重混（真双声道立体声）
    if clean_ins and os.path.exists(clean_ins):
        mix_audio(vocal_converted, clean_ins, out_wav)
    else:
        shutil.copyfile(vocal_converted, out_wav)

    cost_time = time.time() - t0
    print(f"[AI-Singing] 全部流程完成！总耗时: {cost_time:.2f}s，生成文件: {out_filename}")

    # 6. 后台执行轻量磁盘清理
    cleanup_disk()

    if format == "json":
        return {
            "status": "success",
            "song_name": info["song_name"],
            "artist": info["artist"],
            "audio_format": info.get("format", "flac"),
            "bitrate": info.get("bitrate", 0),
            "matched_lyric": info["matched_lyric"],
            "match_type": info.get("match_type", ""),
            "selection_notice": info.get("selection_notice", ""),
            "duration": round(info["duration"], 2),
            "pitch_shift": pitch_shift,
            "detected_f0": round(detected_f0, 1),
            "f0_category": f0_category,
            "index_rate": _rvc.index_rate,
            "protect": _rvc.protect,
            "filter_radius": _rvc.filter_radius,
            "cost_time": round(cost_time, 2),
            "download_url": f"/download/{out_filename}",
        }
    else:
        return FileResponse(
            out_wav,
            media_type="audio/wav",
            filename=f"elysia_{info['matched_lyric']}.wav",
            headers={
                "X-Song-Name": requests.utils.quote(info["song_name"]),
                "X-Artist": requests.utils.quote(info["artist"]),
                "X-Lyric": requests.utils.quote(info["matched_lyric"]),
                "X-Pitch-Shift": str(pitch_shift),
                "X-Detected-F0": f"{detected_f0:.1f}Hz",
                "X-F0-Category": requests.utils.quote(f0_category),
                "X-Cost-Time": f"{cost_time:.2f}s",
            },
        )


@app.get("/download/{filename}")
def download_file(filename: str):
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename or os.path.isabs(filename):
        raise HTTPException(status_code=404, detail="文件不存在")
    output_dir = os.path.realpath(OUTPUT_DIR)
    target = os.path.realpath(os.path.join(output_dir, filename))
    try:
        contained = os.path.commonpath((output_dir, target)) == output_dir
    except ValueError:
        contained = False
    if not contained or not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, media_type="audio/wav")


@app.get("/clean")
@app.post("/clean")
@serialized
def api_clean(all: bool = Query(False, description="是否同时清空outputs历史")):
    # 彻底清空 temp 目录
    removed_temp = 0
    for root, dirs, files in os.walk(TEMP_DIR):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
                removed_temp += 1
            except Exception:
                pass
    removed_out = 0
    if all:
        for f in os.listdir(OUTPUT_DIR):
            if f.endswith(".wav"):
                try:
                    os.remove(os.path.join(OUTPUT_DIR, f))
                    removed_out += 1
                except Exception:
                    pass
    return {
        "status": "success",
        "message": f"已清理 {removed_temp} 个临时切片文件" + (f"，{removed_out} 个历史生成文件" if all else ""),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "AI Singing Inference Engine SVIP Master Pro",
        "model": MODEL_VER,
        "uvr5": True,
        "rmvpe_f0": True,
        "rms_adaptive_mix": True,
    }


@app.post("/admin/settings")
@serialized
def update_service_settings(changes: dict):
    """显式保存服务设置；只有配置了令牌的服务允许此操作。"""
    if not API_TOKEN:
        raise HTTPException(status_code=403, detail="请先在推理服务端设置访问令牌并重启")
    env_names = {
        "host": "SING_HOST", "port": "SING_PORT", "rvc_model": "SING_RVC_MODEL",
        "rvc_index": "SING_RVC_INDEX", "uvr_model": "SING_UVR5_MODEL",
        "uvr_tools_dir": "UVR5_TOOLS_DIR",
    }
    if not changes or any(key not in env_names for key in changes):
        raise HTTPException(status_code=400, detail="没有可用设置，或包含不支持的设置")
    if any(env_names[key] in os.environ for key in changes):
        raise HTTPException(status_code=409, detail="该设置由环境变量覆盖，请在 GPU 电脑修改环境变量")
    for key, value in changes.items():
        if key == "port":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                raise HTTPException(status_code=400, detail="端口必须为 1 到 65535 的整数")
        elif not isinstance(value, str) or "\x00" in value or len(value) > 4096:
            raise HTTPException(status_code=400, detail="配置值无效")
        elif key == "host":
            try:
                if value != "localhost":
                    ipaddress.ip_address(value)
            except ValueError:
                raise HTTPException(status_code=400, detail="监听地址必须是 IP 地址或 localhost")
        elif key == "uvr_tools_dir":
            if not value or not os.path.isfile(os.path.join(setting_path_for_admin(value), "vr.py")):
                raise HTTPException(status_code=400, detail="UVR5 代码目录必须包含 vr.py")
        elif key in ("rvc_model", "uvr_model", "rvc_index"):
            if not value and key == "rvc_index":
                continue
            if not value or not os.path.isfile(setting_path_for_admin(value)):
                raise HTTPException(status_code=400, detail=f"{key} 文件不存在于 GPU 电脑")
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
                settings = json.load(f)
            if not isinstance(settings, dict):
                raise ValueError("设置文件不是 JSON 对象")
        else:
            settings = {}
        settings.update(changes)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=BASE_DIR,
                                             prefix=".settings-", suffix=".tmp", delete=False) as f:
                temp_path = f.name
                json.dump(settings, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(temp_path, SETTINGS_PATH)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"保存配置失败：{type(exc).__name__}")
    return {"status": "saved", "restart_required": True}


def setting_path_for_admin(value):
    return os.path.normpath(os.path.join(BASE_DIR, value))


if __name__ == "__main__":
    host = setting("SING_HOST", "host", "127.0.0.1")
    if host not in ("127.0.0.1", "::1", "localhost") and not API_TOKEN:
        raise SystemExit("非本机监听必须设置 api_token 或 SING_API_TOKEN")
    uvicorn.run(app, host=host, port=int(setting("SING_PORT", "port", 9881)))
