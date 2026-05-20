"""
Batch Video Processor — Local bulk processing tool

Usage:
    python batch_process.py "D:\path\to\videos"
    python batch_process.py "D:\path\to\videos" --limit 50

- Finds all .mp4 files in the given folder
- Creates a subfolder called "processed" inside it
- Processes each video through Pipeline V9 (Horizontal 4K + Blur BG)
- Shows progress and summary at the end
"""
import os, sys, time, glob, argparse
from pipeline_v9 import process_video


def main():
    parser = argparse.ArgumentParser(description="Batch process videos for TikTok bypass")
    parser.add_argument("folder", help="Path to folder containing .mp4 files")
    parser.add_argument("--limit", type=int, default=100, help="Max videos to process (default: 100)")
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print(f"[ERROR] Folder not found: {folder}")
        sys.exit(1)

    # Find all mp4 files (not in the processed subfolder)
    all_mp4 = []
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith(".mp4"):
            full = os.path.join(folder, f)
            if os.path.isfile(full):
                all_mp4.append(full)

    if not all_mp4:
        print(f"[ERROR] No .mp4 files found in: {folder}")
        sys.exit(1)

    videos = all_mp4[:args.limit]
    total = len(videos)

    # Create output folder
    out_dir = os.path.join(folder, "processed")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  BATCH VIDEO PROCESSOR")
    print(f"  Pipeline: v9 (Horizontal 4K + Blur BG)")
    print(f"  Input:  {folder}")
    print(f"  Output: {out_dir}")
    print(f"  Videos: {total}" + (f" (limited from {len(all_mp4)})" if len(all_mp4) > total else ""))
    print(f"{'='*60}\n")

    results = {"ok": 0, "fail": 0, "skipped": 0}
    batch_start = time.time()

    for i, input_path in enumerate(videos, 1):
        filename = os.path.basename(input_path)
        name, ext = os.path.splitext(filename)
        output_path = os.path.join(out_dir, f"{name}_4k{ext}")

        # Skip if already processed
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"[{i}/{total}] SKIP (already exists): {filename}")
            results["skipped"] += 1
            continue

        print(f"\n[{i}/{total}] Processing: {filename}")
        try:
            start = time.time()
            params = process_video(input_path, output_path, use_nvenc=True)
            elapsed = round(time.time() - start, 1)
            out_mb = os.path.getsize(output_path) / 1024 / 1024
            print(f"[{i}/{total}] OK in {elapsed}s -> {out_mb:.1f} MB")
            results["ok"] += 1
        except Exception as e:
            print(f"[{i}/{total}] FAILED: {str(e)[:200]}")
            results["fail"] += 1
            # Remove broken output
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except:
                pass

    total_time = round(time.time() - batch_start, 1)
    avg = round(total_time / max(results["ok"], 1), 1)

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE")
    print(f"  Total time: {total_time}s ({avg}s average per video)")
    print(f"  OK:      {results['ok']}")
    print(f"  Failed:  {results['fail']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  Output:  {out_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
