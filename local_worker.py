"""
Local Worker for Video Uniquifier.
Polls the Render API for pending jobs and processes them locally
using your RTX 4090 GPU with NVIDIA NVENC encoding.

NO Redis/Postgres connection needed — everything goes through the API.

Usage:
  1. pip install requests boto3 python-dotenv
  2. Copy .env.local.example to .env.local and fill in values
  3. python local_worker.py
"""
import os
import sys
import json
import time
import uuid
import random
import subprocess
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(".env.local")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.environ.get("API_URL", "https://video-uniquifier.onrender.com")
DEMO_EMAIL = os.environ.get("DEMO_EMAIL", "demo@example.com")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo123")

R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY")
R2_SECRET = os.environ.get("R2_SECRET")
R2_BUCKET = os.environ.get("R2_BUCKET")
R2_ENDPOINT = os.environ.get("R2_ENDPOINT")

USE_NVENC = os.environ.get("USE_NVENC", "true").lower() == "true"
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))  # seconds

# Local temp directory
TEMP_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "video_uniquifier")
os.makedirs(TEMP_DIR, exist_ok=True)

# R2 client
import boto3
s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET,
    region_name='auto'
)

# Auth token
TOKEN = None


def login():
    """Get JWT token from API."""
    global TOKEN
    print(f"[LOCAL] Logging in as {DEMO_EMAIL}...")
    resp = requests.post(f"{API_URL}/auth/login", data={
        "username": DEMO_EMAIL,
        "password": DEMO_PASSWORD
    })
    if resp.status_code != 200:
        print(f"[LOCAL] Login failed: {resp.text}")
        sys.exit(1)
    TOKEN = resp.json()["access_token"]
    print(f"[LOCAL] Logged in successfully")


def api_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# Video Processing
# ---------------------------------------------------------------------------

def probe_video(video_path: str) -> dict:
    """Get video info via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
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
    
    return {"width": width, "height": height, "has_audio": has_audio, "fps": fps}


def process_video(input_path: str, output_path: str) -> dict:
    """Process video with FFmpeg using NVENC (RTX 4090)."""
    info = probe_video(input_path)
    print(f"[LOCAL] Video: {info['width']}x{info['height']}, audio={info['has_audio']}")
    
    w, h = info["width"], info["height"]
    has_audio = info["has_audio"]
    
    # Random params
    zoom = round(random.uniform(1.02, 1.04), 3)
    dx = random.randint(-3, 3)
    dy = random.randint(-3, 3)
    speed = round(random.uniform(1.01, 1.03), 3)
    contrast = round(random.uniform(0.98, 1.02), 3)
    saturation = round(random.uniform(0.97, 1.03), 3)
    hue_shift = random.randint(-3, 3)
    noise = random.randint(3, 7)
    
    params = {
        "zoom": zoom, "dx": dx, "dy": dy, "speed": speed,
        "contrast": contrast, "saturation": saturation,
        "hue": hue_shift, "noise": noise,
        "original_size": f"{w}x{h}", "has_audio": has_audio
    }
    
    # Build video filter
    crop_w = int(w / zoom)
    crop_h = int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + dx), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + dy), h - crop_h))
    
    vf = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={w}:{h}",
        f"eq=contrast={contrast}:saturation={saturation}",
    ]
    if hue_shift != 0:
        vf.append(f"hue=h={hue_shift}")
    vf.append(f"noise=alls={noise}:allf=t")
    vf.append(f"setpts=PTS/{speed}")
    
    fc = f"[0:v]{','.join(vf)}[v_final]"
    if has_audio:
        fc += f";[0:a]atempo={max(0.5, min(speed, 2.0)):.3f}[a_final]"
    
    unique_title = f"clip-{uuid.uuid4().hex[:8]}"
    
    cmd = ["ffmpeg", "-y", "-i", input_path, "-filter_complex", fc, "-map", "[v_final]"]
    if has_audio:
        cmd.extend(["-map", "[a_final]"])
    
    if USE_NVENC:
        cmd.extend([
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-rc", "vbr",
            "-cq", "20",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ])
        params["encoder"] = "nvenc_rtx4090"
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ])
        params["encoder"] = "libx264"
    
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    
    cmd.extend([
        "-map_metadata", "-1",
        "-metadata", f"title={unique_title}",
        "-movflags", "+faststart",
        output_path
    ])
    
    print(f"[LOCAL] Encoding with {'NVENC (GPU)' if USE_NVENC else 'libx264 (CPU)'}...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        err = result.stderr[-800:] if result.stderr else "No error output"
        # Retry with CPU if NVENC failed
        if USE_NVENC:
            print(f"[LOCAL] NVENC failed, retrying with CPU...")
            # Rebuild command with libx264
            cmd_cpu = ["ffmpeg", "-y", "-i", input_path, "-filter_complex", fc, "-map", "[v_final]"]
            if has_audio:
                cmd_cpu.extend(["-map", "[a_final]"])
            cmd_cpu.extend([
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-profile:v", "high", "-pix_fmt", "yuv420p",
            ])
            if has_audio:
                cmd_cpu.extend(["-c:a", "aac", "-b:a", "128k"])
            cmd_cpu.extend([
                "-map_metadata", "-1", "-metadata", f"title={unique_title}",
                "-movflags", "+faststart", output_path
            ])
            result = subprocess.run(cmd_cpu, capture_output=True, text=True)
            elapsed = round(time.time() - start, 1)
            params["encoder"] = "libx264_fallback"
            if result.returncode != 0:
                raise Exception(f"FFmpeg failed: {result.stderr[-500:]}")
        else:
            raise Exception(f"FFmpeg failed: {err}")
    
    out_size = os.path.getsize(output_path)
    print(f"[LOCAL] Done in {elapsed}s - output: {out_size / 1024 / 1024:.1f} MB")
    params["ffmpeg_duration_s"] = elapsed
    return params


# ---------------------------------------------------------------------------
# Job Polling & Processing
# ---------------------------------------------------------------------------

def get_pending_jobs() -> list:
    """Get all queued jobs from the API."""
    resp = requests.get(f"{API_URL}/jobs", headers=api_headers())
    if resp.status_code == 401:
        login()  # Re-authenticate
        resp = requests.get(f"{API_URL}/jobs", headers=api_headers())
    if resp.status_code != 200:
        return []
    
    jobs = resp.json()
    return [j for j in jobs if j["status"] == "queued"]


def claim_job(job_id: str) -> bool:
    """Mark job as processing via API."""
    # We use the cleanup mechanism in reverse — set to processing directly
    # For now, the worker processes it and the status updates happen via 
    # direct DB updates through a special worker endpoint
    return True


def update_job_status(job_id: str, status: str, output_key: str = None, 
                       params: dict = None, error: str = None):
    """Update job status via API endpoint."""
    resp = requests.put(
        f"{API_URL}/worker/update-job/{job_id}",
        headers=api_headers(),
        json={
            "status": status,
            "output_key": output_key,
            "params_json": json.dumps(params) if params else None,
            "error": error
        }
    )
    return resp.status_code == 200


def process_job(job: dict):
    """Process a single job."""
    job_id = job["id"]
    input_key = job["input_key"]
    job_start = time.time()
    
    print(f"\n{'='*60}")
    print(f"  JOB: {job_id}")
    print(f"  Input: {input_key}")
    print(f"{'='*60}")
    
    input_path = os.path.join(TEMP_DIR, f"in_{job_id}.mp4")
    output_path = os.path.join(TEMP_DIR, f"out_{job_id}.mp4")
    output_key = f"outputs/{job_id}.mp4"
    
    # Mark as processing
    update_job_status(job_id, "processing")
    
    try:
        # Download from R2
        print(f"[LOCAL] Downloading from R2...", end=" ", flush=True)
        dl_start = time.time()
        s3_client.download_file(R2_BUCKET, input_key, input_path)
        size = os.path.getsize(input_path)
        print(f"{size / 1024 / 1024:.1f} MB in {time.time() - dl_start:.1f}s")
        
        # Process with FFmpeg
        params = process_video(input_path, output_path)
        
        # Verify
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Output file missing or empty")
        
        # Upload to R2
        out_size = os.path.getsize(output_path)
        print(f"[LOCAL] Uploading {out_size / 1024 / 1024:.1f} MB to R2...", end=" ", flush=True)
        ul_start = time.time()
        s3_client.upload_file(output_path, R2_BUCKET, output_key)
        print(f"done in {time.time() - ul_start:.1f}s")
        
        # Mark done
        total = round(time.time() - job_start, 1)
        params["total_time_s"] = total
        update_job_status(job_id, "done", output_key=output_key, params=params)
        
        print(f"\n  >>> JOB COMPLETE in {total}s <<<")
        print(f"{'='*60}\n")
        
    except Exception as e:
        total = round(time.time() - job_start, 1)
        error_msg = str(e)[:2000]
        print(f"\n  >>> JOB FAILED after {total}s: {error_msg}")
        print(f"{'='*60}\n")
        update_job_status(job_id, "failed", error=error_msg)
    
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*60}")
    print(f"  VIDEO UNIQUIFIER - Local Worker")
    print(f"  GPU: RTX 4090 (NVENC {'ON' if USE_NVENC else 'OFF'})")
    print(f"  API: {API_URL}")
    print(f"  Temp: {TEMP_DIR}")
    print(f"  Poll interval: {POLL_INTERVAL}s")
    print(f"{'='*60}\n")
    
    # Login
    login()
    
    # Test R2 connection
    try:
        s3_client.head_bucket(Bucket=R2_BUCKET)
        print(f"[LOCAL] R2 bucket '{R2_BUCKET}' connected")
    except Exception as e:
        print(f"[LOCAL] R2 connection failed: {e}")
        sys.exit(1)
    
    # Test FFmpeg
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    if result.returncode != 0:
        print("[LOCAL] FFmpeg not found! Install it first.")
        sys.exit(1)
    ffmpeg_version = result.stdout.split("\n")[0]
    print(f"[LOCAL] {ffmpeg_version}")
    
    if USE_NVENC:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"], 
            capture_output=True, text=True
        )
        if "h264_nvenc" in result.stdout:
            print("[LOCAL] NVENC encoder available")
        else:
            print("[LOCAL] WARNING: NVENC not available, falling back to CPU")
    
    print(f"\n[LOCAL] Listening for jobs... (Ctrl+C to stop)\n")
    
    while True:
        try:
            jobs = get_pending_jobs()
            if jobs:
                print(f"[LOCAL] Found {len(jobs)} pending job(s)")
                for job in jobs:
                    process_job(job)
            else:
                # Silent polling
                pass
        except KeyboardInterrupt:
            print("\n[LOCAL] Worker stopped.")
            break
        except Exception as e:
            print(f"[LOCAL] Error: {e}")
        
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
