from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class ClipUploadResponse(BaseModel):
    clip_id: str
    status: str = "processing"

class ClipStatusResponse(BaseModel):
    clip_id: str
    status: str
    stage: Optional[str] = None
    error_message: Optional[str] = None

class Source(BaseModel):
    name: str
    url: str

class ClaimVerdict(BaseModel):
    claim_text: str
    verdict: str
    confidence: int
    summary: str
    sources: List[Source]

class VerdictResponse(BaseModel):
    clip_id: str
    claims: List[ClaimVerdict]

class HistoryItem(BaseModel):
    clip_id: str
    verdict: str
    generated_at: str

class HistoryResponse(BaseModel):
    total: int
    results: List[HistoryItem]

class Clip(Base):
    __tablename__ = "clips"
    clip_id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    duration_sec = Column(Float, nullable=True)
    storage_path = Column(String)
    status = Column(String, default="processing")
    stage = Column(String, default="preprocessing")
    error_message = Column(String, nullable=True)

class Claim(Base):
    __tablename__ = "claims"
    claim_id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    clip_id = Column(String, ForeignKey("clips.clip_id"))
    claim_type = Column(String)
    verification_target = Column(String)
    explicit_claims = Column(JSON)
    implied_claims = Column(JSON)
    mcie_confidence = Column(Float)

class VerificationPackage(Base):
    __tablename__ = "verification_packages"
    package_id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    claim_id = Column(String, ForeignKey("claims.claim_id"))
    verification_query = Column(String)
    priority_keyframes = Column(JSON)
    package_json = Column(JSON)

class Verdict(Base):
    __tablename__ = "verdicts"
    verdict_id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    package_id = Column(String, ForeignKey("verification_packages.package_id"))
    clip_id = Column(String, ForeignKey("clips.clip_id"))
    claim_text = Column(String)
    verdict = Column(String)
    confidence = Column(Float)
    summary = Column(String)
    sources = Column(JSON)
    generated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
