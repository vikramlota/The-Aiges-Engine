"""
Rule definitions for Vishwas AI's Phase 1 disclosure compliance engine.

These encode ASCI's Guidelines for Influencer Advertising in Digital Media
and Consumer Protection Act (CCPA) enforcement patterns, as researched
mid-2026. This is the coded twin of the "Rules Reference" tab in the
companion audit checklist spreadsheet -- same rules, same short labels,
now expressed as constants the engine actually runs against instead of
a table a human reads.

ASCI updates its guidance periodically. Re-verify against
ascionline.in/social before relying on this for a paying client.
"""

# Recognized disclosure labels per ASCI's original approved list.
APPROVED_LABELS = ["#ad", "#sponsored", "#promo", "#partnership"]

# Technically also on ASCI's original list, but current enforcement
# commentary treats these as too ambiguous when used alone. Flagged as a
# violation unless an approved label above is also present.
AMBIGUOUS_LABELS = ["#collab", "#gift", "#gifted", "#thanks", "#thankyou"]

PLATFORMS = ["Instagram", "YouTube", "Facebook", "X/Twitter", "LinkedIn", "Other"]

CONTENT_TYPES = ["static_post", "reel_story", "video", "youtube_short", "audio_podcast"]

# Sentinel used in *_second fields to mean "reviewed, and confirmed there
# was no verbal disclosure anywhere" -- distinct from None, which means
# "not reviewed yet."
CONFIRMED_ABSENT = -1

MATERIAL_CONNECTIONS = {
    "paid": "Monetary payment for the post.",
    "gifted_barter": "Free product or barter arrangement.",
    "affiliate": "Affiliate marketing / commission on sales.",
    "family_business": "Family, employment, or business relationship with the brand.",
    "none_genuine": "Genuinely bought and liked, with no connection to the brand -- no disclosure required.",
}

VIDEO_VERBAL_DISCLOSURE_MAX_SECOND = 10

# ---------------------------------------------------------------------------
# Full ASCI taxonomy, added at the user's request to cover "every ASCI rule
# for marketing" -- not just influencer disclosure.
#
# Each category is tagged "automated": True / "partial" / False, based on an
# honest technical judgment, not ambition:
#   True    -- mechanical to check from post metadata/text (label present,
#              positioned correctly). Fully automated below.
#   partial -- automatable IF a human has already made one judgment call
#              (e.g. "does this name a competitor"); the engine checks the
#              rule that follows from it, but doesn't make the judgment
#              call itself.
#   False   -- requires subject-matter expertise (medical, legal, financial,
#              engineering) this engine has no business pretending to have.
#              These are routed to "NEEDS EXPERT REVIEW", never auto-passed
#              or auto-failed. Faking precision here would violate the
#              project's core no-black-box rule worse than not checking at
#              all -- a confident wrong answer is more dangerous than an
#              honest "a human needs to look at this."
# ---------------------------------------------------------------------------
ASCI_CATEGORIES = {
    "disclosure": {
        "label": "Influencer / Paid-Partnership Disclosure",
        "source": "ASCI Guidelines for Influencer Advertising in Digital Media",
        "automated": True,
    },
    "ai_content_labeling": {
        "label": "AI-Generated / AI-Enhanced Content Labeling",
        "source": "ASCI draft guidelines on labelling AI-generated ads (2026)",
        "automated": True,
    },
    "comparative_advertising": {
        "label": "Comparative Advertising",
        "source": "ASCI Code, Chapter IV -- Fair in Competition",
        "automated": "partial",
    },
    "real_money_gaming": {
        "label": "Real Money Gaming",
        "source": "Promotion and Regulation of Online Gaming Act, 2025 + Rules, 2026 (in force May 1, 2026) -- "
                   "advertising real money games is now completely prohibited in India, not a disclaimer matter",
        "automated": True,
    },
    "virtual_digital_assets": {
        "label": "Virtual Digital Assets (Crypto / NFT)",
        "source": "ASCI Guidelines for Advertising of Virtual Digital Assets",
        "automated": "partial",
    },
    "surrogate_advertising": {
        "label": "Surrogate / Brand-Extension Advertising",
        "source": "ASCI Code, Chapter III Clause 3.6(a) -- brand extension criteria for restricted products (liquor, tobacco)",
        "automated": False,
    },
    "health_wellness_claims": {
        "label": "Health, Wellness & Nutraceutical Claims",
        "source": "ASCI Code plus Health/Wellness/OTC/Nutraceutical advertising guidelines",
        "automated": False,
    },
    "food_beverage_claims": {
        "label": "Food & Beverage Claims",
        "source": "ASCI Guidelines on Advertising of Foods & Beverages",
        "automated": False,
    },
    "educational_institutions": {
        "label": "Educational Institutions & Programs",
        "source": "ASCI Guidelines for Advertising of Educational Institutions and Programs",
        "automated": False,
    },
    "automotive_claims": {
        "label": "Automotive Safety / Performance Claims",
        "source": "ASCI Guidelines for Advertisements Depicting Automotive Vehicles",
        "automated": False,
    },
    "celebrity_due_diligence": {
        "label": "Celebrity Endorsement Due Diligence",
        "source": "ASCI Code -- celebrity/endorsement due-diligence guidelines",
        "automated": False,
    },
    "awards_rankings_claims": {
        "label": "Awards / Rankings Claims",
        "source": "ASCI guidelines on claimed awards or rankings",
        "automated": False,
    },
    "children_targeted": {
        "label": "Advertising Addressed to Children",
        "source": "ASCI Code, Chapters II-III -- protection of children",
        "automated": False,
    },
    "general_truthfulness": {
        "label": "General Truthful & Honest Representation",
        "source": "ASCI Code, Chapter I -- Truthful & Honest Representation",
        "automated": False,
    },
}

# Short labels used in violation summaries -- match the "Audit Checklist"
# spreadsheet's column headers exactly, so summaries read the same whether
# they came from a human's manual review or this engine.
SHORT_LABELS = {
    "approved_label": "Approved Label",
    "placement": "Placement",
    "verbal_timing": "Verbal Timing",
    "overlay_throughout": "Overlay Throughout",
    "story_superimposed": "Story Superimposed",
    "ai_disclosure": "AI Disclosure",
    "credentials": "Credentials",
    "ai_content_labeling": "AI Content Labeling",
    "comparative_advertising": "Comparative Advertising",
    "real_money_gaming": "Real Money Gaming (Banned)",
    "virtual_digital_assets": "VDA Disclaimer",
}

RULE_DESCRIPTIONS = {
    "approved_label": "Caption must use a recognized disclosure label (#ad, #sponsored, #promo, or #partnership).",
    "placement": "The label must be upfront -- first line of the caption, not buried in a hashtag block or requiring a tap to see.",
    "verbal_timing": "Video: verbal disclosure within the first 10 seconds. Audio: disclosure stated at the start of the sponsored segment.",
    "overlay_throughout": "A visible text disclosure overlay must remain on screen for the entire sponsored portion of the video.",
    "story_superimposed": "For Stories/ephemeral content, the disclosure must be superimposed on the image/video itself and stay visible the whole time it's shown.",
    "ai_disclosure": "Virtual/AI influencer accounts must persistently and prominently disclose they are not a real person -- separate from any paid-partnership disclosure.",
    "credentials": "Health, finance, or technical performance claims need visible qualifications or substantiation.",
    "ai_content_labeling": "AI-generated or AI-enhanced content beyond routine editing needs a visible label such as 'Created using AI' or 'Enhanced using AI'.",
    "comparative_advertising": "Naming a competitor and claiming superiority requires factual, substantiated backing -- not just an assertion.",
    "real_money_gaming": "Advertising a real money game at all is banned in India as of May 2026 -- no disclaimer can fix this; the ad shouldn't run.",
    "virtual_digital_assets": "Crypto/NFT ('VDA') ads need a visible mandatory risk disclaimer.",
}

# ---------------------------------------------------------------------------
# 5-level risk scale, added to help triage which flagged/expert-review items
# actually need attention first -- not every violation carries the same
# consequence, and treating them as equally urgent buries the ones that do.
#
# Assigned by realistic consequence (legal exposure, consumer harm, current
# enforcement intensity), not by how easy each check was to build:
#   CRITICAL -- potential criminal liability, a banned product/service, or
#               real physical/financial harm to consumers. Fix or escalate
#               immediately; don't let this post go out.
#   HIGH     -- a clear, actively-enforced violation with real fines (CCPA
#               penalties up to Rs 50 lakh) or serious legal/reputational risk.
#   MEDIUM   -- a genuine violation, but usually lower fines, or a real (if
#               imperfect) compliance attempt already in place.
#   LOW      -- a technical/procedural gap, often in a newer or less-enforced
#               rule area.
#   ADVISORY -- best-practice guidance rather than a hard, consistently
#               enforced requirement.
# ---------------------------------------------------------------------------
RISK_CRITICAL = "CRITICAL"
RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
RISK_ADVISORY = "ADVISORY"

# Most to least severe -- used for sorting and for picking a post's
# single "highest risk" across everything flagged on it.
RISK_ORDER = [RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW, RISK_ADVISORY]

RISK_NOTES = {
    RISK_CRITICAL: "Potential criminal liability, a banned product/service, or real physical/financial harm to consumers. Fix or escalate immediately.",
    RISK_HIGH: "A clear, actively-enforced violation with real fines (CCPA penalties up to Rs 50 lakh) or serious legal/reputational exposure.",
    RISK_MEDIUM: "A genuine violation, but usually lower fines, or a real (if imperfect) compliance attempt already in place.",
    RISK_LOW: "A technical or procedural gap, often in a newer or less-enforced rule area.",
    RISK_ADVISORY: "Best-practice guidance rather than a hard, consistently-enforced requirement.",
}

RISK_LEVELS = {
    # -- Disclosure sub-checks --
    "approved_label": RISK_HIGH,           # the single most-enforced ASCI issue (~94% of cases)
    "placement": RISK_MEDIUM,              # disclosed, just ineffectively -- real, but lower culpability
    "verbal_timing": RISK_MEDIUM,
    "overlay_throughout": RISK_LOW,
    "story_superimposed": RISK_MEDIUM,
    "ai_disclosure": RISK_HIGH,            # deception about whether you're even talking to a real person
    "credentials": RISK_HIGH,              # necessary check feeding into a potential CRITICAL claim
    # -- Automated / partial-automated categories beyond disclosure --
    "ai_content_labeling": RISK_LOW,       # new rule, enforcement still nascent as of mid-2026
    "comparative_advertising": RISK_HIGH,  # ASCI risk + competitor litigation risk
    "real_money_gaming": RISK_CRITICAL,    # advertising it at all is now a criminal offense
    "virtual_digital_assets": RISK_HIGH,
    # -- Expert-review-only categories --
    "surrogate_advertising": RISK_CRITICAL,     # COTPA criminal liability territory
    "health_wellness_claims": RISK_CRITICAL,    # real physical harm risk (Bournvita/Patanjali-scale)
    "food_beverage_claims": RISK_HIGH,
    "educational_institutions": RISK_MEDIUM,
    "automotive_claims": RISK_HIGH,             # potential physical safety implications
    "celebrity_due_diligence": RISK_MEDIUM,
    "awards_rankings_claims": RISK_ADVISORY,
    "children_targeted": RISK_CRITICAL,         # protecting a vulnerable population, a regulatory priority everywhere
    "general_truthfulness": RISK_MEDIUM,
}


def risk_of(rule_name: str) -> str:
    """Risk level for any check/category name. Defaults to MEDIUM for
    anything not explicitly mapped, rather than silently returning None."""
    return RISK_LEVELS.get(rule_name, RISK_MEDIUM)


def highest_risk(rule_names) -> str:
    """Most severe risk level among a list of rule/category names. Returns
    None if the list is empty (nothing to rank)."""
    names = list(rule_names)
    if not names:
        return None
    present = {risk_of(n) for n in names}
    for level in RISK_ORDER:
        if level in present:
            return level
    return RISK_MEDIUM
