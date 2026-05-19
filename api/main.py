import os
import uuid
import boto3
from datetime import timedelta, datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from redis import Redis
from rq import Queue

from api.database import Base, engine, get_db
from api.models import User, Job
from api.auth import get_password_hash, verify_password, create_access_token, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES
from shared.schemas import UserCreate, UserResponse, Token, JobCreate, JobResponse
from pydantic import BaseModel
from typing import Optional

# Configuración Base de datos
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Video Uniquifier API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración Redis & RQ
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_conn = Redis.from_url(REDIS_URL)
q = Queue("video_jobs", connection=redis_conn)

# Configuración R2
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

# --- AUTH ROUTES ---

@app.post("/auth/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user_in.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user_in.password)
    new_user = User(email=user_in.email, password_hash=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.id}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# --- UPLOADS ---

@app.post("/uploads/presign")
def generate_presigned_url(current_user: User = Depends(get_current_user)):
    """Genera URL prefirmada para subir video directamente a R2"""
    ext = ".mp4"
    file_key = f"uploads/{current_user.id}/{uuid.uuid4().hex}{ext}"
    
    try:
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': R2_BUCKET, 'Key': file_key, 'ContentType': 'video/mp4'},
            ExpiresIn=3600
        )
        return {"upload_url": presigned_url, "file_key": file_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- JOBS ---

def check_rate_limit(user_id: str, db: Session):
    """Límite de rate: 10 jobs por hora en plan free"""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    count = db.query(Job).filter(
        Job.user_id == user_id,
        Job.created_at >= one_hour_ago
    ).count()
    if count >= 10:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 10 jobs per hour.")

@app.post("/jobs", response_model=JobResponse)
def create_job(job_in: JobCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.plan == "free":
        check_rate_limit(current_user.id, db)
        
    new_job = Job(
        user_id=current_user.id,
        input_key=job_in.input_key,
        status="queued"
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    
    # Encolar en RQ
    q.enqueue("worker.main.run_job", new_job.id, job_timeout='1h')
    
    return new_job

@app.get("/jobs", response_model=list[JobResponse])
def list_jobs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.user_id == current_user.id).order_by(Job.created_at.desc()).all()
    return jobs

@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Inject download URL if done
    job_dict = {
        "id": job.id,
        "user_id": job.user_id,
        "input_key": job.input_key,
        "output_key": job.output_key,
        "status": job.status,
        "params_json": job.params_json,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at
    }
    
    if job.status == "done" and job.output_key:
        try:
            presigned_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': R2_BUCKET, 'Key': job.output_key},
                ExpiresIn=3600
            )
            # Add dynamically
            job_dict["download_url"] = presigned_url
        except Exception:
            pass
            
    return job_dict

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    db.delete(job)
    db.commit()
    return {"detail": "Job deleted"}

@app.get("/health")
def health_check():
    """Health check - also shows worker status"""
    try:
        worker_count = len(redis_conn.smembers("rq:workers"))
        queue_size = q.count
        return {
            "status": "ok",
            "workers": worker_count,
            "queue_size": queue_size
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/admin/cleanup")
def cleanup_stuck_jobs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Reset stuck processing/queued jobs to failed"""
    stuck = db.query(Job).filter(
        Job.user_id == current_user.id,
        Job.status.in_(["processing", "queued"])
    ).all()
    count = 0
    for job in stuck:
        job.status = "failed"
        job.error = "Reset: job was stuck"
        count += 1
    db.commit()
    return {"detail": f"Reset {count} stuck jobs"}

@app.post("/admin/retry-failed")
def retry_failed_jobs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-enqueue all failed jobs for reprocessing"""
    failed = db.query(Job).filter(
        Job.user_id == current_user.id,
        Job.status == "failed"
    ).all()
    count = 0
    for job in failed:
        job.status = "queued"
        job.error = None
        job.finished_at = None
        q.enqueue("worker.main.run_job", job.id, job_timeout='1h')
        count += 1
    db.commit()
    return {"detail": f"Re-enqueued {count} failed jobs"}


# --- WORKER ENDPOINTS (for local worker) ---

class WorkerJobUpdate(BaseModel):
    status: str
    output_key: Optional[str] = None
    params_json: Optional[str] = None
    error: Optional[str] = None

@app.put("/worker/update-job/{job_id}")
def worker_update_job(
    job_id: str, 
    update: WorkerJobUpdate, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Endpoint for local worker to update job status."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.status = update.status
    if update.output_key:
        job.output_key = update.output_key
    if update.params_json:
        job.params_json = update.params_json
    if update.error:
        job.error = update.error
    if update.status in ["done", "failed"]:
        job.finished_at = datetime.now(timezone.utc)
    
    db.commit()
    return {"detail": f"Job {job_id} updated to {update.status}"}

@app.get("/worker/download-url/{job_id}")
def worker_get_download_url(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get presigned download URL for a job's input video."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET, 'Key': job.input_key},
            ExpiresIn=3600
        )
        return {"download_url": url, "input_key": job.input_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/worker/upload-url/{job_id}")
def worker_get_upload_url(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get presigned upload URL for a job's output video."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    output_key = f"outputs/{job_id}.mp4"
    try:
        url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': R2_BUCKET, 'Key': output_key, 'ContentType': 'video/mp4'},
            ExpiresIn=3600
        )
        return {"upload_url": url, "output_key": output_key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
