import os
import uuid
import random
import subprocess
import json
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

def probe_video(video_path: str) -> dict:
    """Use ffprobe to get video info: dimensions, has_audio, fps"""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[WORKER] ffprobe error: {result.stderr}", flush=True)
        return {"width": 1080, "height": 1920, "has_audio": False, "fps": 30}
    
    data = json.loads(result.stdout)
    
    width = 1080
    height = 1920
    has_audio = False
    fps = 30
    
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 1080))
            height = int(stream.get("height", 1920))
            # Parse fps from r_frame_rate (e.g., "30/1")
            fps_str = stream.get("r_frame_rate", "30/1")
            try:
                num, den = fps_str.split("/")
                fps = int(num) / int(den)
            except:
                fps = 30
        elif stream.get("codec_type") == "audio":
            has_audio = True
    
    print(f"[WORKER] Video info: {width}x{height}, fps={fps}, audio={has_audio}", flush=True)
    return {"width": width, "height": height, "has_audio": has_audio, "fps": fps}

def get_random_lut() -> str:
    """Obtiene un LUT aleatorio de la carpeta /assets/luts/"""
    luts_dir = Path('/app/assets/luts')
    if not luts_dir.exists():
        return ""
    luts = list(luts_dir.glob("*.cube"))
    if not luts:
        return ""
    return str(random.choice(luts))

def process_video(input_path: str, output_path: str) -> dict:
    """
    Aplica el pipeline de FFmpeg en UN SOLO pase.
    Detecta automáticamente las dimensiones y si hay audio.
    """
    # 0. Probe video info
    info = probe_video(input_path)
    orig_w = info["width"]
    orig_h = info["height"]
    has_audio = info["has_audio"]
    
    # 1. Generar parámetros aleatorios
    zoom = round(random.uniform(1.02, 1.04), 3)
    dx = random.randint(-3, 3)
    dy = random.randint(-3, 3)
    speed = round(random.uniform(1.01, 1.03), 3)
    contrast = round(random.uniform(0.98, 1.02), 3)
    saturation = round(random.uniform(0.97, 1.03), 3)
    hue_shift = random.randint(-3, 3)
    noise = random.randint(3, 7)
    pitch = round(random.uniform(0.98, 1.02), 3)
    
    lut_path = get_random_lut()
    lut_opacity = round(random.uniform(0.10, 0.20), 2)
    
    # 2. No flip (simplify for now)
    can_flip = False

    params = {
        "zoom": zoom,
        "dx": dx,
        "dy": dy,
        "speed": speed,
        "contrast": contrast,
        "saturation": saturation,
        "hue": hue_shift,
        "noise": noise,
        "pitch": pitch,
        "lut": Path(lut_path).name if lut_path else None,
        "lut_opacity": lut_opacity,
        "hflip": can_flip,
        "original_size": f"{orig_w}x{orig_h}",
        "has_audio": has_audio
    }

    # 3. Construir el grafo de filtros complejos de FFmpeg
    # Use actual video dimensions
    crop_w = int(orig_w / zoom)
    crop_h = int(orig_h / zoom)
    crop_x = int((orig_w - crop_w) / 2 + dx)
    crop_y = int((orig_h - crop_h) / 2 + dy)
    
    # Asegurar que el crop no se salga de los bordes
    crop_x = max(0, min(crop_x, orig_w - crop_w))
    crop_y = max(0, min(crop_y, orig_h - crop_h))

    v_filters = []
    
    # Crop y scale back to original dimensions
    v_filters.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")
    v_filters.append(f"scale={orig_w}:{orig_h}")
    
    # Color grading: eq (contrast + saturation)
    v_filters.append(f"eq=contrast={contrast}:saturation={saturation}")
    
    # Hue shift (separate filter, only if non-zero)
    if hue_shift != 0:
        v_filters.append(f"hue=h={hue_shift}")
    
    # Ruido / Film grain
    v_filters.append(f"noise=alls={noise}:allf=t")
    
    # Flip horizontal
    if can_flip:
        v_filters.append("hflip")
        
    # Cambio de velocidad de video
    v_filters.append(f"setpts=PTS/{speed}")

    v_filter_chain = ",".join(v_filters)
    
    # Build filter_complex - skip LUT for simplicity and reliability
    filter_complex = f"[0:v]{v_filter_chain}[v_final]"
    v_out_map = "[v_final]"

    # Audio filter (only if video has audio)
    if has_audio:
        a_filter_chain = f"atempo={speed}"
        filter_complex += f";[0:a]{a_filter_chain}[a_final]"
        a_out_map = "[a_final]"

    # 4. Construir comando FFmpeg
    unique_title = f"clip-{uuid.uuid4().hex[:8]}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", v_out_map,
    ]
    
    if has_audio:
        cmd.extend(["-map", a_out_map])
    
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
    
    print(f"[WORKER] FFmpeg command: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        # Show last 800 chars of stderr for debugging
        err_tail = result.stderr[-800:] if result.stderr else "No stderr"
        print(f"[WORKER] FFmpeg FAILED (code {result.returncode}): {err_tail}", flush=True)
        raise Exception(f"FFmpeg falló con código {result.returncode}")
    else:
        print("[WORKER] FFmpeg completado exitosamente.", flush=True)

    return params

def download_from_r2(key: str, dest_path: str):
    s3_client.download_file(R2_BUCKET, key, dest_path)

def upload_to_r2(file_path: str, key: str):
    s3_client.upload_file(file_path, R2_BUCKET, key)
