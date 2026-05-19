"""
Local Worker for Video Uniquifier.
Polls the Render API for pending jobs and processes them locally
using your RTX 4090 GPU with NVIDIA NVENC encoding.

NO Redis, Postgres, or R2 credentials needed!
Everything goes through the Render API using presigned URLs.

Usage:
  1. pip install requests python-dotenv
  2. python local_worker.py
"""
import os
import sys
import json
import time
import uuid
import random
import subprocess
import requests
from dotenv import load_dotenv

# Load environment
load_dotenv(".env.local")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.environ.get("API_URL", "https://video-uniquifier.onrender.com")
DEMO_EMAIL = os.environ.get("DEMO_EMAIL", "demo@example.com")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo123")
USE_NVENC = os.environ.get("USE_NVENC", "true").lower() == "true"
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))

# Local temp directory
TEMP_DIR = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "video_uniquifier")
os.makedirs(TEMP_DIR, exist_ok=True)

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
    print(f"[LOCAL] Logged in OK")


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# R2 via Presigned URLs (no direct R2 access needed!)
# ---------------------------------------------------------------------------

def download_from_r2(job_id: str, dest_path: str):
    """Download video via presigned URL from API."""
    # Get presigned download URL from Render API
    resp = requests.get(f"{API_URL}/worker/download-url/{job_id}", headers=headers())
    if resp.status_code == 401:
        login()
        resp = requests.get(f"{API_URL}/worker/download-url/{job_id}", headers=headers())
    if resp.status_code != 200:
        raise Exception(f"Failed to get download URL: {resp.text}")
    
    download_url = resp.json()["download_url"]
    
    # Download the file
    print(f"[LOCAL] Downloading video...", end=" ", flush=True)
    start = time.time()
    r = requests.get(download_url, stream=True, verify=False)
    r.raise_for_status()
    
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192*16):
            f.write(chunk)
    
    size = os.path.getsize(dest_path)
    elapsed = round(time.time() - start, 1)
    print(f"{size / 1024 / 1024:.1f} MB in {elapsed}s")


def upload_to_r2(job_id: str, file_path: str) -> str:
    """Upload video via presigned URL from API."""
    # Get presigned upload URL from Render API
    resp = requests.get(f"{API_URL}/worker/upload-url/{job_id}", headers=headers())
    if resp.status_code == 401:
        login()
        resp = requests.get(f"{API_URL}/worker/upload-url/{job_id}", headers=headers())
    if resp.status_code != 200:
        raise Exception(f"Failed to get upload URL: {resp.text}")
    
    data = resp.json()
    upload_url = data["upload_url"]
    output_key = data["output_key"]
    
    # Upload the file
    size = os.path.getsize(file_path)
    print(f"[LOCAL] Uploading {size / 1024 / 1024:.1f} MB...", end=" ", flush=True)
    start = time.time()
    
    with open(file_path, 'rb') as f:
        r = requests.put(upload_url, data=f, 
                         headers={"Content-Type": "video/mp4"},
                         verify=False)
    r.raise_for_status()
    
    elapsed = round(time.time() - start, 1)
    print(f"done in {elapsed}s")
    return output_key


# ---------------------------------------------------------------------------
# Video Processing (FFmpeg with NVENC)
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
    
    # Random uniquification params
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
    
    # Build video filter chain
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
    
    # Build FFmpeg command
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
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-profile:v", "high", "-pix_fmt", "yuv420p",
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
    
    encoder_name = "NVENC (GPU)" if USE_NVENC else "libx264 (CPU)"
    print(f"[LOCAL] Encoding with {encoder_name}...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)
    
    if result.returncode != 0:
        err = result.stderr[-600:] if result.stderr else "No error"
        if USE_NVENC:
            print(f"[LOCAL] NVENC failed, retrying with CPU...")
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
                raise Exception(f"FFmpeg CPU also failed: {result.stderr[-400:]}")
        else:
            raise Exception(f"FFmpeg failed: {err}")
    
    out_size = os.path.getsize(output_path)
    print(f"[LOCAL] Encoded in {elapsed}s - output: {out_size / 1024 / 1024:.1f} MB")
    params["ffmpeg_duration_s"] = elapsed
    return params


# ---------------------------------------------------------------------------
# Job Polling & Processing
# ---------------------------------------------------------------------------

def get_pending_jobs() -> list:
    """Get all queued jobs from the API."""
    resp = requests.get(f"{API_URL}/jobs", headers=headers())
    if resp.status_code == 401:
        login()
        resp = requests.get(f"{API_URL}/jobs", headers=headers())
    if resp.status_code != 200:
        return []
    return [j for j in resp.json() if j["status"] == "queued"]


def update_job(job_id: str, status: str, output_key: str = None,
               params: dict = None, error: str = None):
    """Update job status via API."""
    body = {"status": status}
    if output_key:
        body["output_key"] = output_key
    if params:
        body["params_json"] = json.dumps(params)
    if error:
        body["error"] = error
    
    resp = requests.put(f"{API_URL}/worker/update-job/{job_id}",
                        headers=headers(), json=body)
    if resp.status_code == 401:
        login()
        resp = requests.put(f"{API_URL}/worker/update-job/{job_id}",
                            headers=headers(), json=body)
    return resp.status_code == 200


def process_job(job: dict):
    """Process a single job end-to-end."""
    job_id = job["id"]
    job_start = time.time()
    
    print(f"\n{'='*60}")
    print(f"  JOB: {job_id}")
    print(f"  Input: {job['input_key']}")
    print(f"{'='*60}")
    
    input_path = os.path.join(TEMP_DIR, f"in_{job_id}.mp4")
    output_path = os.path.join(TEMP_DIR, f"out_{job_id}.mp4")
    
    # Mark as processing
    update_job(job_id, "processing")
    
    try:
        # 1. Download via presigned URL
        download_from_r2(job_id, input_path)
        
        # 2. Process with FFmpeg (NVENC GPU)
        params = process_video(input_path, output_path)
        
        # 3. Verify output
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("Output file missing or empty")
        
        # 4. Upload via presigned URL
        output_key = upload_to_r2(job_id, output_path)
        
        # 5. Mark done
        total = round(time.time() - job_start, 1)
        params["total_time_s"] = total
        update_job(job_id, "done", output_key=output_key, params=params)
        
        print(f"\n  >>> JOB COMPLETE in {total}s <<<")
        print(f"{'='*60}\n")
        
    except Exception as e:
        total = round(time.time() - job_start, 1)
        error_msg = str(e)[:2000]
        print(f"\n  >>> JOB FAILED after {total}s: {error_msg}")
        print(f"{'='*60}\n")
        update_job(job_id, "failed", error=error_msg)
    
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Suppress SSL warnings for presigned URL downloads
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    print(f"\n{'='*60}")
    print(f"  VIDEO UNIQUIFIER - Local Worker")
    print(f"  GPU: RTX 4090 (NVENC {'ON' if USE_NVENC else 'OFF'})")
    print(f"  API: {API_URL}")
    print(f"  Poll every: {POLL_INTERVAL}s")
    print(f"{'='*60}\n")
    
    login()
    
    # Test FFmpeg
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    ver = result.stdout.split("\n")[0] if result.returncode == 0 else "NOT FOUND"
    print(f"[LOCAL] {ver}")
    
    if USE_NVENC:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
        if "h264_nvenc" in r.stdout:
            print("[LOCAL] NVENC encoder: READY")
        else:
            print("[LOCAL] NVENC not available, will use CPU")
    
    print(f"\n[LOCAL] Waiting for jobs... (Ctrl+C to stop)\n")
    
    while True:
        try:
            jobs = get_pending_jobs()
            if jobs:
                print(f"[LOCAL] Found {len(jobs)} job(s)!")
                for job in jobs:
                    process_job(job)
        except KeyboardInterrupt:
            print("\n[LOCAL] Worker stopped.")
            break
        except Exception as e:
            print(f"[LOCAL] Poll error: {e}")
        
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
