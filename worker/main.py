"""
RQ Worker job handler.
Downloads video from R2, processes it, uploads result.
Stores detailed error info in Postgres for frontend display.
"""
import os
import sys
import json
import time
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from worker.pipeline import process_video, download_from_r2, upload_to_r2

# Force unbuffered output so logs show in Render immediately
os.environ["PYTHONUNBUFFERED"] = "1"

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)


def run_job(job_id: str):
    """
    Main worker function. Downloads video, processes it, uploads result.
    Updates Postgres at each step with status and error details.
    """
    job_start = time.time()
    print(f"[WORKER] ════════════════════════════════════════", flush=True)
    print(f"[WORKER] Starting job {job_id}", flush=True)
    
    # 1. Get job from DB
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT input_key FROM jobs WHERE id = :job_id"), 
            {"job_id": job_id}
        ).fetchone()
        if not result:
            print(f"[WORKER] Job {job_id} not found in DB", flush=True)
            return
        input_key = result[0]
        
        # Mark as processing
        conn.execute(
            text("UPDATE jobs SET status = 'processing' WHERE id = :job_id"),
            {"job_id": job_id}
        )
        conn.commit()
    
    print(f"[WORKER] Input key: {input_key}", flush=True)

    temp_dir = "/tmp/video_jobs"
    os.makedirs(temp_dir, exist_ok=True)
    
    input_path = os.path.join(temp_dir, f"in_{job_id}.mp4")
    output_path = os.path.join(temp_dir, f"out_{job_id}.mp4")
    output_key = f"outputs/{job_id}.mp4"

    try:
        # 2. Download from R2
        print(f"[WORKER] Downloading from R2...", flush=True)
        dl_start = time.time()
        download_from_r2(input_key, input_path)
        file_size = os.path.getsize(input_path)
        dl_time = round(time.time() - dl_start, 1)
        print(f"[WORKER] Downloaded: {file_size / 1024 / 1024:.1f} MB in {dl_time}s", flush=True)
        
        # 3. Process video (includes auto-retry)
        print(f"[WORKER] Processing video...", flush=True)
        params = process_video(input_path, output_path)
        
        # Verify output exists and has content
        if not os.path.exists(output_path):
            raise Exception("FFmpeg produced no output file")
        out_size = os.path.getsize(output_path)
        if out_size == 0:
            raise Exception("FFmpeg output file is empty (0 bytes)")
        
        # 4. Upload to R2
        print(f"[WORKER] Uploading result ({out_size / 1024 / 1024:.1f} MB) to R2...", flush=True)
        ul_start = time.time()
        upload_to_r2(output_path, output_key)
        ul_time = round(time.time() - ul_start, 1)
        print(f"[WORKER] Uploaded in {ul_time}s", flush=True)
        
        # 5. Mark as done in DB
        total_time = round(time.time() - job_start, 1)
        params["total_time_s"] = total_time
        
        with engine.connect() as conn:
            conn.execute(
                text("""
                UPDATE jobs 
                SET status = 'done', 
                    output_key = :output_key, 
                    params_json = :params, 
                    finished_at = :finished_at 
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
            
        print(f"[WORKER] ✅ Job {job_id} DONE in {total_time}s", flush=True)
        print(f"[WORKER] ════════════════════════════════════════", flush=True)
        
    except Exception as e:
        total_time = round(time.time() - job_start, 1)
        error_msg = str(e)[:2000]  # Truncate to fit in DB
        print(f"[WORKER] ❌ Job {job_id} FAILED after {total_time}s: {error_msg}", flush=True)
        print(f"[WORKER] ════════════════════════════════════════", flush=True)
        
        # Store detailed error in DB
        with engine.connect() as conn:
            conn.execute(
                text("""
                    UPDATE jobs 
                    SET status = 'failed', 
                        error = :error, 
                        finished_at = :finished_at 
                    WHERE id = :job_id
                """),
                {
                    "error": error_msg,
                    "finished_at": datetime.now(timezone.utc),
                    "job_id": job_id
                }
            )
            conn.commit()
    finally:
        # Cleanup temp files
        for path in [input_path, output_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
