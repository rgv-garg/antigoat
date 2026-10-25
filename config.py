"""All settings in one place. Values come from .env (see .env.example).

Nothing else in the repo should read os.environ directly - import SETTINGS instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional
    pass

# Mem0 backend: no telemetry (it also opens a second local Qdrant that clashes between instances)
os.environ.setdefault("MEM0_TELEMETRY", "False")


def _f(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class LLMRole:
    """Settings for one LLM 'role' (Sahayak or attacker)."""

    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    thinking: bool  # Nemotron reasoning mode on/off


@dataclass
class Settings:
    # --- LLM endpoints. "mock" = offline fake LLM (no GPU, no key) for testing the plumbing.
    sahayak: LLMRole = field(
        default_factory=lambda: LLMRole(
            base_url=_f("SAHAYAK_BASE_URL", _f("LLM_BASE_URL", "mock")),
            api_key=_f("SAHAYAK_API_KEY", _f("LLM_API_KEY", "not-needed")),
            model=_f("SAHAYAK_MODEL", _f("LLM_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16")),
            temperature=float(_f("SAHAYAK_TEMPERATURE", "0")),
            max_tokens=int(_f("SAHAYAK_MAX_TOKENS", "512")),
            thinking=_f("SAHAYAK_THINKING", "false").lower() == "true",
        )
    )
    attacker: LLMRole = field(
        default_factory=lambda: LLMRole(
            base_url=_f("ATTACKER_BASE_URL", _f("LLM_BASE_URL", "mock")),
            api_key=_f("ATTACKER_API_KEY", _f("LLM_API_KEY", "not-needed")),
            model=_f("ATTACKER_MODEL", _f("LLM_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16")),
            temperature=float(_f("ATTACKER_TEMPERATURE", "0.7")),
            max_tokens=int(_f("ATTACKER_MAX_TOKENS", "4096")),
            thinking=_f("ATTACKER_THINKING", "true").lower() == "true",
        )
    )

    # --- Embeddings: "hash" = built-in, no download (fine for testing). "BAAI/bge-m3" for real runs.
    embed_model: str = _f("EMBED_MODEL", "hash")

    # --- Sarvam voice (demo only)
    sarvam_api_key: str = _f("SARVAM_API_KEY", "")
    sarvam_stt_model: str = _f("SARVAM_STT_MODEL", "saaras:v4")
    sarvam_tts_model: str = _f("SARVAM_TTS_MODEL", "bulbul:v4-flash")
    sarvam_speaker: str = _f("SARVAM_SPEAKER", "simran_en_customer")

    # --- Runner
    max_workers: int = int(_f("MAX_WORKERS", "16"))  # parallel LLM requests
    request_timeout: float = float(_f("REQUEST_TIMEOUT", "120"))
    summary_mode: str = _f("SUMMARY_MODE", "concat")  # concat | llm

    # --- How "real" Sahayak is.
    #   extract_mode llm  = Intake uses the LLM to pull facts out of what the citizen says
    #                       (canaries get into memory by the citizen TALKING)
    #                off  = facts are written directly (old tell_fact shortcut)
    #   verify_mode  llm  = Verification is an LLM agent that reads memory and decides
    #                rules= deterministic regex rule (reproducible fallback)
    extract_mode: str = _f("SAHAYAK_EXTRACT", "llm")
    verify_mode: str = _f("SAHAYAK_VERIFY", "llm")
    # Verified Erasure: also ask the model which exact strings a forget-request refers to
    # (regex resolution always runs; this adds recall for names/places in free text).
    erase_llm: bool = _f("SAHAYAK_ERASE_LLM", "true").lower() == "true"


SETTINGS = Settings()
