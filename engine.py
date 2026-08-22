"""
Vishwas AI -- Phase 1 disclosure compliance rule engine.

Given structured details about a single post, decides whether it complies
with ASCI/CCPA disclosure rules, and -- critically -- explains why in
plain language. This automates columns J-R of the "Audit Checklist"
spreadsheet tab; a human still owns "Reviewer Explanation" and
"Recommended Fix" (the two columns after that), since those require
judgment this engine deliberately doesn't try to replace.

Design principle carried over from the project's compliance gate: every
FLAGGED or PENDING result comes with a plain-language reason attached.
There is no bare pass/fail anywhere in this module.
"""

from dataclasses import dataclass, field
from typing import Optional

from rules import (
    APPROVED_LABELS,
    AMBIGUOUS_LABELS,
    CONTENT_TYPES,
    MATERIAL_CONNECTIONS,
    CONFIRMED_ABSENT,
    VIDEO_VERBAL_DISCLOSURE_MAX_SECOND,
    SHORT_LABELS,
    ASCI_CATEGORIES,
    risk_of,
    highest_risk,
    RISK_ORDER,
)

EXPERT_REVIEW = "EXPERT_REVIEW_REQUIRED"


@dataclass
class PostInput:
    """One post to audit. Optional fields follow one rule throughout:
    None = not reviewed yet (engine will mark that check PENDING REVIEW).
    A real value (True/False, a timestamp, or CONFIRMED_ABSENT) = a human
    actually looked and is telling the engine what they saw.
    """

    platform: str
    content_type: str                          # one of rules.CONTENT_TYPES
    material_connection: str                   # one of rules.MATERIAL_CONNECTIONS keys
    caption: str = ""

    is_virtual_influencer: bool = False
    makes_health_finance_or_technical_claim: bool = False

    # video/audio_podcast only. Integer second of verbal disclosure,
    # CONFIRMED_ABSENT (-1) if confirmed never spoken, or None if pending.
    video_verbal_disclosure_second: Optional[int] = None
    video_overlay_covers_sponsored_segment: Optional[bool] = None   # video/youtube_short only
    story_label_superimposed: Optional[bool] = None                # reel_story only
    ai_disclosure_present_and_persistent: Optional[bool] = None     # only if is_virtual_influencer
    credentials_or_substantiation_shown: Optional[bool] = None      # only if makes_health_finance_or_technical_claim

    # -- New: coverage beyond disclosure, added to reach "every ASCI rule." --
    # Mechanically automatable (see rules.ASCI_CATEGORIES for why each tier
    # is classified the way it is):
    ai_generated_or_enhanced: bool = False
    ai_content_label_present: Optional[bool] = None
    names_specific_competitor: bool = False                         # human-observed, not text-guessed
    unqualified_superiority_claim: Optional[bool] = None
    product_category: Optional[str] = None                          # "real_money_gaming" / "virtual_digital_asset" / None
    mandatory_disclaimer_present: Optional[bool] = None

    # Categories this engine deliberately does NOT try to auto-verify --
    # tag any that apply (e.g. ["health_wellness_claims"]) and the engine
    # will route them to a human/expert reviewer with the right citation,
    # rather than guessing. See rules.ASCI_CATEGORIES for the full list.
    content_categories: list = field(default_factory=list)

    client: str = ""
    influencer_handle: str = ""
    post_url: str = ""

    def __post_init__(self):
        if self.content_type not in CONTENT_TYPES:
            raise ValueError(f"Unknown content_type {self.content_type!r}. Must be one of {CONTENT_TYPES}.")
        if self.material_connection not in MATERIAL_CONNECTIONS:
            raise ValueError(
                f"Unknown material_connection {self.material_connection!r}. "
                f"Must be one of {list(MATERIAL_CONNECTIONS)}."
            )
        if self.product_category is not None and self.product_category not in ("real_money_gaming", "virtual_digital_asset"):
            raise ValueError("product_category must be 'real_money_gaming', 'virtual_digital_asset', or None.")
        unknown = [c for c in self.content_categories if c not in ASCI_CATEGORIES]
        if unknown:
            raise ValueError(f"Unknown content_categories {unknown}. Must be from rules.ASCI_CATEGORIES: {list(ASCI_CATEGORIES)}.")


@dataclass
class CheckOutcome:
    passed: bool
    reason: str


@dataclass
class AuditResult:
    status: str            # "COMPLIANT" / "FLAGGED" / "NEEDS EXPERT REVIEW" / "PENDING REVIEW"
    checks: dict            # rule_name -> True / False / None / "EXPERT_REVIEW_REQUIRED"
    explanations: dict      # rule_name -> reason, for entries that are False or EXPERT_REVIEW_REQUIRED
    violations: list        # rule_names confirmed False, in check order
    expert_review: list     # rule_names routed to a human expert, in check order
    post: PostInput

    @property
    def risk_level(self) -> str:
        """Single most severe risk level across everything flagged or
        routed to expert review on this post. None if it's clean."""
        return highest_risk(self.violations + self.expert_review)

    def summary(self) -> str:
        if self.status == "COMPLIANT":
            return "COMPLIANT -- no violations found."
        parts = []
        if self.violations:
            parts.append(f"{len(self.violations)} confirmed issue(s):")
            for name in self.violations:
                parts.append(f"  - [{risk_of(name)}] {SHORT_LABELS.get(name, name)}: {self.explanations[name]}")
        if self.expert_review:
            parts.append(f"{len(self.expert_review)} item(s) routed to expert review (not auto-verified):")
            for name in self.expert_review:
                label = ASCI_CATEGORIES.get(name, {}).get("label", name)
                parts.append(f"  - [{risk_of(name)}] {label}: {self.explanations[name]}")
        pending = [n for n, v in self.checks.items() if v is None]
        if pending:
            parts.append("Not yet reviewed:")
            for name in pending:
                parts.append(f"  - {SHORT_LABELS.get(name, name)}")
        risk_line = f" (highest risk: {self.risk_level})" if self.risk_level else ""
        return f"{self.status}{risk_line} --\n" + "\n".join(parts)

    def to_checklist_row(self) -> dict:
        """Mirrors the 'Audit Checklist' tab's column layout, so a batch
        of results can be exported straight into that spreadsheet. Note:
        EXPERT_REVIEW_REQUIRED exports as 'EXPERT' -- the current
        spreadsheet's Y/N/N/A dropdown would need that added as a 4th
        option to display it natively; until then treat 'EXPERT' as a
        signal to check the Violation Summary column for the reason."""

        def yn(v):
            if v is True:
                return "Y"
            if v is False:
                return "N"
            if v == EXPERT_REVIEW:
                return "EXPERT"
            return "N/A"

        flagged_and_expert = self.violations + self.expert_review
        return {
            "Client / Brand": self.post.client,
            "Influencer / Account Handle": self.post.influencer_handle,
            "Post URL": self.post.post_url,
            "Platform": self.post.platform,
            "Content Type": self.post.content_type,
            "Material Connection": self.post.material_connection,
            "Approved Label?": yn(self.checks.get("approved_label")),
            "Placement OK?": yn(self.checks.get("placement")),
            "Verbal Timing OK? (video/audio)": yn(self.checks.get("verbal_timing")),
            "Overlay Throughout? (video)": yn(self.checks.get("overlay_throughout")),
            "Story Superimposed?": yn(self.checks.get("story_superimposed")),
            "AI Disclosed? (virtual influencer)": yn(self.checks.get("ai_disclosure")),
            "Credentials Shown? (claims)": yn(self.checks.get("credentials")),
            "AI Content Labeling?": yn(self.checks.get("ai_content_labeling")),
            "Comparative Advertising OK?": yn(self.checks.get("comparative_advertising")),
            "Real Money Gaming?": yn(self.checks.get("real_money_gaming")),
            "VDA Disclaimer?": yn(self.checks.get("virtual_digital_assets")),
            "Status": self.status,
            "Highest Risk": self.risk_level or "",
            "Violation / Review Summary": ", ".join(
                f"{SHORT_LABELS.get(v, ASCI_CATEGORIES.get(v, {}).get('label', v))} [{risk_of(v)}]"
                for v in flagged_and_expert
            ),
        }


def _check_approved_label(caption: str) -> CheckOutcome:
    caption_lower = caption.lower()
    found_approved = [lbl for lbl in APPROVED_LABELS if lbl in caption_lower]
    found_ambiguous = [lbl for lbl in AMBIGUOUS_LABELS if lbl in caption_lower]

    if found_approved:
        return CheckOutcome(True, f"Found approved disclosure label(s): {', '.join(found_approved)}.")
    if found_ambiguous:
        return CheckOutcome(
            False,
            f"Only ambiguous label(s) found ({', '.join(found_ambiguous)}) -- ASCI's current "
            f"enforcement treats these as too vague on their own. Add '#ad' explicitly.",
        )
    return CheckOutcome(False, "No recognized disclosure label (#ad, #sponsored, #promo, #partnership) found in the caption.")


def _check_placement(caption: str) -> CheckOutcome:
    if not caption.strip():
        return CheckOutcome(False, "No caption text to check placement against.")

    all_labels = APPROVED_LABELS + AMBIGUOUS_LABELS
    first_words = " ".join(caption.split()[:8]).lower()
    label_up_front = any(lbl in first_words for lbl in all_labels)

    if label_up_front:
        return CheckOutcome(True, "Disclosure label appears within the first few words of the caption, visible without scrolling.")

    last_line = caption.split("\n")[-1]
    tail_hashtags = [w for w in last_line.split() if w.startswith("#")]
    if len(tail_hashtags) >= 3 and any(lbl in last_line.lower() for lbl in all_labels):
        return CheckOutcome(
            False,
            "Disclosure label only appears buried inside a block of hashtags at the end -- ASCI "
            "requires it to be upfront and immediately visible, not buried.",
        )
    return CheckOutcome(False, "Disclosure label is not positioned where an average viewer would see it immediately.")


def _check_ai_content_labeling(post: "PostInput") -> CheckOutcome:
    if post.ai_content_label_present:
        return CheckOutcome(True, "AI-generated/enhanced content carries a visible AI label.")
    return CheckOutcome(
        False,
        "AI-generated or AI-enhanced content has no visible label (e.g. 'Created using AI' / "
        "'Enhanced using AI') -- required under ASCI's 2026 AI-content guidelines for anything "
        "beyond routine editing or decorative effects.",
    )


def _check_comparative_advertising(post: "PostInput") -> CheckOutcome:
    return CheckOutcome(
        False,
        "Names a specific competitor and makes a superiority claim flagged as unqualified -- ASCI "
        "requires comparative claims to be factual and substantiated, not just asserted.",
    )


def _check_mandatory_disclaimer(category_label: str) -> CheckOutcome:
    return CheckOutcome(
        False,
        f"{category_label} ad has no visible mandatory disclaimer -- required under ASCI's "
        f"category-specific guidelines for this product type.",
    )


def audit_post(post: PostInput) -> AuditResult:
    checks: dict = {}
    explanations: dict = {}
    violations: list = []
    expert_review: list = []

    def record(name: str, outcome: CheckOutcome):
        checks[name] = outcome.passed
        if outcome.passed is False:
            violations.append(name)
            explanations[name] = outcome.reason

    disclosure_applies = post.material_connection != "none_genuine"

    if disclosure_applies:
        record("approved_label", _check_approved_label(post.caption))
        record("placement", _check_placement(post.caption))

    if disclosure_applies and post.content_type in ("video", "youtube_short"):
        sec = post.video_verbal_disclosure_second
        if sec is None:
            checks["verbal_timing"] = None
        elif sec == CONFIRMED_ABSENT:
            record("verbal_timing", CheckOutcome(False, "Confirmed: no verbal disclosure anywhere in the video."))
        elif sec > VIDEO_VERBAL_DISCLOSURE_MAX_SECOND:
            record("verbal_timing", CheckOutcome(
                False, f"Verbal disclosure happens at second {sec}, after the {VIDEO_VERBAL_DISCLOSURE_MAX_SECOND}-second window."
            ))
        else:
            record("verbal_timing", CheckOutcome(True, f"Verbal disclosure at second {sec}, within the required window."))

        overlay = post.video_overlay_covers_sponsored_segment
        if overlay is None:
            checks["overlay_throughout"] = None
        else:
            record("overlay_throughout", CheckOutcome(
                overlay,
                "Overlay stays visible throughout the sponsored segment." if overlay
                else "Text overlay does not stay visible for the entire sponsored segment.",
            ))

    elif disclosure_applies and post.content_type == "audio_podcast":
        sec = post.video_verbal_disclosure_second
        if sec is None:
            checks["verbal_timing"] = None
        elif sec == CONFIRMED_ABSENT or sec > VIDEO_VERBAL_DISCLOSURE_MAX_SECOND:
            record("verbal_timing", CheckOutcome(False, "No clear verbal disclosure at the start of the sponsored segment."))
        else:
            record("verbal_timing", CheckOutcome(True, "Verbal disclosure made at the start of the sponsored segment."))

    if disclosure_applies and post.content_type == "reel_story":
        sup = post.story_label_superimposed
        if sup is None:
            checks["story_superimposed"] = None
        else:
            record("story_superimposed", CheckOutcome(
                sup,
                "Disclosure is superimposed directly on the image/video, visible for the full duration." if sup
                else "Disclosure is not superimposed directly on the image/video itself.",
            ))

    if post.is_virtual_influencer:
        ai = post.ai_disclosure_present_and_persistent
        if ai is None:
            checks["ai_disclosure"] = None
        else:
            record("ai_disclosure", CheckOutcome(
                ai,
                "AI/virtual persona is persistently and prominently disclosed." if ai
                else "No persistent, prominent disclosure that this is an AI/virtual persona, separate from the paid-partnership label.",
            ))

    if post.makes_health_finance_or_technical_claim:
        cred = post.credentials_or_substantiation_shown
        if cred is None:
            checks["credentials"] = None
        else:
            record("credentials", CheckOutcome(
                cred,
                "Relevant credentials or substantiation are shown alongside the claim." if cred
                else "Health/finance/technical claim made with no visible qualifications or substantiation.",
            ))

    # -- Automated / partial-automated categories beyond disclosure --
    if post.ai_generated_or_enhanced:
        label = post.ai_content_label_present
        if label is None:
            checks["ai_content_labeling"] = None
        else:
            record("ai_content_labeling", _check_ai_content_labeling(post))

    if post.names_specific_competitor:
        claim = post.unqualified_superiority_claim
        if claim is None:
            checks["comparative_advertising"] = None
        elif claim:
            record("comparative_advertising", _check_comparative_advertising(post))
        else:
            checks["comparative_advertising"] = True

    if post.product_category == "real_money_gaming":
        # No disclaimer makes this legal anymore -- the Promotion and
        # Regulation of Online Gaming Act, 2025 (in force May 1, 2026) bans
        # advertising real money games outright. Any post in this category
        # is an automatic, unconditional flag; mandatory_disclaimer_present
        # is not consulted here on purpose.
        record("real_money_gaming", CheckOutcome(
            False,
            "Advertising a real money game is completely prohibited in India under the Promotion "
            "and Regulation of Online Gaming Act, 2025 (in force since May 1, 2026) -- this isn't a "
            "disclaimer problem, the ad shouldn't run at all. Advertising it carries criminal "
            "penalties, not just a fine.",
        ))

    if post.product_category == "virtual_digital_asset":
        d = post.mandatory_disclaimer_present
        if d is None:
            checks["virtual_digital_assets"] = None
        else:
            record("virtual_digital_assets", CheckOutcome(d, "Mandatory VDA risk disclaimer is visible.") if d
                   else _check_mandatory_disclaimer("Virtual digital asset (crypto/NFT)"))

    # -- Categories this engine won't pretend to auto-verify --
    for cat in post.content_categories:
        meta = ASCI_CATEGORIES.get(cat)
        if meta and meta["automated"] is False:
            checks[cat] = EXPERT_REVIEW
            explanations[cat] = (
                f"{meta['label']} applies to this post ({meta['source']}). This needs genuine "
                f"subject-matter judgment -- claim substantiation, safety data, accreditation proof, "
                f"or similar -- that a compliance engine has no business guessing at. Route to a "
                f"qualified reviewer rather than treating this as pass/fail."
            )
            expert_review.append(cat)

    if violations:
        status = "FLAGGED"
    elif expert_review:
        status = "NEEDS EXPERT REVIEW"
    elif any(v is None for v in checks.values()):
        status = "PENDING REVIEW"
    else:
        status = "COMPLIANT"

    return AuditResult(
        status=status, checks=checks, explanations=explanations,
        violations=violations, expert_review=expert_review, post=post,
    )


def batch_audit(posts: list) -> list:
    return [audit_post(p) for p in posts]


def aggregate_summary(results: list) -> dict:
    """Mirrors the 'Summary Dashboard' tab: overall counts, a breakdown of
    which specific rule gets broken most often, which ASCI categories are
    showing up as needing expert review, and -- the actual triage
    question -- how many posts carry each risk level, worst first."""
    counts = {"COMPLIANT": 0, "FLAGGED": 0, "NEEDS EXPERT REVIEW": 0, "PENDING REVIEW": 0}
    violation_counts = {name: 0 for name in SHORT_LABELS}
    expert_review_counts = {}
    risk_counts = {level: 0 for level in RISK_ORDER}

    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        for v in r.violations:
            violation_counts[v] = violation_counts.get(v, 0) + 1
        for e in r.expert_review:
            label = ASCI_CATEGORIES.get(e, {}).get("label", e)
            expert_review_counts[label] = expert_review_counts.get(label, 0) + 1
        if r.risk_level:
            risk_counts[r.risk_level] += 1

    total = len(results)
    return {
        "total_audited": total,
        "compliant": counts["COMPLIANT"],
        "flagged": counts["FLAGGED"],
        "needs_expert_review": counts["NEEDS EXPERT REVIEW"],
        "pending_review": counts["PENDING REVIEW"],
        "compliance_rate": round(counts["COMPLIANT"] / total, 3) if total else None,
        "violations_by_rule": {SHORT_LABELS[k]: v for k, v in violation_counts.items() if v > 0},
        "expert_review_by_category": expert_review_counts,
        "posts_by_highest_risk": {k: v for k, v in risk_counts.items() if v > 0},
    }
