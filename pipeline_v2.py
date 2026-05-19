"""
Pipeline v3.0 — Particles + Simplified Core
No more darkening filters. Particle overlay is the key technique.
"""
import os, json, uuid, random, subprocess, time, math, shutil
from particles_overlay import generate_frames, choose_preset

PIPELINE_VERSION = "3.0-particles"


def probe_video(path):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {"width": 1080, "height": 1920, "has_audio": False, "fps": 30, "duration": 10}
    data = json.loads(r.stdout)
    w, h, has_audio, fps = 1080, 1920, False, 30
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            w = int(s.get("width", 1080))
            h = int(s.get("height", 1920))
            try:
                n, d = s.get("r_frame_rate", "30/1").split("/")
                fps = round(int(n) / int(d), 2)
            except:
                fps = 30
        elif s.get("codec_type") == "audio":
            has_audio = True
    dur = float(data.get("format", {}).get("duration", 10))
    return {"width": w, "height": h, "has_audio": has_audio, "fps": fps, "duration": dur}


def process_video(input_path, output_path, use_nvenc=True):
    """Pipeline v3.0 — particles + simplified core. Never darkens."""
    info = probe_video(input_path)
    w, h, fps = info["width"], info["height"], info["fps"]
    has_audio, duration = info["has_audio"], info["duration"]
    print(f"[PIPE] Video: {w}x{h} @ {fps}fps, audio={has_audio}, dur={duration:.1f}s")

    # ── Random params (NEVER darken: contrast/sat >= 1.0) ──
    zoom = round(random.uniform(1.02, 1.04), 3)
    dx = random.randint(-3, 3)
    dy = random.randint(-3, 3)
    speed = round(random.uniform(1.01, 1.05), 3)
    contrast = round(random.uniform(1.0, 1.05), 3)
    saturation = round(random.uniform(1.0, 1.08), 3)
    hue_shift = random.randint(-3, 3)
    do_mirror = random.random() < 0.25
    noise_level = random.randint(2, 5)

    # Frame trim
    trim_start = random.randint(1, 3)
    trim_start_sec = round(trim_start / fps, 4)
    trim_end = random.randint(1, 3)
    trim_end_sec = round(trim_end / fps, 4)
    target_dur = round(duration - trim_start_sec - trim_end_sec, 4)

    # Audio
    pitch_factor = round(random.uniform(0.985, 1.015), 4)
    pitch_rate = round(44100 * pitch_factor)  # Pre-calculated LITERAL

    # ── Generate particle overlay PNGs ──
    particle_dir = os.path.join(os.path.dirname(output_path), f"_particles_{uuid.uuid4().hex[:6]}")
    num_particle_frames = min(60, max(30, int(duration * fps / 2)))
    particle_info = generate_frames(particle_dir, w, h, num_particle_frames)

    p = {
        "pipeline_version": PIPELINE_VERSION,
        "zoom": zoom, "dx": dx, "dy": dy, "speed": speed,
        "contrast": contrast, "saturation": saturation, "hue": hue_shift,
        "mirror": do_mirror, "noise": noise_level,
        "trim_start": trim_start, "trim_end": trim_end,
        "pitch_factor": pitch_factor, "pitch_rate": pitch_rate,
        "particles": particle_info,
        "original_size": f"{w}x{h}", "fps": fps, "has_audio": has_audio,
    }
    print(f"[PIPE] zoom={zoom} speed={speed} c={contrast} s={saturation} h={hue_shift} mirror={do_mirror}")
    print(f"[PIPE] Particles: {particle_info['preset']} ({particle_info['particle_count']})")

    # ── Video filter chain (simplified — no darkening) ──
    crop_w, crop_h = int(w / zoom), int(h / zoom)
    crop_x = max(0, min(int((w - crop_w) / 2 + dx), w - crop_w))
    crop_y = max(0, min(int((h - crop_h) / 2 + dy), h - crop_h))

    vf = [
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
        f"scale={w}:{h}",
        f"eq=contrast={contrast}:saturation={saturation}",
    ]
    if hue_shift != 0:
        vf.append(f"hue=h={hue_shift}")
    if do_mirror:
        vf.append("hflip")
    vf.append(f"noise=c0s={noise_level}:c1s={max(1,noise_level-1)}:c2s={noise_level}:allf=t")
    vf.append(f"setpts=PTS/{speed}")

    # Filter complex: process video → overlay particles
    fc = f"[0:v]{','.join(vf)}[processed];"
    fc += "[processed][1:v]overlay=0:0:format=auto:shortest=1[v_final]"

    # Audio filter chain
    if has_audio:
        audio_speed = max(0.5, min(speed, 2.0))
        fc += f";[0:a]atempo={audio_speed:.3f},asetrate={pitch_rate},aresample=44100[a_final]"

    unique_title = f"clip-{uuid.uuid4().hex[:8]}"

    # ── Build command ──
    cmd = ["ffmpeg", "-y"]

    # Input 0: video (with trim)
    if trim_start_sec > 0:
        cmd.extend(["-ss", str(trim_start_sec)])
    cmd.extend(["-i", input_path])
    if target_dur > 1:
        cmd.extend(["-t", str(target_dur)])

    # Input 1: particle PNGs (looped)
    particle_pattern = os.path.join(particle_dir, "%03d.png")
    cmd.extend(["-framerate", str(int(fps)), "-stream_loop", "-1", "-i", particle_pattern])

    cmd.extend(["-filter_complex", fc, "-map", "[v_final]"])
    if has_audio:
        cmd.extend(["-map", "[a_final]"])

    if use_nvenc:
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr",
                     "-cq", "18", "-b:v", "10M", "-profile:v", "high", "-pix_fmt", "yuv420p"])
        p["encoder"] = "nvenc_rtx4090"
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                     "-profile:v", "high", "-pix_fmt", "yuv420p"])
        p["encoder"] = "libx264"

    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    cmd.extend(["-map_metadata", "-1",
                "-metadata", f"title={unique_title}",
                "-metadata", f"comment={uuid.uuid4().hex}",
                "-movflags", "+faststart", output_path])

    # ── Execute ──
    encoder = "NVENC-p6" if use_nvenc else "x264"
    print(f"[PIPE] Encoding ({encoder})...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - start, 1)

    if result.returncode != 0 and use_nvenc:
        print(f"[PIPE] NVENC failed, CPU fallback...")
        # Swap encoder only
        cmd2 = [c for c in cmd]
        # Find and replace NVENC args
        for i, c in enumerate(cmd2):
            if c == "h264_nvenc": cmd2[i] = "libx264"
            if c == "p6": cmd2[i] = "medium"
            if c == "vbr": cmd2[i] = "crf"
            if c == "-cq": cmd2[i] = "-crf"
            if c == "-b:v": cmd2[i] = "-maxrate"; 
        result = subprocess.run(cmd2, capture_output=True, text=True)
        elapsed = round(time.time() - start, 1)
        p["encoder"] = "libx264_fallback"
        if result.returncode != 0:
            # Clean up particles before raising
            shutil.rmtree(particle_dir, ignore_errors=True)
            raise Exception(f"FFmpeg failed: {result.stderr[-500:]}")
    elif result.returncode != 0:
        shutil.rmtree(particle_dir, ignore_errors=True)
        raise Exception(f"FFmpeg failed: {result.stderr[-500:]}")

    # Cleanup particle PNGs
    shutil.rmtree(particle_dir, ignore_errors=True)

    out_size = os.path.getsize(output_path)
    print(f"[PIPE] Done in {elapsed}s — {out_size / 1024 / 1024:.1f} MB")
    p["ffmpeg_duration_s"] = elapsed
    return p
