"""
The AIGES Engine -- Compliance Dashboard

A web dashboard that imports and consumes the AI-powered IG Ingestion Pipeline 
and YouTube Ingestion Pipeline to audit post and account compliance dynamically.
"""
import streamlit as st
from urllib.parse import urlparse


def _secret(key, default=""):
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default

from engine import PostInput, audit_post
from rules import (
    PLATFORMS, CONTENT_TYPES, MATERIAL_CONNECTIONS, ASCI_CATEGORIES,
    RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW, RISK_ADVISORY,
)
from ai_engine import audit_post_with_ai

# Import modular pipeline functions directly
from ig_pipeline import (
    fetch_single_ig_post, 
    run_integrated_pipeline as run_ig_pipeline, 
    extract_instagram_info
)
from yt_pipeline import (
    fetch_single_yt_video, 
    run_yt_pipeline, 
    extract_youtube_video_id, 
    extract_youtube_channel_info
)

st.set_page_config(page_title="THE AIGES ENGINE", page_icon="⚖️", layout="wide")

# Colors matching the design guidelines
RISK_COLORS = {
    RISK_CRITICAL: "#8B1E1E", RISK_HIGH: "#B5551A", RISK_MEDIUM: "#8A7000",
    RISK_LOW: "#2E6B4F", RISK_ADVISORY: "#5B6470",
}
STATUS_COLORS = {
    "COMPLIANT": "#2E7D32", "FLAGGED": "#B00020",
    "NEEDS EXPERT REVIEW": "#B5551A", "PENDING REVIEW": "#5B6470",
}

EXPERT_REVIEW_CATEGORIES = [k for k, v in ASCI_CATEGORIES.items() if v["automated"] is False]

EXAMPLES = {
    "-- choose an example --": "",
    "Compliant post": "#ad Loving this new serum from XYZ Skincare! My skin has never felt better.",
    "Missing / buried disclosure": "Had so much fun trying this out! #style #ootd #fashion #india #reels #trending #collab",
    "Unverified health claim": "#ad this tea cures my thyroid completely and clears skin in 3 days",
    "Real money gaming": "#ad download this app and win real cash today, link in bio",
}

# --- Sidebar AI Configuration ---

with st.sidebar:
    st.title("🤖 AI Auditor (LangChain)")
    enable_ai = st.checkbox("Enable AI Auditor", value=True)
    
    yt_key = _secret("YOUTUBE_API_KEY") or _secret("YT_API_KEY")
    ig_token = _secret("IG_ACCESS_TOKEN")
    ig_id = _secret("IG_ACCOUNT_ID")
    ai_provider_val = "gemini"
    ai_model = _secret("GEMINI_MODEL_NAME", "gemini-3.6-flash")
    ollama_url = "http://localhost:11434"
    ai_api_key = _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")
    ai_provider_display = "Gemini"
    
    if enable_ai:
        ai_provider_choice = st.selectbox("AI Provider", ["Ollama (Local)", "Gemini", "Groq"], index=1)
        ai_provider_display = ai_provider_choice
        if ai_provider_choice == "Gemini":
            ai_provider_val = "gemini"
            ai_model = st.text_input("Gemini Model Name", value=_secret("GEMINI_MODEL_NAME", "gemini-3.6-flash"))
            ai_api_key = _secret("GEMINI_API_KEY") or _secret("GOOGLE_API_KEY")
        elif ai_provider_choice == "Groq":
            ai_provider_val = "groq"
            ai_model = st.text_input("Groq Model Name", value=_secret("GROQ_MODEL_NAME", "llama-3.3-70b-versatile"))
            ai_api_key = _secret("GROQ_API_KEY")
        else:
            ai_provider_val = "ollama"
            ai_model = st.text_input("Ollama Model Name", value=_secret("OLLAMA_MODEL_NAME", "qwen3:8b"))
            ollama_url = st.text_input("Ollama URL", value="http://localhost:11434")

# --- App Layout ---

st.title("THE AIGES ENGINE")
st.caption("Verify ASCI/CCPA compliance via traditional rules and Gemini AI auditing.")

tab_manual, tab_link, tab_account = st.tabs([
    "✍️ Single Post Manual Check", 
    "🔗 Import Single Link", 
    "📈 Audit Account Videos / Posts"
])

# --- TAB 1: MANUAL CHECK ---
with tab_manual:
    col_left, col_right = st.columns([1, 1], gap="large")
    
    with col_left:
        st.subheader("Post details")
        example_choice = st.selectbox("Try an example", list(EXAMPLES.keys()), key="man_example")
        default_caption = EXAMPLES[example_choice]
        
        caption = st.text_area("Caption text", value=default_caption, height=120,
                                placeholder="Paste the real post caption here...", key="man_caption")
        
        c1, c2 = st.columns(2)
        with c1:
            platform = st.selectbox("Platform", PLATFORMS, key="man_platform")
            content_type = st.selectbox("Content type", CONTENT_TYPES, format_func=lambda x: x.replace("_", " ").title(), key="man_content_type")
        with c2:
            material_connection = st.selectbox(
                "Material connection", list(MATERIAL_CONNECTIONS.keys()),
                format_func=lambda k: MATERIAL_CONNECTIONS[k], key="man_mat_conn"
            )
            
        is_virtual_influencer = st.checkbox("This is a virtual / AI influencer account", key="man_vi")
        ai_disclosure_present = None
        if is_virtual_influencer:
            ai_disclosure_present = st.checkbox("AI identity is persistently and prominently disclosed", key="man_vi_disc")
            
        makes_claim = st.checkbox("This post makes a health, finance, or technical claim", key="man_makes_claim")
        credentials_shown = None
        if makes_claim:
            credentials_shown = st.checkbox("Some credential or substantiation is shown for the claim", key="man_cred_shown")
            
        verbal_second, overlay_present, story_superimposed = None, None, None
        if content_type in ("video", "youtube_short", "audio_podcast"):
            st.markdown("**Video / audio disclosure**")
            vc1, vc2 = st.columns(2)
            with vc1:
                not_reviewed = st.checkbox("Not reviewed yet (verbal timing)", value=True, key="man_verbal_pending")
            if not not_reviewed:
                confirmed_absent = st.checkbox("Confirmed: no verbal disclosure at all", key="man_verbal_absent")
                if confirmed_absent:
                    verbal_second = -1
                else:
                    verbal_second = st.number_input("Verbal disclosure happens at second", min_value=0, max_value=120, value=5, key="man_verbal_sec")
            if content_type in ("video", "youtube_short"):
                overlay_choice = st.radio("Overlay disclosure visible throughout the sponsored segment?",
                                           ["Not reviewed yet", "Yes", "No"], horizontal=True, key="man_overlay")
                overlay_present = {"Yes": True, "No": False, "Not reviewed yet": None}[overlay_choice]
                
        if content_type == "reel_story":
            story_choice = st.radio("Disclosure superimposed directly on the image/video?",
                                     ["Not reviewed yet", "Yes", "No"], horizontal=True, key="man_story")
            story_superimposed = {"Yes": True, "No": False, "Not reviewed yet": None}[story_choice]
            
        with st.expander("Advanced: other ASCI categories"):
            ai_generated = st.checkbox("AI-generated or AI-enhanced content", key="man_ai_gen")
            ai_label_present = None
            if ai_generated:
                ai_label_present = st.checkbox("Visible 'Created/Enhanced using AI' label present", key="man_ai_lbl")
                
            names_competitor = st.checkbox("Names a specific competitor", key="man_competitor")
            unqualified_claim = None
            if names_competitor:
                unqualified_claim = st.checkbox("Makes an unqualified superiority claim (not substantiated)", key="man_unqual")
                
            product_category = st.selectbox("Product category (if applicable)",
                                             ["None", "real_money_gaming", "virtual_digital_asset"], key="man_prod_cat")
            product_category = None if product_category == "None" else product_category
            mandatory_disclaimer = None
            if product_category == "virtual_digital_asset":
                mandatory_disclaimer = st.checkbox("Mandatory VDA risk disclaimer is visible", key="man_vda_disc")
                
            selected_categories = st.multiselect(
                "Flag for expert review (categories this tool won't auto-verify)",
                EXPERT_REVIEW_CATEGORIES,
                format_func=lambda k: ASCI_CATEGORIES[k]["label"],
                key="man_expert_cats"
            )
            
        run = st.button("Check Compliance", type="primary", use_container_width=True, key="man_run")
        
    with col_right:
        st.subheader("Result")
        if not run:
            st.info("Fill in the post details on the left and click **Check Compliance**.")
        elif not caption.strip() and material_connection != "none_genuine":
            st.warning("Add a caption to check, or set material connection to \"genuinely bought and liked\" if there's no text to review.")
        else:
            # 1. Traditional Rule-based audit
            post = PostInput(
                platform=platform,
                content_type=content_type,
                material_connection=material_connection,
                caption=caption,
                is_virtual_influencer=is_virtual_influencer,
                ai_disclosure_present_and_persistent=ai_disclosure_present,
                makes_health_finance_or_technical_claim=makes_claim,
                credentials_or_substantiation_shown=credentials_shown,
                video_verbal_disclosure_second=verbal_second,
                video_overlay_covers_sponsored_segment=overlay_present,
                story_label_superimposed=story_superimposed,
                ai_generated_or_enhanced=ai_generated,
                ai_content_label_present=ai_label_present,
                names_specific_competitor=names_competitor,
                unqualified_superiority_claim=unqualified_claim,
                product_category=product_category,
                mandatory_disclaimer_present=mandatory_disclaimer,
                content_categories=selected_categories,
            )
            result = audit_post(post)
            
            # Display status card
            status_color = STATUS_COLORS.get(result.status, "#333")
            risk_badge = ""
            if result.risk_level:
                rc = RISK_COLORS.get(result.risk_level, "#333")
                risk_badge = f'&nbsp;&nbsp;<span style="background:{rc};color:white;padding:3px 10px;border-radius:10px;font-size:0.85em;">{result.risk_level} RISK</span>'
                
            st.markdown(
                f'<div style="background:{status_color};color:white;padding:16px 20px;border-radius:8px;font-size:1.3em;font-weight:700;">'
                f'{result.status}{risk_badge}</div>',
                unsafe_allow_html=True,
            )
            st.write("")
            
            if result.violations:
                st.markdown("**Rule Engine Confirmed Issues**")
                for name in result.violations:
                    st.error(f"**{name.replace('_', ' ').title()}** -- {result.explanations[name]}")
                    
            if result.expert_review:
                st.markdown("**Routed to expert review** (not auto-verified)")
                for name in result.expert_review:
                    label = ASCI_CATEGORIES.get(name, {}).get("label", name)
                    st.warning(f"**{label}** -- {result.explanations[name]}")
                    
            pending = [n for n, v in result.checks.items() if v is None]
            if pending:
                st.markdown("**Not yet reviewed**")
                st.info(", ".join(n.replace("_", " ").title() for n in pending))
                
            if result.status == "COMPLIANT":
                st.success("Rule Engine Verdict: Compliant")
                
            if enable_ai:
                st.divider()
                st.subheader(f"🤖 AI-Powered Audit ({ai_provider_display})")
                with st.spinner("Invoking LLM..."):
                    try:
                        ai_report = audit_post_with_ai(
                            caption, 
                            platform, 
                            provider=ai_provider_val,
                            model_name=ai_model, 
                            base_url=ollama_url,
                            api_key=ai_api_key
                        )
                        
                        ai_status = "FLAGGED" if (ai_report.is_sponsored and not ai_report.material_disclosure_present) or ai_report.detected_claims else "COMPLIANT"
                        ai_color = STATUS_COLORS.get(ai_status, "#333")
                        
                        st.markdown(
                            f'<div style="background:{ai_color};color:white;padding:10px 16px;border-radius:8px;font-size:1.1em;font-weight:700;">'
                            f'AI Audit: {ai_status}</div>',
                            unsafe_allow_html=True,
                        )
                        st.write("")
                        
                        st.markdown(f"**AI Disclosure Analysis:**\n{ai_report.disclosure_analysis}")
                        
                        if ai_report.detected_claims:
                            st.error(f"**Extracted Claims:** {', '.join(ai_report.detected_claims)}")
                            st.info(f"**Suggested expert categories:** {', '.join(ai_report.suggested_expert_categories)}")
                            
                        st.markdown(f"**AI Reviewer Explanation:**\n{ai_report.reviewer_explanation}")
                        st.success(f"💡 **AI Recommended Fix:** {ai_report.recommended_fix}")
                    except Exception as e:
                        st.error(f"AI Check Failed: {e}")
                        st.info("💡 Check that the selected AI provider is configured correctly in Streamlit secrets.")

# --- TAB 2: IMPORT SINGLE LINK ---
with tab_link:
    st.subheader("🔗 Verify Post / Video via Link")
    st.caption("Paste a link to a specific Instagram Post/Reel or YouTube Video/Short to fetch its details and check compliance.")
    
    post_url = st.text_input("Post URL", placeholder="https://www.youtube.com/watch?v=... or https://www.instagram.com/p/...")
    
    # Instagram Username extraction fallback
    ig_user_input = ""
    parsed_username, parsed_shortcode = extract_instagram_info(post_url)
    if "instagram.com" in post_url and not parsed_username:
        ig_user_input = st.text_input("Instagram Creator Username (Required for Instagram link checks)", 
                                      placeholder="e.g. gyanmsamarthacademy")
        
    fetch_and_audit = st.button("Fetch and Audit Post", type="primary", use_container_width=True, key="link_fetch_btn")
    
    if fetch_and_audit:
        if not post_url.strip():
            st.error("Please enter a valid URL.")
        else:
            with st.spinner("Fetching post details from modular pipelines..."):
                try:
                    report = None
                    
                    # 1. YouTube Data API v3 Ingestion & Audit
                    if "youtube.com" in post_url or "youtu.be" in post_url:
                        vid_id = extract_youtube_video_id(post_url)
                        if not vid_id:
                            st.error("Could not parse YouTube video ID from the URL.")
                        else:
                            report = fetch_single_yt_video(
                                vid_id, 
                                yt_key, 
                                enable_ai=enable_ai, 
                                provider=ai_provider_val,
                                model_name=ai_model, 
                                base_url=ollama_url,
                                ai_api_key=ai_api_key
                            )
                            if not report:
                                st.error("Video not found. Double check the ID or API Key.")
                                
                    # 2. Instagram Graph API Ingestion & Audit
                    elif "instagram.com" in post_url:
                        username = parsed_username or ig_user_input.strip()
                        if not username:
                            st.error("An Instagram creator username is required for business discovery. Please enter it above.")
                        elif not parsed_shortcode:
                            st.error("Could not parse shortcode from Instagram URL.")
                        else:
                            report = fetch_single_ig_post(
                                username, 
                                parsed_shortcode, 
                                ig_token, 
                                ig_id, 
                                enable_ai=enable_ai, 
                                provider=ai_provider_val,
                                model_name=ai_model, 
                                base_url=ollama_url,
                                api_key=ai_api_key
                            )
                            if not report:
                                st.error(f"Post with shortcode '{parsed_shortcode}' not found under @{username}'s public posts.")
                    else:
                        st.error("Unsupported URL. Please enter a valid Instagram or YouTube video link.")
                        
                    # 3. Process Audit output if successfully fetched
                    if report:
                        st.success("Successfully fetched and audited via modular pipeline!")
                        
                        col_info, col_res = st.columns([1, 1], gap="large")
                        
                        with col_info:
                            st.markdown("### 📥 Imported Post Details")
                            st.write(f"**Platform:** {'Instagram' if 'instagram.com' in post_url else 'YouTube'}")
                            st.write(f"**Influencer/Channel:** {report.influencer_handle}")
                            st.write(f"**Timestamp:** {report.timestamp}")
                            
                            # Display OCR scan results
                            st.markdown("---")
                            st.markdown("### 📷 Visual OCR Scan Results")
                            if report.visual_status == "DISCLOSURE_VISIBLE":
                                st.success(f"✅ **Superimposed disclosure labels detected in image:** {report.visual_flags}")
                            elif report.visual_status == "TEXT_NO_DISCLOSURE":
                                st.warning("🔍 **Text detected in image, but no disclosure labels found.**")
                            elif report.visual_status == "NO_TEXT_DETECTED":
                                st.info("ℹ️ No text found in image.")
                            elif report.visual_status == "NO_MEDIA":
                                st.info("🎥 Post contains video file. Skipped visual OCR.")
                            elif report.visual_status == "OCR_NOT_INSTALLED":
                                st.warning("Tesseract OCR is not installed/configured in the environment.")
                                
                        with col_res:
                            st.markdown("### ⚖️ Compliance Audit Verdict")
                            
                            status_color = STATUS_COLORS.get(report.caption_status, "#333")
                            risk_badge = ""
                            if report.risk_level:
                                rc = RISK_COLORS.get(report.risk_level, "#333")
                                risk_badge = f'&nbsp;&nbsp;<span style="background:{rc};color:white;padding:3px 10px;border-radius:10px;font-size:0.85em;">{report.risk_level} RISK</span>'
                                
                            st.markdown(
                                f'<div style="background:{status_color};color:white;padding:16px 20px;border-radius:8px;font-size:1.3em;font-weight:700;">'
                                f'Rule Engine: {report.caption_status}{risk_badge}</div>',
                                unsafe_allow_html=True,
                            )
                            st.write("")
                            
                            if report.caption_flags:
                                st.markdown("**Confirmed Violations & Expert Checks**")
                                for flag in report.caption_flags:
                                    st.error(f"⚠️ Flagged rule: **{flag}**")
                                    
                            if report.caption_status == "COMPLIANT":
                                st.success("No compliance violations detected by the rules engine!")
                                
                            # AI-Powered LangChain Audit Result
                            if enable_ai and report.ai_status:
                                st.divider()
                                st.subheader(f"🤖 AI-Powered Audit ({ai_provider_display})")
                                
                                ai_color = STATUS_COLORS.get(report.ai_status, "#333")
                                st.markdown(
                                    f'<div style="background:{ai_color};color:white;padding:10px 16px;border-radius:8px;font-size:1.1em;font-weight:700;">'
                                    f'AI Audit: {report.ai_status}</div>',
                                    unsafe_allow_html=True,
                                )
                                st.write("")
                                
                                if report.ai_claims:
                                    st.error(f"**AI Extracted Claims:** {', '.join(report.ai_claims)}")
                                    
                                st.markdown(f"**AI Reviewer Explanation:**\n{report.ai_explanation}")
                                st.success(f"💡 **AI Recommended Fix:** {report.ai_recommended_fix}")
                                
                except Exception as e:
                    st.error(f"Ingestion Pipeline Failure: {e}")

# --- TAB 3: AUDIT ACCOUNT WIDE ---
with tab_account:
    st.subheader("📈 Multi-Post Account Compliance Audit")
    st.caption("Scan the recent videos or posts of a creator or brand profile to generate a compliance health score.")
    
    account_url = st.text_input("Account URL", placeholder="https://www.youtube.com/@username or https://www.instagram.com/username/")
    
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        max_posts = st.slider("Number of recent posts to audit", min_value=1, max_value=15, value=5)
        
    run_account_audit = st.button("Run Account Audit", type="primary", use_container_width=True)
    
    if run_account_audit:
        if not account_url.strip():
            st.error("Please enter a profile or channel URL.")
        else:
            with st.spinner("Fetching and auditing posts from pipelines..."):
                try:
                    reports = []
                    channel_name = ""
                    
                    # 1. YouTube Channel audit
                    if "youtube.com" in account_url:
                        handle, cid = extract_youtube_channel_info(account_url)
                        if not handle and not cid:
                            st.error("Could not parse YouTube handle or channel ID from URL.")
                        else:
                            channel_name, reports = run_yt_pipeline(
                                handle or cid, 
                                yt_key, 
                                limit=max_posts, 
                                enable_ai=enable_ai, 
                                provider=ai_provider_val,
                                model_name=ai_model, 
                                base_url=ollama_url,
                                ai_api_key=ai_api_key
                            )
                            st.success(f"Retrieved {len(reports)} videos from YouTube channel: **{channel_name}**")
                                
                    # 2. Instagram Profile audit
                    elif "instagram.com" in account_url:
                        username = [p for p in urlparse(account_url).path.split('/') if p][0]
                        channel_name = f"@{username}"
                        reports = run_ig_pipeline(
                            username, 
                            enable_ai=enable_ai, 
                            provider=ai_provider_val,
                            model_name=ai_model, 
                            base_url=ollama_url,
                            api_key=ai_api_key
                        )
                        st.success(f"Retrieved {len(reports)} posts from Instagram profile: **{channel_name}**")
                    else:
                        st.error("Unsupported account link. Enter a YouTube channel or Instagram profile URL.")
                        
                    # 3. Batch Audit Presentation
                    if reports:
                        st.write("---")
                        st.subheader(f"📊 Compliance Audit Results: {channel_name}")
                        
                        # Metrics dashboard
                        total = len(reports)
                        compliant_cnt = sum(1 for r in reports if r.is_compliant)
                        flagged_cnt = sum(1 for r in reports if r.caption_status == "FLAGGED")
                        expert_review_cnt = sum(1 for r in reports if r.caption_status == "NEEDS EXPERT REVIEW")
                        visual_disclosure_seen_cnt = sum(1 for r in reports if r.visual_status == "DISCLOSURE_VISIBLE")
                        compliance_rate = (compliant_cnt / total) * 100 if total > 0 else 0
                        
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Total Audited", f"{total} posts")
                        m2.metric("Compliance Rate", f"{compliance_rate:.1f}%")
                        m3.metric("Confirmed Violations", f"{flagged_cnt} posts")
                        m4.metric("Visual Disclosures Seen", f"{visual_disclosure_seen_cnt} posts")
                        
                        # Detail list
                        st.write("### 📋 Post-by-Post Audit Details")
                        for idx, report in enumerate(reports):
                            # Create an expander card for each post
                            title_text = f"Post #{idx+1} ({'Instagram' if 'instagram.com' in report.post_url else 'YouTube'}) -- [{report.caption_status}]"
                            
                            with st.expander(title_text):
                                st.write(f"🔗 **Post Link:** [{report.post_url}]({report.post_url})")
                                st.write(f"⏳ **Timestamp:** {report.timestamp}")
                                
                                st.write("**Visual OCR Status:**")
                                vs = report.visual_status
                                if vs == "DISCLOSURE_VISIBLE":
                                    st.success(f"✅ Superimposed disclosure detected: {report.visual_flags}")
                                elif vs == "TEXT_NO_DISCLOSURE":
                                    st.warning("🔍 Text detected, but no disclosure label visible in image.")
                                elif vs == "NO_TEXT_DETECTED":
                                    st.info("ℹ️ No text detected in image.")
                                elif vs == "NO_MEDIA":
                                    st.info("🎥 Video post. Skipping image OCR.")
                                    
                                st.markdown("##### Rule Engine Verdict:")
                                if report.caption_status == "COMPLIANT":
                                    st.success("✅ Compliant -- No issues found.")
                                else:
                                    for flag in report.caption_flags:
                                        st.error(f"❌ Flagged rule: **{flag}**")
                                        
                                if report.risk_level:
                                    st.write(f"⚠️ **Risk Level:** {report.risk_level}")
                                    
                                # Show AI findings if enabled
                                if enable_ai and report.ai_status:
                                    st.markdown("##### 🤖 AI Auditor Verdict:")
                                    st.markdown(f"**Verdict:** {report.ai_status}")
                                    st.markdown(f"**Analysis:** {report.ai_explanation}")
                                    if report.ai_claims:
                                        st.warning(f"**Claims found:** {', '.join(report.ai_claims)}")
                                    st.success(f"💡 **Recommended Fix:** {report.ai_recommended_fix}")
                                    
                except Exception as e:
                    st.error(f"Account Ingestion Failure: {e}")

st.divider()
st.caption(
    "Prototype demo, Phase 1 concierge tool. Rules researched mid-2026 from ASCI's Guidelines for "
    "Influencer Advertising, the Consumer Protection Act / CCPA, and the Promotion and Regulation of "
    "Online Gaming Act, 2025. Re-verify against ascionline.in/social before treating any single rule "
    "as settled fact for a paying client. A human reviewer signs off on every real result -- this tool "
    "explains its reasoning, it doesn't replace judgment."
)
