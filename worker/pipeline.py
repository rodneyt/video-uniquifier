"""
Video uniquification pipeline.
Applies subtle FFmpeg transformations to make each video copy unique.

IMPORTANT: All filter parameters MUST be literal numeric values.
           NEVER pass math expressions like "44100*0.998" to FFmpeg filters.
"""
import os
import re
import uuid
import random
import subprocess
import json
import time
from pathlib import Path
import boto3

# R2 Configuration
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY")
R2_SECRET = os.environ.get("R2_SECRET")
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")

s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET,
    region_name='auto'
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Patterns that should NEVER appear inside FFmpeg filter parameter values
_INVALID_FILTER_PATTERNS = re.compile(r'\d+[\*\/\+]\d')

def validate_filter_string(filter_str: str) -> None:
    """
    Scan a filter_complex string for math expressions that FFmpeg rejects.
    Raises ValueError if any are found.
    """
    # Split on known safe separators to isolate parameter values
    # We check the whole string for patterns like "44100*0.998"
    if _INVALID_FILTER_PATTERNS.search(filter_str):
        raise ValueError(
            f"Filter string contains math expression that FFmpeg won't evaluate: "
            f"{filter_str}"
        )

def validate_command(cmd: list) -> None:
    """
    Pre-execution validation of the full FFmpeg command.
    Checks for common mistakes in filter parameters.
    """
    for i, arg in enumerate(cmd):
        if arg == "-filter_complex" and i + 1 < len(cmd):
            validate_filter_string(cmd[i + 1])
    
    # Validate atempo range (must be 0.5 - 100.0)
    filter_idx = None
    for i, arg in enumerate(cmd):
        if arg == "-filter_complex" and i + 1 < len(cmd):
            filter_str = cmd[i + 1]
            atempo_match = re.search(r'atempo=([\d.]+)', filter_str)
            if atempo_match:
                val = float(atempo_match.group(1))
                if val < 0.5 or val > 100.0:
                    raise ValueError(f"atempo={val} is out of range [0.5, 100.0]")


# ---------------------------------------------------------------------------
# Video probing
# ---------------------------------------------------------------------------

def probe_video(video_path: str) -> dict:
    """Use ffprobe to get video info: dimensions, has_audio, fps, sample_rate."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[PIPELINE] ffprobe error: {result.stderr}", flush=True)
        return {"width": 1080, "height": 1920, "has_audio": False, "fps": 30, "sample_rate": 44100}
    
    data = json.loads(result.stdout)
    
    width = 1080
    height = 1920
    has_audio = False
    fps = 30
    sample_rate = 44100
    
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 1080))
            height = int(stream.get("height", 1920))
            fps_str = stream.get("r_frame_rate", "30/1")
            try:
                num, den = fps_str.split("/")
                fps = round(int(num) / int(den), 2)
            except Exception:
                fps = 30
        elif stream.get("codec_type") == "audio":
            has_audio = True
            sample_rate = int(stream.get("sample_rate", 44100))
    
    print(f"[PIPELINE] Video: {width}x{height}, fps={fps}, audio={has_audio}, sr={sample_rate}", flush=True)
    return {
        "width": width,
        "height": height,
        "has_audio": has_audio,
        "fps": fps,
        "sample_rate": sample_rate
    }


# ---------------------------------------------------------------------------
# Filter builders (all return literal values, NO math expressions)
# ---------------------------------------------------------------------------

def build_video_filter(orig_w: int, orig_h: int, params: dict) -> str:
    """Build the video filter chain. All values are pre-computed literals."""
    zoom = params["zoom"]
    dx = params["dx"]
    dy = params["dy"]
    speed = params["speed"]
    contrast = params["contrast"]
    saturation = params["saturation"]
    hue_shift = params["hue"]
    noise = params["noise"]
    
    crop_w = int(orig_w / zoom)
    crop_h = int(orig_h / zoom)
    crop_x = int((orig_w - crop_w) / 2 + dx)
    crop_y = int((orig_h - crop_h) / 2 + dy)
    
    # Clamp to valid bounds
    crop_x = max(0, min(crop_x, orig_w - crop_w))
    crop_y = max(0, min(crop_y, orig_h - crop_h))

    filters = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={orig_w}:{orig_h}",
        f"eq=contrast={contrast}:saturation={saturation}",
    ]
    
    if hue_shift != 0:
        filters.append(f"hue=h={hue_shift}")
    
    filters.append(f"noise=alls={noise}:allf=t")
    
    if params.get("hflip"):
        filters.append("hflip")
    
    # Speed change via setpts (literal division)
    filters.append(f"setpts=PTS/{speed}")
    
    return ",".join(filters)


def build_audio_filter(params: dict) -> str:
    """
    Build the audio filter chain.
    Uses ONLY atempo for speed change — no asetrate, no math expressions.
    atempo alone is sufficient to alter the audio fingerprint.
    """
    speed = params["speed"]
    # Clamp speed to valid atempo range
    speed = max(0.5, min(speed, 2.0))
    return f"atempo={speed:.3f}"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def generate_random_params() -> dict:
    """Generate random uniquification parameters."""
    return {
        "zoom": round(random.uniform(1.02, 1.04), 3),
        "dx": random.randint(-3, 3),
        "dy": random.randint(-3, 3),
        "speed": round(random.uniform(1.01, 1.03), 3),
        "contrast": round(random.uniform(0.98, 1.02), 3),
        "saturation": round(random.uniform(0.97, 1.03), 3),
        "hue": random.randint(-3, 3),
        "noise": random.randint(3, 7),
        "hflip": False,
    }


def build_ffmpeg_command(input_path: str, output_path: str, 
                          params: dict, info: dict,
                          conservative: bool = False) -> list:
    """
    Build the full FFmpeg command.
    If conservative=True, use minimal filters (retry mode).
    """
    orig_w = info["width"]
    orig_h = info["height"]
    has_audio = info["has_audio"]
    
    if conservative:
        # Minimal: just crop+scale+speed, no color grading or noise
        safe_params = {**params, "contrast": 1.0, "saturation": 1.0, 
                       "hue": 0, "noise": 0, "hflip": False}
        vf = build_video_filter(orig_w, orig_h, safe_params)
    else:
        vf = build_video_filter(orig_w, orig_h, params)
    
    filter_complex = f"[0:v]{vf}[v_final]"
    
    if has_audio:
        af = build_audio_filter(params)
        filter_complex += f";[0:a]{af}[a_final]"
    
    unique_title = f"clip-{uuid.uuid4().hex[:8]}"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v_final]",
    ]
    
    if has_audio:
        cmd.extend(["-map", "[a_final]"])
    
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
    ])
    
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    
    cmd.extend([
        "-map_metadata", "-1",
        "-metadata", f"title={unique_title}",
        "-movflags", "+faststart",
        output_path
    ])
    
    return cmd


def process_video(input_path: str, output_path: str) -> dict:
    """
    Main processing function with automatic retry.
    First attempt: full pipeline.
    Second attempt (on failure): conservative pipeline (no LUT, no grain).
    """
    info = probe_video(input_path)
    params = generate_random_params()
    params["original_size"] = f"{info['width']}x{info['height']}"
    params["has_audio"] = info["has_audio"]
    
    for attempt, conservative in enumerate([False, True], start=1):
        mode = "conservative" if conservative else "full"
        print(f"[PIPELINE] Attempt {attempt}/2 ({mode} mode)", flush=True)
        
        cmd = build_ffmpeg_command(input_path, output_path, params, info, 
                                   conservative=conservative)
        
        # Pre-execution validation
        try:
            validate_command(cmd)
        except ValueError as e:
            print(f"[PIPELINE] ❌ Validation failed: {e}", flush=True)
            if attempt == 2:
                raise
            continue
        
        print(f"[PIPELINE] CMD: {' '.join(cmd)}", flush=True)
        
        start_time = time.time()
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        duration = round(time.time() - start_time, 1)
        
        if result.returncode == 0:
            out_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            print(f"[PIPELINE] ✅ FFmpeg OK in {duration}s, output={out_size / 1024 / 1024:.1f}MB", flush=True)
            params["attempt"] = attempt
            params["mode"] = mode
            params["ffmpeg_duration_s"] = duration
            return params
        
        # Failed
        err_tail = result.stderr[-2000:] if result.stderr else "No stderr"
        print(f"[PIPELINE] ❌ FFmpeg FAILED (code {result.returncode}) in {duration}s", flush=True)
        print(f"[PIPELINE] stderr: {err_tail}", flush=True)
        
        if attempt == 2:
            raise Exception(
                f"FFmpeg falló con código {result.returncode} (ambos intentos). "
                f"Último error: {err_tail[-500:]}"
            )
        
        print("[PIPELINE] Retrying with conservative preset...", flush=True)
    
    # Should never reach here
    raise Exception("FFmpeg processing failed")


# ---------------------------------------------------------------------------
# R2 helpers
# ---------------------------------------------------------------------------

def download_from_r2(key: str, dest_path: str):
    s3_client.download_file(R2_BUCKET, key, dest_path)

def upload_to_r2(file_path: str, key: str):
    s3_client.upload_file(file_path, R2_BUCKET, key)
