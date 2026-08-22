import re
import time
import requests
import streamlit as st
from pathlib import Path
from typing import Optional, List, Tuple

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from datastruct import UnifiedAuditReport
from engine import PostInput, audit_post
from rules import APPROVED_LABELS, AMBIGUOUS_LABELS
from ai_engine import audit_post_with_ai

def _secret(key, default=None):
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default

DOWNLOAD_DIR = Path("temp_media")
DOWNLOAD_DIR.mkdir(exist_ok=True)

DEFAULT_MATERIAL_CONNECTION = "paid"

# --- Claim Classifier Integration ---
try:
    from claim_classifier import classify_content_categories
    CLAIM_CLASSIFIER_AVAILABLE = True
except ImportError:
    CLAIM_CLASSIFIER_AVAILABLE = False


def extract_youtube_video_id(url: str) -> Optional[str]:
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    if parsed.netloc in ('youtu.be', 'www.youtu.be'):
        return parsed.path.lstrip('/')
    if parsed.netloc in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        if parsed.path.startswith('/shorts/'):
            return parsed.path.split('/')[2]
        if parsed.path == '/watch':
            return parse_qs(parsed.query).get('v', [None])[0]
        if parsed.path.startswith('/embed/'):
            return parsed.path.split('/')[2]
        if parsed.path.startswith('/v/'):
            return parsed.path.split('/')[2]
    return None


def extract_youtube_channel_info(url: str) -> Tuple[Optional[str], Optional[str]]:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if 'youtube.com' not in parsed.netloc:
        return None, None
        
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return None, None
        
    if path_parts[0].startswith('@'):
        return path_parts[0], None
    if path_parts[0] == 'channel' and len(path_parts) > 1:
        return None, path_parts[1]
    if path_parts[0] in ('c', 'user') and len(path_parts) > 1:
        return path_parts[1], None
        
    return None, None


def parse_iso8601_duration(duration_str: str) -> int:
    pattern = re.compile(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?')
    match = pattern.match(duration_str)
    if not match:
        return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    return hours * 3600 + minutes * 60 + seconds


def download_asset(url: str, filename: str) -> Optional[Path]:
    target_path = DOWNLOAD_DIR / filename
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return target_path
    except Exception as e:
        print(f"    [!] Failed to download thumbnail {filename}: {e}")
        return None


def process_image_ocr(file_path: Path) -> dict:
    if not OCR_AVAILABLE:
        return {"visual_status": "OCR_NOT_INSTALLED", "labels_found": [], "extracted_text": ""}
    try:
        img = Image.open(file_path)
        raw_text = pytesseract.image_to_string(img)
        clean_text = " ".join(raw_text.split()).lower()

        if not clean_text:
            return {"visual_status": "NO_TEXT_DETECTED", "labels_found": [], "extracted_text": ""}

        all_labels = APPROVED_LABELS + AMBIGUOUS_LABELS
        found_labels = [lbl for lbl in all_labels if lbl in clean_text]

        if found_labels:
            return {"visual_status": "DISCLOSURE_VISIBLE", "labels_found": found_labels, "extracted_text": clean_text}

        return {"visual_status": "TEXT_NO_DISCLOSURE", "labels_found": [], "extracted_text": clean_text}
    except Exception as e:
        return {"visual_status": "ERROR", "labels_found": [], "extracted_text": str(e)}


def fetch_single_yt_video(
    video_id: str, 
    api_key: str, 
    enable_ai: bool = False, 
    provider: str = "ollama",
    model_name: str = _secret("OLLAMA_MODEL_NAME", "qwen3:8b"), 
    base_url: str = "http://localhost:11434", 
    ai_api_key: Optional[str] = None
) -> Optional[UnifiedAuditReport]:
    """
    Fetches details of a single YouTube video by ID and performs traditional rules + optional AI audits.
    """
    if not api_key:
        raise ValueError("YouTube API Key is missing.")

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,contentDetails",
        "id": video_id,
        "key": api_key
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[!] YouTube API request failed: {e}")
        return None

    items = data.get("items", [])
    if not items:
        return None
    
    video_data = items[0]
    snippet = video_data.get("snippet", {})
    content_details = video_data.get("contentDetails", {})
    
    duration_iso = content_details.get("duration", "PT0S")
    duration_sec = parse_iso8601_duration(duration_iso)
    
    content_type = "youtube_short" if duration_sec <= 60 else "video"
    caption = snippet.get("description", "")
    influencer_handle = snippet.get("channelTitle", "Unknown Channel")
    timestamp = snippet.get("publishedAt", "")
    post_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Auto-detect claims
    content_categories = []
    if CLAIM_CLASSIFIER_AVAILABLE:
        content_categories = classify_content_categories(caption)

    # Caption audit
    post_input = PostInput(
        platform="YouTube",
        content_type=content_type,
        material_connection=DEFAULT_MATERIAL_CONNECTION,
        caption=caption,
        influencer_handle=influencer_handle,
        post_url=post_url,
        content_categories=content_categories
    )
    caption_audit = audit_post(post_input)
    is_compliant = (caption_audit.status == "COMPLIANT")
    caption_flags = caption_audit.violations + caption_audit.expert_review

    # OCR Scan
    visual_status = "NO_MEDIA"
    visual_labels_found = []
    
    thumbnails = snippet.get("thumbnails", {})
    t_url = None
    for size in ["maxres", "standard", "high", "medium", "default"]:
        if size in thumbnails:
            t_url = thumbnails[size].get("url")
            break
            
    if t_url:
        fname = f"temp_yt_{video_id}.jpg"
        local_path = download_asset(t_url, fname)
        if local_path and local_path.exists():
            ocr_res = process_image_ocr(local_path)
            visual_status = ocr_res["visual_status"]
            visual_labels_found = ocr_res["labels_found"]
            local_path.unlink()

    # Optional AI Audit
    ai_status = None
    ai_explanation = None
    ai_recommended_fix = None
    ai_claims = []
    
    if enable_ai:
        try:
            ai_report = audit_post_with_ai(
                caption, 
                "YouTube", 
                provider=provider,
                model_name=model_name, 
                base_url=base_url,
                api_key=ai_api_key
            )
            ai_status = "FLAGGED" if (ai_report.is_sponsored and not ai_report.material_disclosure_present) or ai_report.detected_claims else "COMPLIANT"
            ai_explanation = ai_report.reviewer_explanation
            ai_recommended_fix = ai_report.recommended_fix
            ai_claims = ai_report.detected_claims
        except Exception as e:
            print(f"[!] AI audit failed: {e}")

    return UnifiedAuditReport(
        post_id=video_id,
        influencer_handle=influencer_handle,
        post_url=post_url,
        timestamp=timestamp,
        caption_status=caption_audit.status,
        caption_flags=caption_flags,
        visual_status=visual_status,
        visual_flags=list(set(visual_labels_found)),
        is_compliant=is_compliant,
        risk_level=caption_audit.risk_level or "LOW",
        expert_review_flags=caption_audit.expert_review,
        ai_status=ai_status,
        ai_explanation=ai_explanation,
        ai_recommended_fix=ai_recommended_fix,
        ai_claims=ai_claims,
    )


def run_yt_pipeline(
    channel_handle_or_id: str, 
    api_key: str, 
    limit=5, 
    enable_ai: bool = False, 
    provider: str = "ollama",
    model_name: str = _secret("OLLAMA_MODEL_NAME", "qwen3:8b"), 
    base_url: str = "http://localhost:11434",
    ai_api_key: Optional[str] = None
) -> Tuple[str, List[UnifiedAuditReport]]:
    """
    Ingests and audits the recent videos of a YouTube channel.
    """
    if not api_key:
        raise ValueError("YouTube API Key is missing.")

    # Parse handle or channel id
    is_handle = channel_handle_or_id.startswith("@") or not channel_handle_or_id.startswith("UC")
    
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "contentDetails,snippet",
        "key": api_key
    }
    
    if not is_handle:
        params["id"] = channel_handle_or_id
    else:
        # If it's a handle but doesn't start with @, add it
        handle = channel_handle_or_id if channel_handle_or_id.startswith("@") else f"@{channel_handle_or_id}"
        params["forHandle"] = handle

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[!] YouTube channel lookup failed: {e}")
        return "Unknown Channel", []

    items = data.get("items", [])
    if not items:
        # Fallback in case forHandle failed or it was actually a plain channel ID
        if is_handle:
            params = {"part": "contentDetails,snippet", "id": channel_handle_or_id, "key": api_key}
            response = requests.get(url, params=params)
            items = response.json().get("items", [])
            
        if not items:
            return "Unknown Channel", []
            
    channel = items[0]
    uploads_playlist_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    channel_title = channel.get("snippet", {}).get("title", "Unknown Channel")
    
    if not uploads_playlist_id:
        return channel_title, []

    # Get recent videos in playlist
    playlist_url = "https://www.googleapis.com/youtube/v3/playlistItems"
    playlist_params = {
        "part": "snippet",
        "playlistId": uploads_playlist_id,
        "maxResults": limit,
        "key": api_key
    }
    
    try:
        playlist_response = requests.get(playlist_url, params=playlist_params)
        playlist_response.raise_for_status()
        playlist_items = playlist_response.json().get("items", [])
    except Exception as e:
        print(f"[!] Playlist fetch failed: {e}")
        return channel_title, []

    if not playlist_items:
        return channel_title, []
        
    video_ids = [item.get("snippet", {}).get("resourceId", {}).get("videoId") for item in playlist_items]
    video_ids = [v for v in video_ids if v]
    
    reports = []
    for vid_id in video_ids:
        report = fetch_single_yt_video(
            vid_id, 
            api_key, 
            enable_ai=enable_ai, 
            provider=provider,
            model_name=model_name, 
            base_url=base_url,
            ai_api_key=ai_api_key
        )
        if report:
            reports.append(report)
            
    return channel_title, reports


if __name__ == "__main__":
    import sys
    print("🎯 Running Standalone YouTube AI-Powered Audit Ingestion...")
    api_key_env = _secret("YOUTUBE_API_KEY") or _secret("YT_API_KEY")
    if not api_key_env:
        print("[!] YOUTUBE_API_KEY or YT_API_KEY not found in Streamlit secrets. Exiting.")
        sys.exit(1)
        
    test_channel = "@Google"
    print(f"Auditing recent videos for channel: {test_channel}")
    title, results = run_yt_pipeline(test_channel, api_key_env, limit=3, enable_ai=False)
    print(f"\nResults for {title} (Total: {len(results)}):")
    for r in results:
        print(f"- Video ID: {r.post_id} | Caption Verdict: {r.caption_status} | OCR: {r.visual_status}")
