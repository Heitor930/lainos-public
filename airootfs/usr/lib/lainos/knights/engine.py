"""‡ Knights OSINT — os mecanismos de busca, todos sobre dados públicos.

Cada função trabalha com fontes abertas (perfis públicos, DNS, WHOIS,
metadados de um arquivo que a pessoa escolhe). Nada aqui invade, força ou
contorna autenticação: é reconhecimento de informação já pública, o terreno
legítimo do OSINT. Use com responsabilidade e dentro da lei.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
HERE = Path(__file__).resolve().parent


# ----------------------------------------------------------------------
# Busca de nome de usuário em sites públicos
# ----------------------------------------------------------------------
@dataclass
class Site:
    name: str
    url: str
    detect: str = "status"
    absence: str = ""


@dataclass
class UserHit:
    site: str
    url: str
    state: str  # "found" | "missing" | "error"
    detail: str = ""


def load_sites() -> list[Site]:
    # permite ao usuário sobrepor com ~/.config/lainos/knights-sites.json
    paths = [
        Path(os.path.expanduser("~/.config/lainos/knights-sites.json")),
        HERE / "sites.json",
    ]
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sites = []
        for entry in data.get("sites", []):
            try:
                sites.append(Site(entry["name"], entry["url"],
                                  entry.get("detect", "status"), entry.get("absence", "")))
            except KeyError:
                continue
        if sites:
            return sites
    return []


USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def valid_username(name: str) -> bool:
    return bool(USERNAME_RE.fullmatch(name))


def check_username(site: Site, username: str, timeout: float = 12.0) -> UserHit:
    import requests  # import tardio: só quando a busca roda

    url = site.url.replace("{u}", username)
    try:
        resp = requests.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en;q=0.8"},
        )
    except requests.RequestException as exc:
        return UserHit(site.name, url, "error", type(exc).__name__)

    if site.detect == "absence":
        if resp.status_code >= 400:
            return UserHit(site.name, url, "missing", f"HTTP {resp.status_code}")
        found = site.absence.lower() not in resp.text.lower()
        return UserHit(site.name, url, "found" if found else "missing", f"HTTP {resp.status_code}")
    # detecção por status
    if resp.status_code == 200:
        return UserHit(site.name, url, "found", "HTTP 200")
    if resp.status_code in (404, 410):
        return UserHit(site.name, url, "missing", f"HTTP {resp.status_code}")
    return UserHit(site.name, url, "error", f"HTTP {resp.status_code}")


# ----------------------------------------------------------------------
# Inteligência de domínio: DNS + WHOIS
# ----------------------------------------------------------------------
@dataclass
class DomainReport:
    domain: str
    records: dict[str, list[str]] = field(default_factory=dict)
    whois: dict[str, str] = field(default_factory=dict)
    error: str = ""


DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+$")


def valid_domain(name: str) -> bool:
    return bool(DOMAIN_RE.fullmatch(name.strip().rstrip(".")))


def dns_records(domain: str) -> dict[str, list[str]]:
    try:
        import dns.resolver
    except ImportError:
        return {}
    out: dict[str, list[str]] = {}
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 8.0
    for rtype in ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"):
        try:
            answers = resolver.resolve(domain, rtype)
            out[rtype] = sorted(str(r.to_text()).strip('"') for r in answers)
        except Exception:
            continue
    return out


def whois_lookup(domain: str) -> dict[str, str]:
    exe = shutil.which("whois")
    if not exe:
        return {}
    try:
        raw = subprocess.run(
            [exe, domain], capture_output=True, text=True, timeout=20, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    wanted = {
        "registrar": r"Registrar:\s*(.+)",
        "criado em": r"Cre(?:ation Date|ated):\s*(.+)",
        "expira em": r"(?:Registry Expiry Date|Expiration Date|paid-till):\s*(.+)",
        "atualizado": r"Updated Date:\s*(.+)",
        "país": r"Registrant Country:\s*(.+)",
        "org": r"Registrant Organization:\s*(.+)",
    }
    found: dict[str, str] = {}
    for key, pattern in wanted.items():
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            found[key] = m.group(1).strip()
    servers = re.findall(r"Name Server:\s*(.+)", raw, re.IGNORECASE)
    if servers:
        found["servidores"] = ", ".join(sorted({s.strip().lower() for s in servers}))
    return found


def domain_report(domain: str) -> DomainReport:
    domain = domain.strip().rstrip(".").lower()
    if not valid_domain(domain):
        return DomainReport(domain, error="Domínio inválido.")
    return DomainReport(domain, records=dns_records(domain), whois=whois_lookup(domain))


# ----------------------------------------------------------------------
# IP: DNS reverso + geolocalização aproximada (serviço público)
# ----------------------------------------------------------------------
@dataclass
class IPReport:
    ip: str
    reverse: str = ""
    geo: dict[str, str] = field(default_factory=dict)
    error: str = ""


def valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def ip_report(value: str) -> IPReport:
    value = value.strip()
    if not valid_ip(value):
        return IPReport(value, error="Endereço IP inválido.")
    report = IPReport(value)
    try:
        report.reverse = socket.gethostbyaddr(value)[0]
    except (OSError, socket.herror):
        report.reverse = "(sem registro reverso)"
    try:
        import requests

        resp = requests.get(
            f"https://ipapi.co/{value}/json/",
            timeout=12, headers={"User-Agent": USER_AGENT},
        )
        if resp.ok:
            data = resp.json()
            for key, label in [
                ("org", "organização"), ("asn", "ASN"), ("city", "cidade"),
                ("region", "região"), ("country_name", "país"), ("timezone", "fuso"),
            ]:
                if data.get(key):
                    report.geo[label] = str(data[key])
    except Exception as exc:  # noqa: BLE001
        report.error = f"geolocalização indisponível ({type(exc).__name__})"
    return report


# ----------------------------------------------------------------------
# Metadados de um arquivo local (exiftool)
# ----------------------------------------------------------------------
INTERESTING_TAGS = [
    "File Name", "File Size", "File Type", "MIME Type",
    "Image Size", "Megapixels",
    "Create Date", "Date/Time Original", "Modify Date",
    "Make", "Camera Model Name", "Lens Model", "Software",
    "GPS Latitude", "GPS Longitude", "GPS Position",
    "Author", "Creator", "Producer", "Title", "Artist", "Copyright",
    "Document Name", "Application", "Company", "Last Modified By",
]


def file_metadata(path: str) -> dict[str, str]:
    exe = shutil.which("exiftool")
    if not exe:
        return {"_erro": "O exiftool não está instalado (pacote perl-image-exiftool)."}
    if not os.path.isfile(path):
        return {"_erro": "Arquivo não encontrado."}
    try:
        raw = subprocess.run(
            [exe, "-json", "-G1", "-n", path],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
        data = json.loads(raw)[0]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"_erro": "Não consegui ler os metadados deste arquivo."}

    out: dict[str, str] = {}
    # normaliza chaves "Grupo:Tag" -> "Tag"
    flat = {k.split(":")[-1]: v for k, v in data.items()}
    for tag in INTERESTING_TAGS:
        if tag in flat and str(flat[tag]).strip():
            out[tag] = str(flat[tag])
    if "GPS Latitude" in flat and "GPS Longitude" in flat:
        out["_mapa"] = f"https://www.openstreetmap.org/?mlat={flat['GPS Latitude']}&mlon={flat['GPS Longitude']}#map=15/{flat['GPS Latitude']}/{flat['GPS Longitude']}"
    if not out:
        out["_vazio"] = "Nenhum metadado relevante. O arquivo pode já ter sido limpo."
    return out
