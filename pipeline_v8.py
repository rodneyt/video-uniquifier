"""
Pipeline v8.0 — The Nuke (Trim + Noise + 1px Watermark)
Restores critical temporal trimming and audio masking to defeat TikTok 2026.
"""
import os, json, uuid, random, subprocess, time, shutil
from particles_overlay import generate_frames

PIPELINE_VERSION = "8.0-nuke"
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
    if not os.path.exists(OVERLAYS_DIR): return None
    files = [f for f in os.listdir(OVERLAYS_DIR) if f.endswith(".mp4")]
    if not files: return None
    return os.path.join(OVERLAYS_DIR, random.choice(files))

def process_video(input_path, output_path, use_nvenc=True):
    info = _probe(input_path)
    w, h, fps = info["w"], info["h"], info["fps"]
    has_audio, duration = info["audio"], info["dur"]
    
    # ── 1. Temporal Trimming (CRITICAL FOR HASH EVASION) ──
    trim_s = round(random.uniform(0.15, 0.45), 3)
    trim_e = round(random.uniform(0.15, 0.45), 3)
    trimmed_dur = round(duration - trim_s - trim_e, 3)
    if trimmed_dur < 1.0:
        trim_s = trim_e = 0
        trimmed_dur = duration

    # ── 2. Core params ──
    zoom = round(random.uniform(1.03, 1.05), 3)
    dx, dy = random.randint(-4, 4), random.randint(-4, 4)
    speed = round(random.uniform(1.015, 1.045), 3)
    contrast = round(random.uniform(1.02, 1.06), 3)
    saturation = round(random.uniform(1.03, 1.09), 3)
    hue_shift = random.randint(-4, 4)
    do_mirror = random.random() < 0.25

    # ── 3. Overlays ──
    overlay_vid = get_random_overlay()
    ghost_opacity = round(random.uniform(0.02, 0.04), 3)
    
    # Audio
    pitch_rate = round(44100 * random.uniform(0.985, 1.025))

    # Particles
    particle_dir = os.path.join(os.path.dirname(output_path), f"_particles_{uuid.uuid4().hex[:6]}")
    particle_dir_ff = particle_dir.replace("\\", "/")
    num_particle_frames = min(60, max(30, int(trimmed_dur * fps / 2)))
    generate_frames(particle_dir, w, h, num_particle_frames)

    p = {
        "pipeline_version": PIPELINE_VERSION,
        "trim_start": trim_s, "trim_end": trim_e,
        "zoom": zoom, "speed": speed, "pitch_rate": pitch_rate,
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
    
    # 1-pixel invisible watermarks in corners
    vf.append(f"drawbox=x=1:y=1:w=1:h=1:color=black@0.1:t=fill")
    vf.append(f"drawbox=x=w-2:y=1:w=1:h=1:color=white@0.1:t=fill")
    vf.append(f"drawbox=x=1:y=h-2:w=1:h=1:color=white@0.1:t=fill")
    vf.append(f"drawbox=x=w-2:y=h-2:w=1:h=1:color=black@0.1:t=fill")
    
    # Noise/Grain (Subtle)
    grain = random.randint(12, 18)
    vf.append(f"noise=c0s={grain}:c1s={grain-5}:c2s={grain-5}:allf=t")

    vf.append(f"setpts=PTS/{speed}")
    fc = f"[0:v]{','.join(vf)}[base];"

    # Ghost Overlay
    current_out = "[base]"
    if overlay_vid:
        fc += f"[2:v]format=rgba,scale={w}:{h},colorchannelmixer=aa={ghost_opacity}[ghost];"
        fc += f"{current_out}[ghost]overlay=0:0:shortest=1[with_ghost];"
        current_out = "[with_ghost]"

    # Particles
    fc += f"{current_out}[1:v]overlay=0:0:format=auto:shortest=1[v_final]"

    # ── Audio filter chain ──
    if has_audio:
        # Complex audio masking: Pitch shift + Compressor + Background Brown Noise
        af = [
            f"atempo={max(0.5, min(speed, 2.0)):.3f}",
            f"asetrate={pitch_rate}", 
            "aresample=44100",
            "acompressor=threshold=0.1:ratio=2:attack=20:release=250"
        ]
        fc += f";[0:a]{','.join(af)}[a_main];"
        # Generate low volume brown noise to destroy fingerprint (-40dB)
        fc += f"anoisesrc=c=brown:a=0.01:r=44100:d={trimmed_dur}[anoise];"
        fc += f"[a_main][anoise]amix=inputs=2:duration=first:weights=1 0.3[a_final]"

    # ── Build command ──
    title = f"clip-{uuid.uuid4().hex[:8]}"
    cmd = ["ffmpeg", "-y"]
    if trim_s > 0: cmd.extend(["-ss", str(trim_s)])
    cmd.extend(["-i", input_path])
    if trimmed_dur > 1: cmd.extend(["-t", str(trimmed_dur)])

    # Input 1: particle PNGs
    particle_pattern = f"{particle_dir_ff}/%03d.png"
    cmd.extend(["-framerate", str(int(fps)), "-stream_loop", "-1", "-i", particle_pattern])

    # Input 2: Overlay video
    if overlay_vid:
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
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    if result.returncode != 0:
        err = result.stderr[-600:] if result.stderr else "unknown"
        if use_nvenc:
            cmd2 = [c for c in cmd]
            for i in range(len(cmd2)):
                if cmd2[i] == "h264_nvenc": cmd2[i] = "libx264"
                elif cmd2[i] == "p4": cmd2[i] = "medium"
                elif cmd2[i] == "vbr":
                    cmd2[i-1] = "-crf"
                    cmd2[i] = "20"
                elif cmd2[i] == "-cq": cmd2[i] = "-qp"
            cmd2 = [c for j, c in enumerate(cmd2) if c != "-b:v" and (j == 0 or cmd2[j-1] != "-b:v")]
            result = subprocess.run(cmd2, capture_output=True, text=True)
            if result.returncode != 0:
                shutil.rmtree(particle_dir, ignore_errors=True)
                raise Exception(f"FFmpeg CPU failed: {result.stderr[-500:]}")
        else:
            shutil.rmtree(particle_dir, ignore_errors=True)
            raise Exception(f"FFmpeg failed: {err}")

    shutil.rmtree(particle_dir, ignore_errors=True)
    p["encode_time"] = elapsed
    return p
