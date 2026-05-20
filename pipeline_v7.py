"""
Pipeline v7.0 — Ultimate Evasion (Ghost Overlay & PIP Corner)
Combines V6 Core + Particle system + Dynamic Video Overlays to destroy optical flow.
"""
import os, json, uuid, random, subprocess, time, shutil
from particles_overlay import generate_frames

PIPELINE_VERSION = "7.0-ultimate-evasion"
OVERLAYS_DIR = "assets/overlays"

def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_streams", "-show_format", path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"w": 1080, "h": 1920, "audio": False, "fps": 30, "dur": 10}
    d = json.loads(r.stdout)
    w, h, audio, fps = 1080, 1920, False, 30
    for s in d.get("streams", []):
        if s.get("codec_type") == "video":
            w, h = int(s.get("width", 1080)), int(s.get("height", 1920))
            try:
                n, dn = s.get("r_frame_rate", "30/1").split("/")
                fps = round(int(n) / int(dn), 2)
            except: pass
        elif s.get("codec_type") == "audio":
            audio = True
    dur = float(d.get("format", {}).get("duration", 10))
    return {"w": w, "h": h, "audio": audio, "fps": fps, "dur": dur}

def get_random_overlay():
    if not os.path.exists(OVERLAYS_DIR):
        return None
    files = [f for f in os.listdir(OVERLAYS_DIR) if f.endswith(".mp4")]
    if not files:
        return None
    return os.path.join(OVERLAYS_DIR, random.choice(files))

def process_video(input_path, output_path, use_nvenc=True):
    info = _probe(input_path)
    w, h, fps = info["w"], info["h"], info["fps"]
    has_audio, duration = info["audio"], info["dur"]
    print(f"[V7] {w}x{h} @{fps}fps audio={has_audio} dur={duration:.1f}s")

    # ── 1-6. Core params (NO darkening) ──
    zoom = round(random.uniform(1.02, 1.04), 3)
    dx, dy = random.randint(-3, 3), random.randint(-3, 3)
    speed = round(random.uniform(1.01, 1.05), 3)
    contrast = round(random.uniform(1.0, 1.05), 3)
    saturation = round(random.uniform(1.0, 1.08), 3)
    hue_shift = random.randint(-3, 3)
    do_mirror = random.random() < 0.25

    # ── Ultimate Evasion params ──
    overlay_vid = get_random_overlay()
    do_ghost = overlay_vid and random.random() < 0.70  # 70% chance full screen 3% opacity
    do_pip = overlay_vid and random.random() < 0.50    # 50% chance small corner PIP

    ghost_opacity = round(random.uniform(0.015, 0.035), 3)
    pip_scale_w = int(w * random.uniform(0.15, 0.25))
    pip_scale_w = (pip_scale_w // 2) * 2  # even
    pip_scale_h = -2 # maintain aspect ratio
    pip_corner = random.choice(["tl", "tr", "bl", "br"])

    # Audio
    pitch_rate = round(44100 * random.uniform(0.985, 1.015))

    # ── Generate particle overlay PNGs ──
    particle_dir = os.path.join(os.path.dirname(output_path), f"_particles_{uuid.uuid4().hex[:6]}")
    particle_dir_ff = particle_dir.replace("\\", "/")
    
    num_particle_frames = min(60, max(30, int(duration * fps / 2)))
    particle_info = generate_frames(particle_dir, w, h, num_particle_frames)

    p = {
        "pipeline_version": PIPELINE_VERSION,
        "zoom": zoom, "speed": speed, "contrast": contrast,
        "saturation": saturation, "hue": hue_shift, "mirror": do_mirror,
        "particles": particle_info,
        "ghost_overlay": do_ghost, "ghost_opacity": ghost_opacity,
        "pip_corner": do_pip, "pip_pos": pip_corner if do_pip else None,
        "pitch_rate": pitch_rate,
        "original_size": f"{w}x{h}", "fps": fps, "has_audio": has_audio,
    }
    
    # ── Build video filter chain ──
    crop_w, crop_h = int(w / zoom), int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + dx), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + dy), h - crop_h))

    vf = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={w}:{h}",
        f"eq=contrast={contrast}:saturation={saturation}"
    ]
    if hue_shift != 0: vf.append(f"hue=h={hue_shift}")
    if do_mirror: vf.append("hflip")
    vf.append(f"setpts=PTS/{speed}")

    fc = f"[0:v]{','.join(vf)}[base];"

    # Input 1 is particles, Input 2 is overlay video (if used)
    # 1. Add Ghost Overlay
    current_out = "[base]"
    if overlay_vid and (do_ghost or do_pip):
        # Format input 2 (overlay video)
        fc += f"[2:v]format=rgba[ov];"
        
        if do_ghost:
            # Full screen ghost overlay
            fc += f"[ov]scale={w}:{h},colorchannelmixer=aa={ghost_opacity}[ghost];"
            fc += f"{current_out}[ghost]overlay=0:0:shortest=1[with_ghost];"
            current_out = "[with_ghost]"
            
        if do_pip:
            # Small PIP in corner
            fc += f"[ov]scale={pip_scale_w}:{pip_scale_h}[pip];"
            x = "10" if pip_corner.startswith("t") or pip_corner.startswith("b") and pip_corner.endswith("l") else "W-w-10"
            y = "10" if pip_corner.startswith("t") else "H-h-10"
            if pip_corner.startswith("b"): y = "H-h-10"
            fc += f"{current_out}[pip]overlay={x}:{y}:shortest=1[with_pip];"
            current_out = "[with_pip]"

    # 2. Add Particles
    fc += f"{current_out}[1:v]overlay=0:0:format=auto:shortest=1[v_final]"

    # ── Audio filter chain ──
    if has_audio:
        af = [f"atempo={max(0.5, min(speed, 2.0)):.3f}",
              f"asetrate={pitch_rate}", "aresample=44100"]
        fc += f";[0:a]{','.join(af)}[a_final]"

    # ── Build command ──
    title = f"clip-{uuid.uuid4().hex[:8]}"
    cmd = ["ffmpeg", "-y", "-i", input_path]

    # Input 1: particle PNGs
    particle_pattern = f"{particle_dir_ff}/%03d.png"
    cmd.extend(["-framerate", str(int(fps)), "-stream_loop", "-1", "-i", particle_pattern])

    # Input 2: Overlay video (if needed)
    if overlay_vid and (do_ghost or do_pip):
        cmd.extend(["-stream_loop", "-1", "-i", overlay_vid])

    cmd.extend(["-filter_complex", fc, "-map", "[v_final]"])
    if has_audio: cmd.extend(["-map", "[a_final]"])

    nvenc_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
                  "-cq", "20", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    cpu_args = ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-profile:v", "high", "-pix_fmt", "yuv420p"]

    if use_nvenc:
        cmd.extend(nvenc_args)
        p["encoder"] = "nvenc"
    else:
        cmd.extend(cpu_args)
        p["encoder"] = "x264"

    if has_audio: cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(["-map_metadata", "-1", "-metadata", f"title={title}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-movflags", "+faststart", output_path])

    # ── Execute ──
    print(f"[V7] Encoding ({'NVENC' if use_nvenc else 'CPU'})...")
    print(f"[V7] Ghost: {do_ghost} | PIP: {do_pip}")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    if result.returncode != 0:
        err = result.stderr[-600:] if result.stderr else "unknown"
        if use_nvenc:
            print(f"[V7] NVENC failed, CPU fallback...")
            cmd2 = [c for c in cmd]
            for i in range(len(cmd2)):
                if cmd2[i] == "h264_nvenc": cmd2[i] = "libx264"
                elif cmd2[i] == "p4": cmd2[i] = "medium"
                elif cmd2[i] == "vbr":
                    cmd2[i-1] = "-crf"
                    cmd2[i] = "20"
                elif cmd2[i] == "-cq": cmd2[i] = "-qp"
            cmd2 = [c for j, c in enumerate(cmd2)
                    if c != "-b:v" and (j == 0 or cmd2[j-1] != "-b:v")]
            result = subprocess.run(cmd2, capture_output=True, text=True)
            elapsed = round(time.time() - start, 1)
            p["encoder"] = "x264_fallback"
            if result.returncode != 0:
                shutil.rmtree(particle_dir, ignore_errors=True)
                raise Exception(f"FFmpeg CPU failed: {result.stderr[-500:]}")
        else:
            shutil.rmtree(particle_dir, ignore_errors=True)
            raise Exception(f"FFmpeg failed: {err}")

    # Cleanup particles
    shutil.rmtree(particle_dir, ignore_errors=True)

    out_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"[V7] Done in {elapsed}s — {out_mb:.1f} MB")
    p["encode_time"] = elapsed
    return p
