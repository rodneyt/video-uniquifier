import os
import json
from datetime import datetime, timezone
import uuid
from sqlalchemy import create_engine, text
from worker.pipeline import process_video, download_from_r2, upload_to_r2

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def run_job(job_id: str):
    """
    Función principal del worker. Descarga el video, lo procesa y lo sube.
    Actualiza la base de datos en cada paso.
    """
    print(f"Iniciando job {job_id}")
    
    # 1. Obtener job de BD
    with engine.connect() as conn:
        result = conn.execute(text("SELECT input_key FROM jobs WHERE id = :job_id"), {"job_id": job_id}).fetchone()
        if not result:
            print(f"Job {job_id} no encontrado")
            return
        input_key = result[0]
        
        # Marcar como processing
        conn.execute(
            text("UPDATE jobs SET status = 'processing' WHERE id = :job_id"),
            {"job_id": job_id}
        )
        conn.commit()

    temp_dir = "/tmp/video_jobs"
    os.makedirs(temp_dir, exist_ok=True)
    
    input_path = os.path.join(temp_dir, f"in_{job_id}.mp4")
    output_path = os.path.join(temp_dir, f"out_{job_id}.mp4")
    
    output_key = f"outputs/{job_id}.mp4"

    try:
        # 2. Descargar de R2
        print(f"Descargando {input_key} desde R2...")
        download_from_r2(input_key, input_path)
        
        # 3. Procesar video
        print("Procesando video...")
        params = process_video(input_path, output_path)
        
        # 4. Subir a R2
        print(f"Subiendo a R2 en {output_key}...")
        upload_to_r2(output_path, output_key)
        
        # 5. Actualizar BD como done
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
            
        print(f"Job {job_id} finalizado exitosamente.")
        
    except Exception as e:
        print(f"Error en job {job_id}: {str(e)}")
        # Actualizar BD como failed
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE jobs SET status = 'failed', error = :error, finished_at = :finished_at WHERE id = :job_id"),
                {
                    "error": str(e),
                    "finished_at": datetime.now(timezone.utc),
                    "job_id": job_id
                }
            )
            conn.commit()
    finally:
        # Limpiar temporales
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
