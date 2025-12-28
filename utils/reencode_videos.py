#!/usr/bin/env python3
"""
Re-encode videos to H.264/AAC for QuickTime compatibility.

This script converts VP9/AV1/Opus videos to H.264/AAC which plays
everywhere (QuickTime, iOS, Windows, etc.)

Usage:
    python reencode_videos.py
"""

import os
import subprocess
import sys
from pathlib import Path


def check_ffmpeg():
    """Check if ffmpeg is installed."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            print(f"✓ {version_line}")
            return True
    except FileNotFoundError:
        pass
    
    print("✗ FFmpeg not found!")
    print("  Install with: brew install ffmpeg")
    return False


def get_video_info(path: Path) -> dict:
    """Get video codec information using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            info = {"video_codec": None, "audio_codec": None}
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    info["video_codec"] = stream.get("codec_name")
                elif stream.get("codec_type") == "audio":
                    info["audio_codec"] = stream.get("codec_name")
            return info
    except Exception as e:
        print(f"  Warning: Could not probe {path}: {e}")
    
    return {"video_codec": "unknown", "audio_codec": "unknown"}


def needs_reencoding(info: dict) -> tuple[bool, str]:
    """Check if video needs re-encoding for QuickTime compatibility."""
    video_codec = info.get("video_codec", "").lower()
    audio_codec = info.get("audio_codec", "").lower()
    
    reasons = []
    
    # QuickTime doesn't support VP9, AV1
    if video_codec in ("vp9", "vp8", "av1", "av01"):
        reasons.append(f"video codec '{video_codec}' not QuickTime compatible")
    
    # QuickTime doesn't support Opus, Vorbis
    if audio_codec in ("opus", "vorbis"):
        reasons.append(f"audio codec '{audio_codec}' not QuickTime compatible")
    
    if reasons:
        return True, "; ".join(reasons)
    
    return False, "Already compatible (H.264/AAC)"


def reencode_video(input_path: Path, output_path: Path) -> bool:
    """Re-encode video to H.264/AAC."""
    print(f"  🔄 Re-encoding to H.264/AAC...")
    
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-c:v", "libx264",       # H.264 video codec
        "-preset", "medium",     # Encoding speed/quality tradeoff
        "-crf", "23",            # Quality (lower = better, 18-28 is good)
        "-c:a", "aac",           # AAC audio codec
        "-b:a", "192k",          # Audio bitrate
        "-movflags", "+faststart",  # Enable streaming
        "-y",                    # Overwrite output
        str(output_path),
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"  ✗ FFmpeg error: {result.stderr[:200]}")
            return False
            
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def main():
    print("=" * 60)
    print("Video Re-encoder for QuickTime Compatibility")
    print("=" * 60)
    
    if not check_ffmpeg():
        return 1
    
    # Find videos in test_downloads
    video_dir = Path("./test_downloads")
    if not video_dir.exists():
        print(f"✗ Directory not found: {video_dir}")
        return 1
    
    # Create output directory
    output_dir = Path("./test_downloads_compatible")
    output_dir.mkdir(exist_ok=True)
    print(f"✓ Output directory: {output_dir.absolute()}")
    print()
    
    # Process each video
    videos = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.webm"))
    
    if not videos:
        print("No videos found in ./test_downloads/")
        return 1
    
    success_count = 0
    skip_count = 0
    
    for video in videos:
        print(f"📹 {video.name}")
        
        # Check codec
        info = get_video_info(video)
        print(f"   Video: {info['video_codec']}, Audio: {info['audio_codec']}")
        
        needs_reencode, reason = needs_reencoding(info)
        
        if needs_reencode:
            print(f"   ⚠️  {reason}")
            
            output_path = output_dir / f"{video.stem}_h264.mp4"
            
            if reencode_video(video, output_path):
                new_size = output_path.stat().st_size / (1024 * 1024)
                old_size = video.stat().st_size / (1024 * 1024)
                print(f"   ✓ Saved: {output_path.name} ({new_size:.1f} MB, was {old_size:.1f} MB)")
                success_count += 1
            else:
                print(f"   ✗ Failed to re-encode")
        else:
            print(f"   ✓ {reason}")
            # Copy compatible file
            import shutil
            output_path = output_dir / video.name
            shutil.copy2(video, output_path)
            skip_count += 1
        
        print()
    
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Re-encoded: {success_count}")
    print(f"Already compatible: {skip_count}")
    print(f"\nQuickTime-compatible videos saved to: {output_dir.absolute()}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

