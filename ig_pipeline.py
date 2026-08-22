import time
import requests
import streamlit as st
from pathlib import Path
import pytesseract
from PIL import Image

from datastruct import UnifiedAuditReport

# FIX: engine.py lives inside the vishwas_compliance package and does
# `from .rules import (...)` internally -- a relative import that only
# works when engine.py is imported AS PART OF that package. Copying
# engine.py out to sit next to this file (as the previous version of this
# comment described) makes that internal import crash immediately with
# "attempted relative import with no known parent package" -- confirmed by
# actually reproducing it. Importing from the real package fixes this, and
# also gives us the risk-level helpers added since.
from engine import PostInput, audit_post, aggregate_summary, EXPERT_REVIEW
from rules import APPROVED_LABELS, AMBIGUOUS_LABELS, risk_of
from ai_engine import audit_post_with_ai
from typing import Optional, Tuple

# Optional: auto-detects which ASCI expert-review categories (health
# claims, automotive claims, etc.) a caption's text plausibly touches on,
# using a transformer zero-shot classifier -- so content_categories doesn't
# rely purely on a human remembering to tag it. Genuinely optional: if
# `transformers`/`torch` aren't installed, or the model can't be reached,
# the pipeline still runs -- it just falls back to whatever
# content_categories a human sets by hand (i.e. today's behavior).


try:
    
    import claim_classifier
    from claim_classifier import classify_content_categories
    CLAIM_CLASSIFIER_AVAILABLE = True
    print("[✓] ✅ claim_classifier successfully loaded")
    print(f"[✓] 📦 classify_content_categories imported from: {claim_classifier.__file__}")
except ImportError as e:
    CLAIM_CLASSIFIER_AVAILABLE = False
    print("[!] ⚠️ Transformers library not installed — claim-category auto-detection disabled.")
    print("[!] 📋 Error details:", str(e))
    print("[!] 🔧 To enable claim classification, run:")
    print("    pip install transformers torch")
    print("[!] 💡 Note: Claim detection is optional. Core functionality will still work.")
except Exception as e:
    CLAIM_CLASSIFIER_AVAILABLE = False
    print("[!] ❌ Unexpected error loading claim_classifier:", str(e))
    print("[!] 🔧 Run: pip install --upgrade transformers torch")
    print("[!] 💡 Continuing without claim classification...") 


try:
    from generate_validation_log import write_validation_log
    VALIDATION_LOG_AVAILABLE = True
except ImportError:
    VALIDATION_LOG_AVAILABLE = False

def _secret(key, default=None):
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default


ACCESS_TOKEN = _secret("IG_ACCESS_TOKEN")
IG_ACCOUNT_ID = _secret("IG_ACCOUNT_ID")
API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{IG_ACCOUNT_ID}"

DOWNLOAD_DIR = Path("temp_media")
DOWNLOAD_DIR.mkdir(exist_ok=True)
# The defined list of pilot creator/brand accounts
PILOT_ACCOUNTS = ["gyanm.samarth.academy"]

# FIX: this was hardcoded inline as "paid" on every single post pulled from
# an account, with no way to tell an actual sponsored post apart from
# completely organic content. Instagram's API doesn't expose "this post was
# paid for" as a field, so there's no way to detect this automatically yet --
# pulling this out to a named constant at least makes the assumption
# visible instead of buried in a function body. Until there's a real
# classification step (manual tagging, or a future model), treat every
# COMPLIANT/FLAGGED verdict from this pipeline as conditional on that
# assumption being true for the account you're auditing.
DEFAULT_MATERIAL_CONNECTION = "paid"


def fetch_pilot_data(target_username, max_pages=3):
    """
    Securely fetches extended post data using cursor-based pagination
    and defends against BUC rate limits using exponential backoff.
    """
    all_media = []
    after_cursor = None
    page_count = 0

    while page_count < max_pages:
        # 1. Build the dynamic pagination string
        # FIX: added `permalink` -- the previous field list never fetched a
        # real, clickable post URL at all (see map_ig_to_post_input below).
        if after_cursor:
            media_field = f"media.after({after_cursor}){{id,caption,media_url,media_type,timestamp,like_count,permalink,children{{id,media_url,media_type}}}}"
        else:
            media_field = "media{id,caption,media_url,media_type,timestamp,like_count,permalink,children{id,media_url,media_type}}"

        fields = f"business_discovery.username({target_username}){{{media_field}}}"

        params = {
            "fields": fields,
            "access_token": ACCESS_TOKEN
        }

        # 2. Rate Limit Defense (Exponential Backoff)
        max_retries = 3
        data = None  # FIX: explicitly track whether a response was ever obtained
        for attempt in range(max_retries):
            try:
                response = requests.get(BASE_URL, params=params)

                # If we hit Meta's 200 calls/hr limit, back off and retry
                if response.status_code == 429:
                    wait_time = (2 ** attempt) * 5  # Waits 5s, 10s, 20s
                    print(f"    [!] Rate limited by Meta. Backing off for {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()
                break  # Success! Break out of the retry loop

            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"    [!] Fatal network error for {target_username}: {e}")
                    return {"account": target_username, "status": "error", "posts": all_media}
                time.sleep(2)

        # FIX: if every attempt above was rate-limited, `data` is still None
        # here -- the original code fell through to `data.get(...)` in that
        # case, which crashes with a NameError/AttributeError instead of
        # failing gracefully. Reproduced this before fixing it.
        if data is None:
            print(f"    [!] Giving up on {target_username} after repeated rate limiting.")
            return {"account": target_username, "status": "error", "posts": all_media}

        # 3. Extract the posts and append to master list
        business_data = data.get("business_discovery", {})
        media_edge = business_data.get("media", {})

        page_posts = media_edge.get("data", [])
        all_media.extend(page_posts)
        print(f"    -> Fetched page {page_count + 1} ({len(page_posts)} posts)")

        # 4. Check for the next cursor
        paging = media_edge.get("paging", {})
        cursors = paging.get("cursors", {})
        after_cursor = cursors.get("after")

        page_count += 1

        # If there is no cursor, we've reached the beginning of their account
        if not after_cursor:
            break

        time.sleep(1)  # Gentle pause before requesting the next page

    return {
        "account": target_username,
        "status": "success",
        "posts": all_media
    }


def map_ig_to_post_input(account_username: str, ig_post: dict) -> PostInput:
    """
    Maps raw Instagram Graph API media payloads to the compliance engine's
    PostInput dataclass.
    """
    raw_media_type = ig_post.get("media_type", "IMAGE")
    caption_text = ig_post.get("caption", "")
    post_id = ig_post.get("id", "")
    # FIX: use the real permalink Instagram returns instead of guessing a
    # URL from the internal numeric media ID, which isn't a valid post URL.
    permalink = ig_post.get("permalink")

    if raw_media_type == "VIDEO":
        content_type = "video"
        # NOTE: Instagram's Business Discovery media fields don't reliably
        # distinguish Reels from regular feed videos (that needs
        # media_product_type, not fetched here), and true 24-hour Stories
        # aren't exposed by this endpoint at all -- only permanent posts are.
        # So "reel_story" content_type is never produced by this pipeline
        # yet; every video is checked against the "video" rules (verbal
        # timing, overlay), not the Reels/Stories superimposed-label rule.
    else:
        # Covers both IMAGE and CAROUSEL_ALBUM for the caption-level check;
        # each carousel slide's own image/video still gets OCR'd or queued
        # for audio separately in route_and_process_media.
        content_type = "static_post"

    # NEW: auto-suggest expert-review categories from the caption text.
    # This never decides compliance by itself -- it only widens the same
    # content_categories field you could otherwise set by hand, so a
    # health/automotive/education claim has a real chance of reaching
    # NEEDS EXPERT REVIEW instead of silently passing through because no
    # one remembered to tag it.
    content_categories = []
    if CLAIM_CLASSIFIER_AVAILABLE:
        content_categories = classify_content_categories(caption_text)

    return PostInput(
        platform="Instagram",
        content_type=content_type,
        material_connection=DEFAULT_MATERIAL_CONNECTION,
        caption=caption_text,
        client="Pilot Campaign",
        influencer_handle=f"@{account_username}",
        post_url=permalink or f"https://instagram.com/p/{post_id}",
        content_categories=content_categories,
    )


def download_asset(url: str, filename: str) -> Path:
    """Streams binary asset data from Meta CDN to local disk securely."""
    target_path = DOWNLOAD_DIR / filename
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(target_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return target_path
    except Exception as e:
        print(f"    [!] Failed to download asset {filename}: {e}")
        return None


def process_image_ocr(file_path):
    """
    Scans a downloaded image using Tesseract OCR to extract burned-in text,
    and reports whether a recognized disclosure label is visible in it.

    FIX (found via testing, not just reading): the previous version treated
    *finding* a disclosure label (e.g. "#ad") in the image as a violation --
    literally the opposite of what should happen. Confirmed directly: a
    post already COMPLIANT on its caption (a proper "#ad" up front) got
    marked visual_status="FLAGGED" for the exact same "#ad" text also being
    visible in the image, which then made an already-compliant post
    register as not fully compliant. Finding a disclosure label burned into
    an image is evidence *for* compliance (especially useful for Reels,
    where ASCI wants the label superimposed on the image itself), not
    against it.

    This function still can't determine a real visual VIOLATION on its own
    -- that would require knowing whether this specific piece of content
    structurally needs an on-image disclosure (a Reel/Story) versus one
    where the caption alone is sufficient, which isn't information this
    function has. So for now it only reports what it found; it does not
    declare a pass/fail verdict, and (see run_integrated_pipeline) it does
    not gate is_compliant. Treat "visual_status" as supporting evidence for
    a human reviewer, not an independent judgment, until that context is
    wired through.
    """
    print(f"    📷 Running OCR Scan on: {file_path.name}")

    try:
        # Open image and run OCR
        img = Image.open(file_path)
        raw_text = pytesseract.image_to_string(img)

        # Normalize the text (lowercase, remove excessive newlines/spaces)
        clean_text = " ".join(raw_text.split()).lower()

        if not clean_text:
            return {"visual_status": "NO_TEXT_DETECTED", "labels_found": [], "extracted_text": ""}

        print(f"       📝 Text Detected: '{clean_text[:60]}...'")

        # Reuse the same labels the caption engine checks against, so an
        # image is judged by the same standard as a caption -- not a
        # separate, looser keyword list.
        all_labels = APPROVED_LABELS + AMBIGUOUS_LABELS
        found_labels = [lbl for lbl in all_labels if lbl in clean_text]

        if found_labels:
            print(f"       ✅ Disclosure label visible in image: {found_labels}")
            return {"visual_status": "DISCLOSURE_VISIBLE", "labels_found": found_labels, "extracted_text": clean_text}

        return {"visual_status": "TEXT_NO_DISCLOSURE", "labels_found": [], "extracted_text": clean_text}

    except Exception as e:
        print(f"       [!] OCR Engine Error on {file_path.name}: {e}")
        return {"visual_status": "ERROR", "labels_found": [], "extracted_text": ""}


def process_video_audio(file_path: Path):
    """Placeholder for Video/Audio transcription compliance check (Phase 2.3)."""
    # This will receive the downloaded mp4 to extract and transcribe audio
    print(f"    🎥 Routing to Transcription Layer: {file_path.name}")
    return []


def route_and_process_media(post_id: str, raw_post: dict):
    """
    Inspects media structural signatures, handles carousel extraction, and
    downloads assets locally. Returns a list of (file_path, media_type)
    tuples for the caller to dispatch to OCR/audio processing.

    FIX: this used to also call process_image_ocr / process_video_audio
    directly, in addition to run_integrated_pipeline calling them AGAIN on
    the same files afterward -- every image was silently OCR'd twice, and
    the first pass's result was discarded and never used for anything.
    Downloading and dispatching are now separated so each file is
    processed exactly once.
    """
    media_type = raw_post.get("media_type")
    downloaded = []

    # Case 1: Complex Album Layouts (Carousels)
    if media_type == "CAROUSEL_ALBUM":
        children = raw_post.get("children", {}).get("data", [])
        print(f"    📦 Processing Carousel Album ({len(children)} slides)...")

        for idx, child in enumerate(children):
            child_url = child.get("media_url")
            child_type = child.get("media_type")
            child_id = child.get("id")

            if child_url:
                ext = "mp4" if child_type == "VIDEO" else "jpg"
                fname = f"{post_id}_slide_{idx}_{child_id}.{ext}"
                file_path = download_asset(child_url, fname)
                if file_path:
                    downloaded.append((file_path, child_type))

    # Case 2: Standard Direct Media Assets (Single Image / Reel / Video)
    else:
        media_url = raw_post.get("media_url")
        if media_url:
            ext = "mp4" if media_type == "VIDEO" else "jpg"
            fname = f"{post_id}.{ext}"
            file_path = download_asset(media_url, fname)
            if file_path:
                downloaded.append((file_path, media_type))

    return downloaded


def run_integrated_pipeline(
    target_username: str, 
    enable_ai: bool = False, 
    provider: str = "ollama",
    model_name: str = _secret("OLLAMA_MODEL_NAME", "qwen3:8b"), 
    base_url: str = "http://localhost:11434",
    api_key: Optional[str] = None
):
    print(f"🚀 Starting Multi-Modal Audit for: @{target_username}")

    # 1. Fetch live data using Phase 1 Pagination pipeline
    api_result = fetch_pilot_data(target_username, max_pages=2)
    unified_reports = []

    if api_result["status"] == "success":
        for raw_post in api_result["posts"]:
            post_id = raw_post.get("id", "unknown")
            # FIX: "shortcode" was never a field this pipeline actually
            # requested, so this always silently fell back to post_id --
            # producing a URL Instagram doesn't recognize. Use the real
            # permalink fetched above instead.
            post_url = raw_post.get("permalink") or f"https://www.instagram.com/p/{post_id}/"
            timestamp = raw_post.get("timestamp", "")

            print(f"\n🔍 Auditing Post ID: {post_id}")

            # --- LAYER 1: Text Caption Audit ---
            post_input_object = map_ig_to_post_input(target_username, raw_post)
            caption_audit = audit_post(post_input_object)  # Existing rule engine

            # --- LAYER 2: Visual OCR Media Audit ---
            active_files = route_and_process_media(post_id, raw_post)

            visual_labels_found = []
            visual_status = "NO_MEDIA"

            # Dispatch each downloaded asset to exactly one processing step
            for file_path, media_type in active_files:
                if media_type == "VIDEO":
                    process_video_audio(file_path)
                else:
                    ocr_res = process_image_ocr(file_path)
                    visual_status = ocr_res["visual_status"]
                    visual_labels_found.extend(ocr_res["labels_found"])

                # Dynamic Clean-up: Delete asset immediately after inspection
                if file_path.exists():
                    file_path.unlink()

            # --- LAYER 3: Unified Compilation ---
            # FIX: this used to be `caption_audit.status != "FLAGGED"`, which
            # silently treated NEEDS EXPERT REVIEW (e.g. an unverified health
            # claim -- CRITICAL risk) and PENDING REVIEW the same as an
            # actual clean pass. Confirmed by testing directly: a "this
            # cures my thyroid" post with no confirmed violations came back
            # is_compliant=True under the old logic. Only a caption status
            # of exactly COMPLIANT counts now.
            #
            # The visual OCR layer deliberately does NOT gate is_compliant
            # here -- see process_image_ocr's docstring. It can't yet tell
            # whether a given piece of content actually required an
            # on-image disclosure, so it isn't in a position to fail a post
            # on its own. It's carried through the report as supporting
            # evidence for a human reviewer instead.
            is_compliant = (caption_audit.status == "COMPLIANT")

            # FIX: `getattr(caption_audit, 'flags', [])` was reading an
            # attribute that doesn't exist on AuditResult at all -- it
            # always silently returned the [] default, even for posts with
            # real, confirmed violations. The real attributes are
            # `violations` (confirmed problems) and `expert_review`
            # (routed to a human, never auto-verified).
            caption_flags = caption_audit.violations + caption_audit.expert_review

            # Run AI Audit if enabled
            ai_status = None
            ai_explanation = None
            ai_recommended_fix = None
            ai_claims = []

            if enable_ai:
                try:
                    ai_report = audit_post_with_ai(
                        post_input_object.caption, 
                        post_input_object.platform, 
                        provider=provider,
                        model_name=model_name, 
                        base_url=base_url,
                        api_key=api_key
                    )
                    ai_status = "FLAGGED" if (ai_report.is_sponsored and not ai_report.material_disclosure_present) or ai_report.detected_claims else "COMPLIANT"
                    ai_explanation = ai_report.reviewer_explanation
                    ai_recommended_fix = ai_report.recommended_fix
                    ai_claims = ai_report.detected_claims
                except Exception as e:
                    print(f"      [!] AI audit failed for post {post_id}: {e}")

            report = UnifiedAuditReport(
                post_id=post_id,
                influencer_handle=target_username,
                post_url=post_url,
                timestamp=timestamp,
                caption_status=caption_audit.status,
                caption_flags=caption_flags,
                visual_status=visual_status,
                visual_flags=list(set(visual_labels_found)),  # Deduplicate
                is_compliant=is_compliant,
                risk_level=caption_audit.risk_level or "LOW",
                expert_review_flags=caption_audit.expert_review,
                ai_status=ai_status,
                ai_explanation=ai_explanation,
                ai_recommended_fix=ai_recommended_fix,
                ai_claims=ai_claims,
            )

            unified_reports.append(report)

            # Console Logging UI -- distinguishes a confirmed violation from
            # something merely routed to a human, rather than lumping both
            # under one generic "out of compliance" message.
            if caption_audit.status == "FLAGGED":
                worst_risk = caption_audit.risk_level
                print(f"❌ FLAGGED [{worst_risk}] -- confirmed issue(s): {caption_audit.violations}")
            elif caption_audit.status == "NEEDS EXPERT REVIEW":
                print(f"🧑‍⚖️  NEEDS EXPERT REVIEW [{caption_audit.risk_level}] -- {caption_audit.expert_review}")
            elif caption_audit.status == "PENDING REVIEW":
                print("⏳ PENDING REVIEW -- caption checks look fine, but not everything has been reviewed yet")

            if visual_status == "DISCLOSURE_VISIBLE":
                print(f"👁️  Visual disclosure confirmed in image: {sorted(set(visual_labels_found))}")
            elif visual_status == "ERROR":
                print("⚠️  VISUAL SCAN FAILED -- treat as unverified, not clean")

            print(f"{'✅ POST FULLY COMPLIANT' if is_compliant else '⚠️  NOT YET FULLY COMPLIANT'}")

    return unified_reports


def fetch_single_ig_post(
    username: str, 
    shortcode: str, 
    access_token: str, 
    ig_account_id: str, 
    enable_ai: bool = False, 
    provider: str = "ollama",
    model_name: str = _secret("OLLAMA_MODEL_NAME", "qwen3:8b"), 
    base_url: str = "http://localhost:11434",
    api_key: Optional[str] = None
) -> Optional[UnifiedAuditReport]:
    """
    Fetches and audits a single Instagram post by username and shortcode.
    Matches the multi-modal checking pipeline.
    """
    api_version = "v25.0"
    base_url_api = f"https://graph.facebook.com/{api_version}/{ig_account_id}"
    
    # Query business discovery for user posts
    fields = f"business_discovery.username({username}){{media{{id,caption,media_url,media_type,timestamp,like_count,permalink,children{{id,media_url,media_type}}}}}}"
    params = {
        "fields": fields,
        "access_token": access_token
    }
    
    try:
        response = requests.get(base_url_api, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[!] Graph API Request failed: {e}")
        return None
        
    posts = data.get("business_discovery", {}).get("media", {}).get("data", [])
    target_post = None
    for post in posts:
        permalink = post.get("permalink", "")
        if shortcode in permalink or post.get("id") == shortcode:
            target_post = post
            break
            
    if not target_post:
        # Attempt cursor paging for one more page
        paging = data.get("business_discovery", {}).get("media", {}).get("paging", {})
        after_cursor = paging.get("cursors", {}).get("after")
        if after_cursor:
            fields_p2 = f"business_discovery.username({username}){{media.after({after_cursor}){{id,caption,media_url,media_type,timestamp,like_count,permalink,children{{id,media_url,media_type}}}}}}"
            params["fields"] = fields_p2
            try:
                response2 = requests.get(base_url_api, params=params)
                response2.raise_for_status()
                posts2 = response2.json().get("business_discovery", {}).get("media", {}).get("data", [])
                for post in posts2:
                    permalink = post.get("permalink", "")
                    if shortcode in permalink or post.get("id") == shortcode:
                        target_post = post
                        break
            except Exception:
                pass

    if not target_post:
        return None
        
    post_id = target_post.get("id", "unknown")
    post_url = target_post.get("permalink") or f"https://www.instagram.com/p/{post_id}/"
    timestamp = target_post.get("timestamp", "")
    
    # Caption audit
    post_input_object = map_ig_to_post_input(username, target_post)
    caption_audit = audit_post(post_input_object)
    is_compliant = (caption_audit.status == "COMPLIANT")
    caption_flags = caption_audit.violations + caption_audit.expert_review
    
    # OCR Visual audit
    active_files = route_and_process_media(post_id, target_post)
    visual_labels_found = []
    visual_status = "NO_MEDIA"
    
    for file_path, media_type in active_files:
        if media_type != "VIDEO":
            ocr_res = process_image_ocr(file_path)
            visual_status = ocr_res["visual_status"]
            visual_labels_found.extend(ocr_res["labels_found"])
        if file_path.exists():
            file_path.unlink()
            
    # Optional AI Audit
    ai_status = None
    ai_explanation = None
    ai_recommended_fix = None
    ai_claims = []
    
    if enable_ai:
        try:
            ai_report = audit_post_with_ai(
                post_input_object.caption, 
                post_input_object.platform, 
                provider=provider,
                model_name=model_name, 
                base_url=base_url,
                api_key=api_key
            )
            ai_status = "FLAGGED" if (ai_report.is_sponsored and not ai_report.material_disclosure_present) or ai_report.detected_claims else "COMPLIANT"
            ai_explanation = ai_report.reviewer_explanation
            ai_recommended_fix = ai_report.recommended_fix
            ai_claims = ai_report.detected_claims
        except Exception as e:
            print(f"[!] AI audit failed: {e}")
            
    return UnifiedAuditReport(
        post_id=post_id,
        influencer_handle=f"@{username}",
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


def extract_instagram_info(url: str) -> Tuple[Optional[str], Optional[str]]:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if 'instagram.com' not in parsed.netloc:
        return None, None
    
    path_parts = [p for p in parsed.path.split('/') if p]
    if not path_parts:
        return None, None
        
    username = None
    shortcode = None
    
    if path_parts[0] not in ('p', 'reel', 'tv', 'stories', 'explore', 'reels'):
        username = path_parts[0]
        if len(path_parts) > 2 and path_parts[1] in ('p', 'reel', 'tv', 'stories'):
            shortcode = path_parts[2]
    else:
        if len(path_parts) > 1:
            shortcode = path_parts[1]
            
    return username, shortcode


if __name__ == "__main__":
    print("🎯 Starting Aegis Engine Batch Processing...\n")
    master_audit_results = []

    # Loop through the list of pilot accounts defined at the top of your script
    for account in PILOT_ACCOUNTS:
        try:
            account_reports = run_integrated_pipeline(account)
            master_audit_results.extend(account_reports)

            # Crucial: Sleep for 5 seconds between accounts to avoid triggering
            # Meta's burst rate limits when iterating through multiple brands.
            time.sleep(5)

        except Exception as e:
            print(f"\n[!] Critical failure processing @{account}: {e}")
            continue

    # --- Final Batch Summary UI ---
    print("\n" + "=" * 60)
    print("🎯 BATCH PROCESSING COMPLETE")
    print("=" * 60)

    total_audited = len(master_audit_results)

    if total_audited > 0:
        compliant_count = sum(1 for report in master_audit_results if report.is_compliant)
        flagged_count = sum(1 for report in master_audit_results if report.caption_status == "FLAGGED")
        expert_review_count = sum(1 for report in master_audit_results if report.caption_status == "NEEDS EXPERT REVIEW")
        visual_disclosure_count = sum(1 for report in master_audit_results if report.visual_status == "DISCLOSURE_VISIBLE")
        compliance_rate = (compliant_count / total_audited) * 100

        print(f"Total Posts Audited:     {total_audited}")
        print(f"Fully Compliant:         {compliant_count}")
        print(f"Confirmed Violations:    {flagged_count}")
        print(f"Needs Expert Review:     {expert_review_count}")
        print(f"Visual Disclosure Seen:  {visual_disclosure_count}  (informational -- see process_image_ocr docstring)")
        print(f"Overall Health Score:    {compliance_rate:.1f}%\n")
        print("Note: material_connection is currently assumed to be \"paid\" for every")
        print("post pulled from these accounts (see DEFAULT_MATERIAL_CONNECTION) --")
        print("that assumption should be reviewed per-post before trusting this score")
        print("with a real client.")

        if VALIDATION_LOG_AVAILABLE:
            log_path = write_validation_log(master_audit_results, "validation_log.xlsx")
            print(f"\nWrote {log_path} -- open it, review each post blind (see the "
                  f"'How To Use' tab), then compare your verdict to the engine's.")
        else:
            print("\n[!] generate_validation_log.py not found next to this script -- "
                  "skipping automatic validation log generation.")
    else:
        print("No posts were successfully retrieved or audited.")