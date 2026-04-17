from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import TypedDict
from uuid import UUID


VALID_SEVERITIES: frozenset[str] = frozenset(
    {"critical", "high", "medium", "low", "info"}
)

VALID_VULN_STATUSES: frozenset[str] = frozenset(
    {"open", "acknowledged", "resolved", "accepted_risk", "false_positive"}
)

VALID_SCAN_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)


@dataclass(frozen=True, slots=True)
class EnrichedFinding:
    """Hallazgo enriquecido por el LLM. Producido por el agente, consumido por el service."""

    asset_id: UUID
    scan_id: UUID
    vuln_type: str
    severity: str
    title: str
    description: str
    evidence: str
    remediation: str
    port: int | None
    protocol: str | None
    service: str | None
    cve: str | None
    cwe: str | None
    path: str | None
    cvss_score: float | None
    ai_enriched: bool = True
    needs_ai_retry: bool = False

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"Severidad inválida: {self.severity!r}")
        if not self.title or not self.title.strip():
            raise ValueError("title no puede estar vacío")
        if not self.vuln_type or not self.vuln_type.strip():
            raise ValueError("vuln_type no puede estar vacío")
        if self.cvss_score is not None and not (0.0 <= self.cvss_score <= 10.0):
            raise ValueError(f"cvss_score fuera de rango: {self.cvss_score}")
        if self.port is not None and not (0 < self.port <= 65535):
            raise ValueError(f"Puerto inválido: {self.port}")

    def fingerprint(self) -> str:
        """SHA-256(asset_id|vuln_type|port|cve|cwe|path) — algoritmo ADR-009."""
        def norm(val: object) -> str:
            return str(val).strip() if val is not None else ""

        components = [
            norm(self.asset_id),
            norm(self.vuln_type).lower(),
            norm(self.port),
            norm(self.cve).upper(),
            norm(self.cwe).upper(),
            norm(self.path).lower().rstrip("/"),
        ]
        return hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()

    def to_fallback(self) -> EnrichedFinding:
        """Copia marcada como fallback cuando el LLM falla — se reintentará después."""
        return replace(self, ai_enriched=False, needs_ai_retry=True)


class ScanState(TypedDict, total=False):
    """
    Estado del grafo LangGraph. total=False: cada nodo devuelve solo lo que modifica.
    Cualquier nodo puede escribir `error`. run_agent_safely() lo lee al finalizar.
    scan_id y tenant_id son strings porque LangGraph serializa el estado a JSON.
    """

    scan_id: str
    tenant_id: str
    asset: dict
    nmap_raw_xml: str
    raw_findings: list[dict]
    enriched_findings: list[EnrichedFinding]
    llm_failed: bool
    error: str | None
    completed: bool


@dataclass(frozen=True, slots=True)
class UpsertVulnerabilitiesResult:
    """Resultado de vulnerabilities/service.py::upsert_findings()."""

    created: int
    updated: int
    skipped: int  # findings con error de validación — se loguean como warning

    @property
    def total(self) -> int:
        return self.created + self.updated

    @property
    def has_new_findings(self) -> bool:
        return self.created > 0