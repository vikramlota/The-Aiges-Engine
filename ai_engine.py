"""
Vishwas AI -- LangChain AI Compliance Ingestion Layer using Ollama
"""
import json
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

load_dotenv(override=True)

class AIChecklistAudit(BaseModel):
    is_sponsored: bool = Field(
        description="True if the post text indicates it is paid, sponsored, an ad, a brand partnership, or contains affiliate/gifted promotion. False if organic."
    )
    material_disclosure_present: bool = Field(
        description="True if a clear disclosure of material connection (e.g., #ad, #sponsored, #collab, partnership, gift, ad, advertisement, paid, collab) is present in the caption text."
    )
    disclosure_analysis: str = Field(
        description="Detailed analysis of where/how the disclosure was found, or why it counts as missing, buried, or obscured."
    )
    detected_claims: List[str] = Field(
        description="Any specific health, medical, wellness, nutritional, financial, investment, or superiority (e.g. 'No. 1', 'best') claims made in the text."
    )
    suggested_expert_categories: List[str] = Field(
        description="List of ASCI expert review categories that apply to these claims. Valid values: health_wellness_claims, food_beverage_claims, educational_institutions, automotive_claims, awards_rankings_claims, children_targeted, real_money_gaming, virtual_digital_asset."
    )
    reviewer_explanation: str = Field(
        description="Structured, plain-language audit commentary explaining why the post violates or complies with ASCI/CCPA rules."
    )
    recommended_fix: str = Field(
        description="Actionable fix to make the post fully compliant (e.g., 'Move #ad to the first 8 words of the caption', 'Remove unsubstantiated medical claims')."
    )

SYSTEM_PROMPT = """You are an expert AI Marketing Compliance Auditor for the Indian market, validating against ASCI (Advertising Standards Council of India) and CCPA (Central Consumer Protection Authority) rules.

Analyze the given post caption carefully. Evaluate:
1. **Material Connection**: Is there a commercial relationship (sponsored, paid collab, ad, affiliate, free gift)?
2. **Disclosure Prominence & Placement**: Is the disclosure prominent? (Buried at the end of a long hashtag block or past the 'see more' cutoff is a violation. ASCI requires text disclosures to be in the first 8 words).
3. **Indian Regional Languages**: Valid disclosures can be in English, Hindi, Hinglish, or regional terms (e.g. "विज्ञापन", "साझेदारी", "ad", "partnership", "collab", "sponsored").
4. **Special Claims**: Flag health, wellness, food, financial, educational, superiority, gaming, or VDA (Crypto) claims.

Output a structured JSON response matching the schema. Do not include any conversational filler."""

import os

def audit_post_with_ai(
    caption: str, 
    platform: str, 
    provider: str = "ollama",
    model_name: str = "qwen3:8b", 
    base_url: str = "http://localhost:11434",
    api_key: Optional[str] = None
) -> AIChecklistAudit:
    """
    Leverages LangChain to perform an LLM compliance audit of the caption text using Ollama, Gemini, or Groq.
    """
    if not caption or not caption.strip():
        return AIChecklistAudit(
            is_sponsored=False,
            material_disclosure_present=False,
            disclosure_analysis="No text provided to analyze.",
            detected_claims=[],
            suggested_expert_categories=[],
            reviewer_explanation="No text was provided.",
            recommended_fix="Provide caption text to audit."
        )

    # Initialize the LLM based on provider
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=model_name or "gemini-3.6-flash",
            google_api_key=api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            temperature=0
        )
    elif provider == "groq":
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            model=model_name or "llama-3.3-70b-versatile",
            groq_api_key=api_key or os.getenv("GROQ_API_KEY"),
            temperature=0
        )
    else:  # "ollama"
        from langchain_ollama import ChatOllama
        llm = ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0,
            format="json"  # Ensure Ollama enforces JSON mode
        )

    # Enforce Pydantic structure
    structured_llm = llm.with_structured_output(AIChecklistAudit)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("user", "Platform: {platform}\n\nCaption text to audit:\n{caption}")
    ])

    chain = prompt | structured_llm
    
    # Run the chain
    return chain.invoke({"platform": platform, "caption": caption})
