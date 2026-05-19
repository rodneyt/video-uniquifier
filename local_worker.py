"""
Local Worker for Video Uniquifier.
Runs on your Windows machine, connects to remote Redis/Postgres/R2.
Uses NVIDIA NVENC (RTX 4090) for blazing fast encoding.

Usage:
  1. Copy .env.local.example to .env.local and fill in values from Render
  2. pip install -r worker/requirements.txt
  3. python local_worker.py
"""
import os
import sys
import json
import time
import re
import uuid
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load local environment
load_dotenv(".env.local")

from sqlalchemy import create_engine, text
from redis import Redis
from rq import Queue, Worker
import boto3

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY")
R2_SECRET = os.environ.get("R2_SECRET")
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")

# Use NVENC if available (RTX 4090)
USE_NVENC = os.environ.get("USE_NVENC", "true").lower() == "true"

engine = create_engine(DATABASE_URL)
redis_conn = Redis.from_url(REDIS_URL)
q = Queue("video_jobs", connection=redis_conn)

s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET,
    region_name='auto'
)

# Local temp directory (Windows)
TEMP_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "video_uniquifier")
os.makedirs(TEMP_DIR, exist_ok=True)

print(f"[LOCAL] Temp dir: {TEMP_DIR}")
print(f"[LOCAL] NVENC: {'enabled' if USE_NVENC else 'disabled'}")
print(f"[LOCAL] Redis: {REDIS_URL[:30]}...")
print(f"[LOCAL] R2 Bucket: {R2_BUCKET}")


# ---------------------------------------------------------------------------
# Video Probing
# ---------------------------------------------------------------------------

def probe_video(video_path: str) -> dict:
    """Get video info via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[LOCAL] ffprobe error: {result.stderr[:500]}")
        return {"width": 1080, "height": 1920, "has_audio": False, "fps": 30}
    
    data = json.loads(result.stdout)
    width, height, has_audio, fps = 1080, 1920, False, 30
    
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 1080))
            height = int(stream.get("height", 1920))
            try:
                num, den = stream.get("r_frame_rate", "30/1").split("/")
                fps = round(int(num) / int(den), 2)
            except:
                fps = 30
        elif stream.get("codec_type") == "audio":
            has_audio = True
    
    print(f"[LOCAL] Video: {width}x{height}, fps={fps}, audio={has_audio}")
    return {"width": width, "height": height, "has_audio": has_audio, "fps": fps}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def generate_params() -> dict:
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
    }


def process_video(input_path: str, output_path: str) -> dict:
    """Process video with FFmpeg. Uses NVENC on RTX 4090 if available."""
    info = probe_video(input_path)
    params = generate_params()
    
    w, h = info["width"], info["height"]
    has_audio = info["has_audio"]
    
    # Build video filter
    zoom = params["zoom"]
    crop_w = int(w / zoom)
    crop_h = int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + params["dx"]), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + params["dy"]), h - crop_h))
    
    vf_parts = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={w}:{h}",
        f"eq=contrast={params['contrast']}:saturation={params['saturation']}",
    ]
    if params["hue"] != 0:
        vf_parts.append(f"hue=h={params['hue']}")
    vf_parts.append(f"noise=alls={params['noise']}:allf=t")
    vf_parts.append(f"setpts=PTS/{params['speed']}")
    
    vf = ",".join(vf_parts)
    filter_complex = f"[0:v]{vf}[v_final]"
    
    if has_audio:
        speed = max(0.5, min(params["speed"], 2.0))
        filter_complex += f";[0:a]atempo={speed:.3f}[a_final]"
    
    unique_title = f"clip-{uuid.uuid4().hex[:8]}"
    
    # Build command — NVENC for RTX 4090 or libx264 fallback
    cmd = ["ffmpeg", "-y", "-i", input_path, "-filter_complex", filter_complex, "-map", "[v_final]"]
    
    if has_audio:
        cmd.extend(["-map", "[a_final]"])
    
    if USE_NVENC:
        # NVIDIA NVENC — uses GPU, ~10-50x faster than CPU
        cmd.extend([
            "-c:v", "h264_nvenc",
            "-preset", "p4",        # Good quality/speed balance
            "-rc", "vbr",           # Variable bitrate
            "-cq", "20",            # Quality level (lower = better)
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ])
    else:
        # CPU fallback
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
    
    print(f"[LOCAL] FFmpeg {'NVENC' if USE_NVENC else 'CPU'} encoding...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        err = result.stderr[-1000:] if result.stderr else "No stderr"
        print(f"[LOCAL] FFmpeg FAILED ({elapsed}s): {err}")
        
        # Retry with CPU if NVENC failed
        if USE_NVENC:
            print("[LOCAL] Retrying with CPU encoding...")
            # Replace NVENC args with libx264
            for i, arg in enumerate(cmd):
                if arg == "h264_nvenc":
                    cmd[i] = "libx264"
                elif arg == "p4":
                    cmd[i] = "medium"
                elif arg == "-rc":
                    cmd[i] = "-crf"
                elif arg == "vbr":
                    cmd[i] = "20"
                elif arg == "-cq":
                    cmd.pop(i)
                    cmd.pop(i)  # Remove value too
                    break
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = round(time.time() - start, 1)
            if result.returncode != 0:
                raise Exception(f"FFmpeg CPU fallback also failed: {result.stderr[-500:]}")
        else:
            raise Exception(f"FFmpeg failed (code {result.returncode}): {err}")
    
    out_size = os.path.getsize(output_path)
    print(f"[LOCAL] Done in {elapsed}s — output: {out_size / 1024 / 1024:.1f} MB")
    
    params["original_size"] = f"{w}x{h}"
    params["has_audio"] = has_audio
    params["encoder"] = "nvenc" if USE_NVENC else "libx264"
    params["ffmpeg_duration_s"] = elapsed
    return params


# ---------------------------------------------------------------------------
# R2 Helpers
# ---------------------------------------------------------------------------

def download_from_r2(key: str, dest_path: str):
    print(f"[LOCAL] Downloading {key} from R2...", end=" ", flush=True)
    start = time.time()
    s3_client.download_file(R2_BUCKET, key, dest_path)
    size = os.path.getsize(dest_path)
    print(f"{size / 1024 / 1024:.1f} MB in {time.time() - start:.1f}s")

def upload_to_r2(file_path: str, key: str):
    size = os.path.getsize(file_path)
    print(f"[LOCAL] Uploading {size / 1024 / 1024:.1f} MB to R2...", end=" ", flush=True)
    start = time.time()
    s3_client.upload_file(file_path, R2_BUCKET, key)
    print(f"done in {time.time() - start:.1f}s")


# ---------------------------------------------------------------------------
# Job Runner
# ---------------------------------------------------------------------------

def run_job(job_id: str):
    """Main job processor — runs locally on your PC."""
    job_start = time.time()
    print(f"\n{'='*60}")
    print(f"[LOCAL] Processing job {job_id}")
    print(f"{'='*60}")
    
    # 1. Get job from remote DB
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT input_key FROM jobs WHERE id = :job_id"),
            {"job_id": job_id}
        ).fetchone()
        if not result:
            print(f"[LOCAL] Job {job_id} not found!")
            return
        input_key = result[0]
        
        conn.execute(
            text("UPDATE jobs SET status = 'processing' WHERE id = :job_id"),
            {"job_id": job_id}
        )
        conn.commit()
    
    input_path = os.path.join(TEMP_DIR, f"in_{job_id}.mp4")
    output_path = os.path.join(TEMP_DIR, f"out_{job_id}.mp4")
    output_key = f"outputs/{job_id}.mp4"
    
    try:
        # 2. Download from R2
        download_from_r2(input_key, input_path)
        
        # 3. Process with FFmpeg (NVENC GPU!)
        params = process_video(input_path, output_path)
        
        # Verify output
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Output file missing or empty")
        
        # 4. Upload result to R2
        upload_to_r2(output_path, output_key)
        
        # 5. Mark done in remote DB
        total = round(time.time() - job_start, 1)
        params["total_time_s"] = total
        
        with engine.connect() as conn:
            conn.execute(
                text("""
                    UPDATE jobs SET status = 'done', output_key = :output_key,
                    params_json = :params, finished_at = :finished_at
                    WHERE id = :job_id
                """),
                {
                    "output_key": output_key,
                    "params": json.dumps(params),
                    "finished_at": datetime.now(timezone.utc),
                    "job_id": job_id
                }
            )
            conn.commit()
        
        print(f"[LOCAL] JOB DONE in {total}s")
        print(f"{'='*60}\n")
        
    except Exception as e:
        total = round(time.time() - job_start, 1)
        error_msg = str(e)[:2000]
        print(f"[LOCAL] JOB FAILED after {total}s: {error_msg}")
        
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE jobs SET status = 'failed', error = :error, finished_at = :finished_at WHERE id = :job_id"),
                {"error": error_msg, "finished_at": datetime.now(timezone.utc), "job_id": job_id}
            )
            conn.commit()
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main — Start as RQ Worker
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  VIDEO UNIQUIFIER — Local Worker")
    print(f"  GPU: RTX 4090 (NVENC {'ON' if USE_NVENC else 'OFF'})")
    print(f"  Temp: {TEMP_DIR}")
    print(f"{'='*60}\n")
    
    # Test connections
    try:
        redis_conn.ping()
        print("[LOCAL] Redis connected")
    except Exception as e:
        print(f"[LOCAL] Redis FAILED: {e}")
        sys.exit(1)
    
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[LOCAL] Postgres connected")
    except Exception as e:
        print(f"[LOCAL] Postgres FAILED: {e}")
        sys.exit(1)
    
    print(f"[LOCAL] Queue size: {q.count} jobs waiting")
    print(f"[LOCAL] Listening for jobs on 'video_jobs'...\n")
    
    # Start RQ worker — listens to remote Redis, processes locally
    worker = Worker([q], connection=redis_conn, name=f"local-{os.getlogin()}")
    worker.work(with_scheduler=False)
