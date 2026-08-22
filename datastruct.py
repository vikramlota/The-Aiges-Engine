from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class VisualAuditResult:
    visual_status: str  # "CLEAN", "FLAGGED", or "ERROR"
    flags: List[str] = field(default_factory=list)
    extracted_text: str = ""

@dataclass
class UnifiedAuditReport:
    post_id: str
    influencer_handle: str
    post_url: str
    timestamp: str
    caption_status: str  
    caption_flags: List[str]
    visual_status: str   
    visual_flags: List[str]
    is_compliant: bool
    # NEW FIELDS FOR PHASE 1 ENGINE SYNC
    risk_level: str = "LOW"
    expert_review_flags: List[str] = field(default_factory=list)
    # AI AUDIT LAYER INTEGRATION
    ai_status: Optional[str] = None
    ai_explanation: Optional[str] = None
    ai_recommended_fix: Optional[str] = None
    ai_claims: List[str] = field(default_factory=list)