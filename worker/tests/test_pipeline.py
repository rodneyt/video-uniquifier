import pytest
import os
import cv2
import uuid
import numpy as np
from pathlib import Path
from worker.pipeline import process_video

@pytest.fixture
def dummy_video(tmp_path):
    """Crea un video dummy de 1080x1920 para testing"""
    file_path = str(tmp_path / "input.mp4")
    out = cv2.VideoWriter(
        file_path, 
        cv2.VideoWriter_fourcc(*'mp4v'), 
        30.0, 
        (1080, 1920)
    )
    for _ in range(30): # 1 segundo
        frame = np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)
        out.write(frame)
    out.release()
    return file_path

def test_pipeline_output_exists_and_valid(dummy_video, tmp_path):
    output_path = str(tmp_path / "output.mp4")
    
    # Run pipeline
    params = process_video(dummy_video, output_path)
    
    assert os.path.exists(output_path), "El video de salida no fue creado"
    
    # Verificar que el video de salida se puede leer y tiene dimensiones correctas
    cap = cv2.VideoCapture(output_path)
    assert cap.isOpened(), "El video de salida no se puede abrir"
    
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    assert width == 1080, f"Ancho incorrecto: {width}"
    assert height == 1920, f"Alto incorrecto: {height}"
    
    # Validar que los params aleatorios fueron devueltos
    assert "zoom" in params
    assert "dx" in params
    assert "speed" in params
    
    cap.release()
