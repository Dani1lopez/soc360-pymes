"""Parse untrusted Nmap XML without recovering incomplete reports."""

from dataclasses import dataclass
from typing import Any

from defusedxml.common import (  # type: ignore[import-untyped]
    DefusedXmlException,
    DTDForbidden,
)
from defusedxml.ElementTree import DefusedXMLParser  # type: ignore[import-untyped]

from app.modules.scans.nmap.command import REQUIRED_SCAN_TYPES


class NmapParseError(Exception):
    """A bounded failure code suitable for scans.failure_reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _NmapXMLParser(DefusedXMLParser):  # type: ignore[misc]
    """Allow only the bare ``<!DOCTYPE nmaprun>`` that real Nmap output carries.

    Any other doctype, external DTD (SYSTEM/PUBLIC) or internal subset is
    rejected; entity declarations and external references stay forbidden.
    """

    def __init__(self) -> None:
        super().__init__(forbid_dtd=True, forbid_entities=True, forbid_external=True)

    def defused_start_doctype_decl(
        self,
        name: str,
        sysid: str | None,
        pubid: str | None,
        has_internal_subset: bool,
    ) -> None:
        if name != "nmaprun" or sysid or pubid or has_internal_subset:
            raise DTDForbidden(name, sysid, pubid)


@dataclass(frozen=True, slots=True)
class ScriptFinding:
    script_id: str | None
    output: str | None


@dataclass(frozen=True, slots=True)
class NmapService:
    name: str | None
    product: str | None
    version: str | None
    extrainfo: str | None


@dataclass(frozen=True, slots=True)
class NmapPort:
    protocol: str | None
    port_id: int
    state: str | None
    service: NmapService | None
    scripts: tuple[ScriptFinding, ...]


@dataclass(frozen=True, slots=True)
class NmapHost:
    addresses: tuple[str, ...]
    hostnames: tuple[str, ...]
    status: str | None
    os_matches: tuple[str, ...]
    ports: tuple[NmapPort, ...]
    host_scripts: tuple[ScriptFinding, ...]


@dataclass(frozen=True, slots=True)
class NmapReport:
    scan_types: frozenset[str]
    hosts: tuple[NmapHost, ...]


def _scripts(element: Any, path: str) -> tuple[ScriptFinding, ...]:
    return tuple(
        ScriptFinding(script.get("id"), script.get("output"))
        for script in element.findall(path)
    )


def _attributes(element: Any, path: str, attribute: str) -> tuple[str, ...]:
    return tuple(
        value
        for child in element.findall(path)
        if (value := child.get(attribute)) is not None
    )


def _port(element: Any) -> NmapPort:
    try:
        port_id = int(element.get("portid", ""))
    except ValueError as exc:
        raise NmapParseError("invalid_port") from exc
    if not 0 <= port_id <= 65535:
        raise NmapParseError("invalid_port")
    service = element.find("service")
    state = element.find("state")
    return NmapPort(
        protocol=element.get("protocol"),
        port_id=port_id,
        state=state.get("state") if state is not None else None,
        service=(
            NmapService(
                service.get("name"),
                service.get("product"),
                service.get("version"),
                service.get("extrainfo"),
            )
            if service is not None
            else None
        ),
        scripts=_scripts(element, "script"),
    )


def _host(element: Any) -> NmapHost:
    status = element.find("status")
    return NmapHost(
        addresses=_attributes(element, "address", "addr"),
        hostnames=_attributes(element, "hostnames/hostname", "name"),
        status=status.get("state") if status is not None else None,
        os_matches=_attributes(element, "os/osmatch", "name"),
        ports=tuple(_port(port) for port in element.findall("ports/port")),
        host_scripts=_scripts(element, "hostscript/script"),
    )


def parse_nmap_xml(data: bytes | str) -> NmapReport:
    """Reject hostile DTDs/entities and malformed XML before extracting data."""
    parser = _NmapXMLParser()
    try:
        parser.feed(data)
        root = parser.close()
    except DefusedXmlException as exc:
        raise NmapParseError("forbidden_xml_construct") from exc
    except Exception as exc:
        raise NmapParseError("malformed_xml") from exc
    if root.tag != "nmaprun":
        raise NmapParseError("unexpected_root")
    scan_types = frozenset(_attributes(root, "scaninfo", "type"))
    if not scan_types:
        raise NmapParseError("missing_scaninfo")
    return NmapReport(scan_types, tuple(_host(host) for host in root.findall("host")))


def verify_scan_types(
    report: NmapReport, required: frozenset[str] = REQUIRED_SCAN_TYPES
) -> None:
    """Ensure the executed scan did not silently fall back to another profile."""
    if not required.issubset(report.scan_types):
        raise NmapParseError("scan_type_mismatch")
