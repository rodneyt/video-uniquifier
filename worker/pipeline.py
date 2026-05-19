import os
import uuid
import random
import subprocess
import json
from pathlib import Path
import cv2
import pytesseract
import boto3
from urllib.parse import urlparse

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

def has_text_in_video(video_path: str) -> bool:
    """
    Samplea frames del video y usa OCR (Tesseract) para detectar texto.
    Retorna True si encuentra texto, False en caso contrario.
    """
    cap = cv2.VideoCapture(video_path)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if frame_count == 0 or fps == 0:
        return False
        
    # Extraer hasta 5 frames distribuidos uniformemente
    samples = 5
    step = max(1, frame_count // samples)
    
    text_found = False
    for i in range(0, frame_count, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if not ret:
            break
            
        # Convertir a escala de grises para mejorar OCR
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        text = pytesseract.image_to_string(gray).strip()
        if len(text) > 3: # Si hay más de 3 caracteres, asumimos que hay texto
            text_found = True
            break
            
    cap.release()
    return text_found

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
    """
    # 1. Generar parámetros aleatorios
    zoom = round(random.uniform(1.02, 1.04), 3)
    dx = random.randint(-3, 3)
    dy = random.randint(-3, 3)
    speed = round(random.uniform(1.01, 1.05), 3)
    contrast = round(random.uniform(0.98, 1.04), 3)
    saturation = round(random.uniform(0.97, 1.05), 3)
    hue = random.randint(-4, 4)
    noise = random.randint(4, 9)
    pitch = round(random.uniform(0.97, 1.03), 3)
    
    lut_path = get_random_lut()
    lut_opacity = round(random.uniform(0.15, 0.30), 2)
    
    # 2. Determinar si se puede hacer flip horizontal
    can_flip = False
    if not has_text_in_video(input_path):
        can_flip = random.random() < 0.25 # 25% probabilidad

    params = {
        "zoom": zoom,
        "dx": dx,
        "dy": dy,
        "speed": speed,
        "contrast": contrast,
        "saturation": saturation,
        "hue": hue,
        "noise": noise,
        "pitch": pitch,
        "lut": Path(lut_path).name if lut_path else None,
        "lut_opacity": lut_opacity,
        "hflip": can_flip
    }

    # 3. Construir el grafo de filtros complejos de FFmpeg
    # Dimensiones originales asumidas: 1080x1920
    # Calculamos el crop para el micro-zoom
    crop_w = int(1080 / zoom)
    crop_h = int(1920 / zoom)
    crop_x = int((1080 - crop_w) / 2 + dx)
    crop_y = int((1920 - crop_h) / 2 + dy)
    
    # Asegurar que el crop no se salga de los bordes
    crop_x = max(0, min(crop_x, 1080 - crop_w))
    crop_y = max(0, min(crop_y, 1920 - crop_h))

    v_filters = []
    
    # Aplicar crop y scale (esto hace el micro-zoom y el offset)
    v_filters.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale=1080:1920")
    
    # Color grading: eq (contrast + saturation only)
    v_filters.append(f"eq=contrast={contrast}:saturation={saturation}")
    
    # Hue shift (separate filter)
    if hue != 0:
        v_filters.append(f"hue=h={hue}")
    
    # Ruido / Film grain
    v_filters.append(f"noise=alls={noise}:allf=t")
    
    # Flip horizontal
    if can_flip:
        v_filters.append("hflip")
        
    # Cambio de velocidad de video
    # PTS se divide por la velocidad
    v_filters.append(f"setpts=PTS/{speed}")

    v_filter_chain = ",".join(v_filters)
    
    # Si tenemos LUT, usamos un split y blend para la opacidad
    if lut_path:
        # Aseguramos de escapar la ruta del LUT
        lut_escaped = lut_path.replace("'", "\\\\'")
        # Cadena de video:
        # [0:v] filtro_base [v_base];
        # [v_base] split [v_orig][v_lut_in];
        # [v_lut_in] lut3d='LUT' [v_lut_out];
        # [v_orig][v_lut_out] blend... [v_out]
        
        filter_complex = f"[0:v]{v_filter_chain}[v_base];"
        filter_complex += f"[v_base]split[v_orig][v_lut_in];"
        filter_complex += f"[v_lut_in]lut3d='{lut_escaped}'[v_lut_out];"
        # Blend con opacidad: A es orig, B es lut
        filter_complex += f"[v_orig][v_lut_out]blend=all_expr='A*(1-{lut_opacity})+B*{lut_opacity}'[v_final]"
        v_out_map = "[v_final]"
    else:
        filter_complex = f"[0:v]{v_filter_chain}[v_final]"
        v_out_map = "[v_final]"

    # Audio filter
    # Cambio de velocidad (atempo) y pitch sutil (asetrate + aresample)
    # Asumimos sample rate 44100 para el aresample final
    a_filter_chain = f"atempo={speed},asetrate=44100*{pitch},aresample=44100"
    filter_complex += f";[0:a]{a_filter_chain}[a_final]"
    a_out_map = "[a_final]"

    # 4. Construir comando FFmpeg
    # Encoding final OBLIGATORIO:
    # -c:v libx264 -preset slow -crf 18 -profile:v high 
    # -pix_fmt yuv420p -c:a aac -b:a 192k -map_metadata -1
    # -metadata title=clip-{uuid8}
    
    unique_title = f"clip-{uuid.uuid4().hex[:8]}"

    cmd = [
        "ffmpeg",
        "-y", # Sobrescribir
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", v_out_map,
        "-map", a_out_map,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map_metadata", "-1",
        "-metadata", f"title={unique_title}",
        output_path
    ]
    
    print(f"Ejecutando FFmpeg: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr[-500:]}", flush=True)
        raise Exception(f"FFmpeg falló con código {result.returncode}")
    else:
        print("FFmpeg completado exitosamente.", flush=True)

    return params

def download_from_r2(key: str, dest_path: str):
    s3_client.download_file(R2_BUCKET, key, dest_path)

def upload_to_r2(file_path: str, key: str):
    s3_client.upload_file(file_path, R2_BUCKET, key)
