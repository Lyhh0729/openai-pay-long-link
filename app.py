from __future__ import annotations

import json
import os
import queue
import random
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit, unquote

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

try:
    from curl_cffi.requests import Session as CurlCffiSession  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    CurlCffiSession = None  # type: ignore


DEFAULT_STRIPE_PK = (
    "pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRac"
    "ViovU3kLKvpkjh7IqkW00iXQsjo3n"
)
STRIPE_VERSION_FULL = "2025-03-31.basil; checkout_server_update_beta=v1; checkout_manual_approval_preview=v1"
DEFAULT_TIMEOUT = 30
CHATGPT_TIMEOUT = 45
CHATGPT_RETRY_ATTEMPTS = 5
PROVIDER_RETRY_ATTEMPTS = 3
CTF_MOCK_MODE = os.getenv("OPENAI_PAY_CTF_MOCK_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
LOG_DIR = BASE_DIR / "logs"
RUN_JOBS: dict[str, dict[str, Any]] = {}
RUN_JOBS_LOCK = threading.Lock()
RUN_JOB_TTL_SECONDS = 3600
RUN_JOB_MAX_ITEMS = 80
DEFAULT_PROXY = os.getenv(
    "OPENAI_PAY_DEFAULT_PROXY",
    "socks5://nsxym:Nsxym@2026@10.0.0.9:10802",
).strip()
PROVIDER_STAGE_PROXY = os.getenv(
    "OPENAI_PAY_PROVIDER_PROXY",
    "socks5://nsxym:Nsxym@2026@10.0.0.9:10801",
).strip()
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
DEFAULT_STRIPE_RUNTIME_VERSION = "6f8494a281"
US_BILLING_NAMES = [
    ("James", "Smith"),
    ("John", "Brown"),
    ("Michael", "Johnson"),
    ("Robert", "Miller"),
    ("David", "Davis"),
    ("William", "Wilson"),
]
US_BILLING_STREETS = [
    ("3110 Sunset Boulevard", "Los Angeles", "CA", "90026"),
    ("1200 Market Street", "San Francisco", "CA", "94102"),
    ("500 Main Street", "Austin", "TX", "78701"),
    ("88 Broadway", "New York", "NY", "10007"),
    ("1200 Peachtree St", "Atlanta", "GA", "30309"),
]
DE_BILLING_NAMES = [
    ("Lukas", "Schneider"),
    ("Felix", "Muller"),
    ("Jonas", "Weber"),
    ("Leon", "Fischer"),
    ("Marie", "Wagner"),
    ("Laura", "Becker"),
    ("Maximilian", "Hoffmann"),
    ("Paul", "Schulz"),
    ("Emma", "Koch"),
    ("Hannah", "Bauer"),
    ("Sophie", "Richter"),
    ("Noah", "Klein"),
]
DE_BILLING_STREETS = [
    ("Friedrichstrasse 123", "Berlin", "BE", "10117"),
    ("Leopoldstrasse 50", "Munich", "BY", "80802"),
    ("Zeil 85", "Frankfurt am Main", "HE", "60313"),
    ("Konigsallee 60", "Dusseldorf", "NW", "40212"),
    ("Moenckebergstrasse 7", "Hamburg", "HH", "20095"),
    ("Hohenzollernring 72", "Cologne", "NW", "50672"),
    ("Kaiserstrasse 44", "Stuttgart", "BW", "70173"),
    ("Kaufingerstrasse 15", "Munich", "BY", "80331"),
    ("Georgstrasse 24", "Hanover", "NI", "30159"),
    ("Prager Strasse 9", "Dresden", "SN", "01069"),
    ("Schadowstrasse 36", "Dusseldorf", "NW", "40212"),
    ("Breite Strasse 18", "Bonn", "NW", "53111"),
]
AU_BILLING_NAMES = [
    ("Oliver", "Smith"),
    ("William", "Jones"),
    ("Jack", "Williams"),
    ("Noah", "Brown"),
    ("Thomas", "Wilson"),
    ("James", "Taylor"),
    ("Lucas", "Johnson"),
    ("Charlotte", "White"),
    ("Olivia", "Martin"),
    ("Ava", "Anderson"),
    ("Amelia", "Thompson"),
    ("Isla", "Clark"),
]
AU_BILLING_STREETS = [
    ("1 Collins Street", "Melbourne", "VIC", "3000"),
    ("100 George Street", "Sydney", "NSW", "2000"),
    ("150 Queen Street", "Brisbane", "QLD", "4000"),
    ("50 King William Street", "Adelaide", "SA", "5000"),
    ("200 St Georges Terrace", "Perth", "WA", "6000"),
    ("120 London Circuit", "Canberra", "ACT", "2601"),
    ("300 Elizabeth Street", "Hobart", "TAS", "7001"),
]
COUNTRY_CURRENCY = {
    "US": "USD",
    "DE": "EUR",
    "AU": "AUD",
}
LOCALE_MAP = {
    "de": ("de-DE", "de"),
    "en": ("en-US", "en"),
    "en-AU": ("en-AU", "en-AU"),
    "en-US": ("en-US", "en"),
    "es": ("es-ES", "es"),
    "fr": ("fr-FR", "fr"),
    "id": ("id-ID", "id"),
    "it": ("it-IT", "it"),
    "ja": ("ja-JP", "ja"),
    "ko": ("ko-KR", "ko"),
    "pt-BR": ("pt-BR", "pt-BR"),
    "zh-CN": ("zh-CN", "zh-CN"),
    "zh-TW": ("zh-TW", "zh-TW"),
}


class LongLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(..., alias="accessToken")
    proxy: str = ""
    jp_proxy: str = ""
    us_proxy: str = ""
    au_proxy: str = ""
    billing_countries: list[str] = []
    payment_method_countries: list[str] = []
    provider_proxy_countries: list[str] = []
    stripe_publishable_key: str = ""
    billing_country: str = "US"
    payment_method_country: str = "US"
    provider_proxy_country: str = ""
    checkout_ui_mode: str = "custom"
    payment_locale: str = "en"
    diagnostic_mode: bool = False
    max_combos: int = 0
    device_id: str = ""
    user_agent: str = ""


class LongLinkResponse(BaseModel):
    ok: bool
    cs_id: str
    processor_entity: str
    billing_country: str
    payment_method_country: str
    currency: str
    payment_locale: str
    flow_type: str
    payment_method_type: str
    payment_method_id: str
    stripe_redirect_url: str
    provider_redirect_url: str
    fallback: bool = False
    provider_error: str = ""
    stripe_hosted_url: str
    long_url: str


class ProxyCheckRequest(BaseModel):
    jp_proxy: str = ""
    us_proxy: str = ""
    au_proxy: str = ""
    billing_country: str = "US"


class ProxyProbeResult(BaseModel):
    ok: bool
    label: str
    proxy: str
    ip: str = ""
    country: str = ""
    country_code: str = ""
    error: str = ""


class ProxyCheckResponse(BaseModel):
    ok: bool
    results: list[ProxyProbeResult]


def encode_socks_password(proxy: str) -> str:
    proxy = str(proxy or "").strip()
    if not proxy or not proxy.lower().startswith("socks"):
        return proxy
    parsed = urlsplit(proxy)
    if parsed.username and parsed.password:
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        netloc = f"{quote(parsed.username, safe='-._~')}:{quote(parsed.password, safe='-._~')}@{host}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return proxy


def new_session(proxy: str = "") -> Any:
    use_curl = CurlCffiSession is not None
    if use_curl:
        session = CurlCffiSession(impersonate="chrome136")
    else:
        session = requests.Session()
    if hasattr(session, "trust_env"):
        session.trust_env = False
    return session


def effective_default_proxy(proxy: str = "") -> str:
    return str(proxy or "").strip() or DEFAULT_PROXY


def checkout_stage_proxy(req: LongLinkRequest) -> str:
    return normalize_proxy_url(str(req.jp_proxy or req.proxy or "").strip() or DEFAULT_PROXY)


def normalize_proxy_url(proxy: str) -> str:
    proxy = str(proxy or "").strip()
    if proxy and "://" not in proxy:
        return f"http://{proxy}"
    return proxy


def set_proxy_url(session: Any, proxy: str) -> None:
    proxy = normalize_proxy_url(proxy)
    if proxy:
        if CurlCffiSession is not None and isinstance(session, CurlCffiSession) and proxy.lower().startswith("socks"):
            proxy = encode_socks_password(proxy)
        session.proxies = {"http": proxy, "https": proxy}


def set_proxy(session: Any, proxy: str) -> None:
    set_proxy_url(session, effective_default_proxy(proxy))


def proxy_for_region(proxy: str, region: str) -> str:
    proxy = str(proxy or "").strip()
    region = str(region or "").strip().upper()
    if proxy and region and "region-" in proxy:
        return re.sub(r"region-[A-Za-z]{2}", f"region-{region}", proxy)
    return proxy


def new_proxy_session_id() -> str:
    return str(random.randint(10_000_000, 99_999_999))


def rotate_kookeey_proxy_session(proxy: str, country: str) -> str:
    proxy = normalize_proxy_url(proxy)
    country = str(country or "").strip().upper()
    if not proxy or not country:
        return proxy

    parsed = urlsplit(proxy)
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not username or not password:
        return proxy

    match = re.match(r"^(?P<base>.+?)-(?P<country>[A-Za-z]{2})(?:-[A-Za-z0-9]+)?$", password)
    if match:
        password_base = match.group("base")
    else:
        return proxy
    rotated_password = f"{password_base}-{country}-{new_proxy_session_id()}"

    hostname = parsed.hostname or ""
    if not hostname:
        return proxy
    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"{quote(username, safe='-._~')}:{quote(rotated_password, safe='-._~')}@{host}"
    return urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment))


def request_with_rotated_proxy_sessions(req: LongLinkRequest) -> LongLinkRequest:
    return req.model_copy(
        update={
            "jp_proxy": rotate_kookeey_proxy_session(checkout_stage_proxy(req), "JP"),
            "us_proxy": rotate_kookeey_proxy_session(provider_stage_proxy(req), "US"),
        }
    )


def request_with_rotated_jp_session(req: LongLinkRequest) -> LongLinkRequest:
    return req.model_copy(update={"jp_proxy": rotate_kookeey_proxy_session(checkout_stage_proxy(req), "JP")})


def is_retryable_network_error(exc: Exception) -> bool:
    retryable_names = {
        "ReadTimeout",
        "ConnectTimeout",
        "ConnectionError",
        "Timeout",
        "SSLError",
        "ProxyError",
        "RemoteDisconnected",
        "ConnectionResetError",
    }
    for item in type(exc).mro():
        if item.__name__ in retryable_names:
            return True
    text = str(exc).lower()
    retryable_markers = (
        "read timed out",
        "connect timed out",
        "connection aborted",
        "connection reset",
        "remote end closed connection",
        "remote disconnected",
        "unexpected_eof_while_reading",
        "eof occurred in violation of protocol",
        "ssleoferror",
        "max retries exceeded",
        "proxyerror",
        "unable to connect to proxy",
    )
    return any(marker in text for marker in retryable_markers)


def is_retryable_provider_http_exception(exc: HTTPException) -> bool:
    if exc.status_code not in (502, 504):
        return False
    detail = str(exc.detail or "")
    return is_retryable_network_error(Exception(detail))


def provider_stage_proxy(req: LongLinkRequest) -> str:
    """Provider-stage proxy: US for Stripe/PayPal, separate from JP for ChatGPT."""
    us = str(req.us_proxy or "").strip()
    au = str(req.au_proxy or "").strip()
    if au:
        return normalize_proxy_url(au)
    if us:
        return normalize_proxy_url(us)
    return normalize_proxy_url(PROVIDER_STAGE_PROXY)


def provider_proxy_for_country(req: LongLinkRequest, country: str) -> str:
    country = normalize_country(country)
    if country == "AU":
        explicit = str(req.au_proxy or "").strip()
        if explicit:
            return normalize_proxy_url(explicit)
    if country == "JP":
        return checkout_stage_proxy(req)
    explicit = str(req.us_proxy or "").strip()
    if explicit:
        return normalize_proxy_url(explicit)
    return normalize_proxy_url(PROVIDER_STAGE_PROXY)


def apply_provider_proxy(chatgpt: Any, proxy: str) -> None:
    set_proxy_url(chatgpt, proxy)


def fetch_proxy_geo(session: Any) -> tuple[str, str, str]:
    errors: list[str] = []
    probes = [
        (
            "ip-api",
            "http://ip-api.com/json/?fields=status,message,country,countryCode,query",
            lambda payload: (
                str(payload.get("query") or ""),
                str(payload.get("countryCode") or "").upper(),
                str(payload.get("country") or ""),
                str(payload.get("message") or ""),
                str(payload.get("status") or "") == "success",
            ),
        ),
        (
            "ipwho.is",
            "https://ipwho.is/",
            lambda payload: (
                str(payload.get("ip") or ""),
                str(payload.get("country_code") or "").upper(),
                str(payload.get("country") or ""),
                str(payload.get("message") or ""),
                bool(payload.get("success", True)),
            ),
        ),
        (
            "ipapi.co",
            "https://ipapi.co/json/",
            lambda payload: (
                str(payload.get("ip") or ""),
                str(payload.get("country_code") or "").upper(),
                str(payload.get("country_name") or ""),
                str(payload.get("reason") or payload.get("error") or ""),
                not bool(payload.get("error")),
            ),
        ),
    ]
    for name, url, parser in probes:
        try:
            response = session.get(url, timeout=12)
            response.raise_for_status()
            ip, country_code, country, message, ok = parser(response.json() or {})
            if ok and ip and country_code:
                return ip, country_code, country
            errors.append(f"{name}: {message or response.text[:120]}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("；".join(errors))


def probe_proxy(label: str, proxy: str, expected_country: str = "", required: bool = False) -> ProxyProbeResult:
    proxy = normalize_proxy_url(proxy)
    expected_country = str(expected_country or "").strip().upper()
    if CTF_MOCK_MODE:
        effective_proxy = proxy or f"mock://{(expected_country or 'US').lower()}-pool"
        country_code = expected_country or "US"
        ip = mock_ip_for_country(country_code, f"{label}:{effective_proxy}")
        return ProxyProbeResult(
            ok=True,
            label=label,
            proxy=effective_proxy,
            ip=ip,
            country=country_code,
            country_code=country_code,
        )
    if not proxy:
        if required:
            return ProxyProbeResult(ok=False, label=label, proxy="", error=f"{label} 代理不能为空")
        return ProxyProbeResult(ok=True, label=label, proxy="", error=f"{label} 未填写，使用直连")

    parsed = urlsplit(proxy)
    username = unquote(parsed.username or "")
    if username.startswith("-"):
        return ProxyProbeResult(
            ok=False,
            label=label,
            proxy=proxy,
            error=f"{label} 代理用户名不应以 '-' 开头，请使用 Kookeey 页面生成的原始格式",
        )

    session = requests.Session()
    session.trust_env = False
    set_proxy_url(session, proxy)
    try:
        ip, country_code, country = fetch_proxy_geo(session)
    except Exception as exc:
        return ProxyProbeResult(ok=False, label=label, proxy=proxy, error=f"{label} 检测失败: {exc}")
    result = ProxyProbeResult(
        ok=True,
        label=label,
        proxy=proxy,
        ip=ip,
        country=country,
        country_code=country_code,
    )
    if expected_country and country_code != expected_country:
        result.ok = False
        result.error = f"{label} 出口不是 {expected_country}: {country_code or '未知'} {result.ip}".strip()
    return result


def check_request_proxies(req: LongLinkRequest) -> list[ProxyProbeResult]:
    jp_proxy = checkout_stage_proxy(req)
    results = [
        probe_proxy("checkout/approve JP", jp_proxy, "JP", required=True),
    ]
    for label, proxy_val, expected in _provider_proxy_options(req):
        results.append(probe_proxy(label, proxy_val, expected, required=False))
    mark_same_exit(results)
    return results


def _provider_proxy_options(req: LongLinkRequest) -> list[tuple[str, str, str]]:
    """Return list of (label, proxy_url, expected_country) for all available provider proxies."""
    explicit_countries = normalize_country_list(req.provider_proxy_countries)
    if explicit_countries:
        opts: list[tuple[str, str, str]] = []
        for country in explicit_countries:
            proxy_val = provider_proxy_for_country(req, country)
            opts.append((f"provider {country}", proxy_val, country))
        return opts
    # Default: use all available provider proxies
    opts: list[tuple[str, str, str]] = []
    us = str(req.us_proxy or "").strip()
    au = str(req.au_proxy or "").strip()
    if us:
        opts.append(("provider US", normalize_proxy_url(us), "US"))
    if au:
        opts.append(("provider AU", normalize_proxy_url(au), "AU"))
    if not opts:
        # Fallback: use US proxy from env, or default
        opts.append(("provider US", provider_stage_proxy(req), "US"))
    return opts


def check_provider_proxy_for(req: LongLinkRequest, country: str) -> ProxyProbeResult:
    """Check a specific provider proxy by country ('US', 'AU', or 'JP')."""
    country = (country or "").upper()
    if country == "AU":
        au = str(req.au_proxy or "").strip()
        if au:
            return probe_proxy("provider AU", normalize_proxy_url(au), "AU", required=False)
    if country == "US":
        us = str(req.us_proxy or "").strip()
        if us:
            return probe_proxy("provider US", normalize_proxy_url(us), "US", required=False)
    # Single-proxy or JP-provider fallback — check the actual proxy
    fallback = provider_stage_proxy(req)
    expected = country if country in ("US", "AU") else "JP"
    return probe_proxy(f"provider {country}", fallback, expected, required=False)


def check_provider_proxy(req: LongLinkRequest) -> ProxyProbeResult:
    return check_provider_proxy_for(req, "US")


def mock_ip_for_country(country: str, salt: str = "") -> str:
    base = sum(ord(ch) for ch in f"{country}:{salt}") % 200
    return f"10.{(base % 200) + 1}.{((base * 7) % 200) + 1}.{((base * 13) % 200) + 1}"


def mock_combo_profile(req: LongLinkRequest) -> dict[str, str]:
    checkout_country = effective_country(req)
    pm_country = effective_payment_method_country(req)
    provider_country = normalize_country(getattr(req, "provider_proxy_country", "") or "US")
    mode = "approve" if pm_country == "AU" else "redirect"
    if checkout_country == "DE" and pm_country == "DE":
        mode = "failed"
    return {
        "checkout_country": checkout_country,
        "pm_country": pm_country,
        "provider_country": provider_country,
        "mode": mode,
        "ba_token": f"BA-MOCK-{checkout_country}{pm_country}{provider_country}-{uuid.uuid4().hex[:10].upper()}",
    }


def mark_same_exit(results: list[ProxyProbeResult]) -> None:
    if len(results) < 2:
        return
    first = results[0]
    first_ip = str(first.ip or "").strip()
    if not first_ip:
        return
    for item in results[1:]:
        if str(item.ip or "").strip() == first_ip and item.label != first.label:
            item.ok = False
            suffix = f"；并且与 {first.label} 使用同一出口 {first_ip}"
            item.error = (item.error or f"{item.label} 出口异常").rstrip("。") + suffix


def ensure_request_proxies_ok(req: LongLinkRequest) -> list[ProxyProbeResult]:
    results = check_request_proxies(req)
    failed = [item for item in results if not item.ok]
    if failed:
        detail = "; ".join(item.error or f"{item.label} 代理不可用" for item in failed)
        raise HTTPException(status_code=400, detail=f"代理检测未通过: {detail}")
    return results


def format_proxy_probe_summary(results: list[ProxyProbeResult]) -> str:
    parts: list[str] = []
    for item in results:
        if not item.proxy:
            parts.append(f"{item.label}: 直连")
            continue
        if item.ok:
            summary = f"{item.label}: {item.ip or '未知 IP'} / {item.country_code or '未知'} {item.country or ''}".strip()
        else:
            summary = f"{item.label}: {item.error or '检测失败'}"
        parts.append(summary)
    return "；".join(parts)


def currency_for_country(country: str) -> str:
    return COUNTRY_CURRENCY.get(str(country or "").upper(), "USD")


def normalize_country(country: str) -> str:
    country = str(country or "").strip().upper()
    return country if country in COUNTRY_CURRENCY else "US"


def effective_country(req: LongLinkRequest) -> str:
    return normalize_country(req.billing_country)


def effective_payment_method_country(req: LongLinkRequest) -> str:
    return normalize_country(req.payment_method_country or "US")


def normalize_country_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        country = normalize_country(item)
        if country in seen:
            continue
        seen.add(country)
        result.append(country)
    return result


def configured_billing_combos(req: LongLinkRequest) -> list[tuple[str, str]]:
    billing_candidates = normalize_country_list(req.billing_countries)
    pm_candidates = normalize_country_list(req.payment_method_countries)
    if not billing_candidates and not pm_candidates:
        # Default: US+DE billing × DE+AU payment = 4 combos
        billing_candidates = ["US", "DE"]
        pm_candidates = ["DE", "AU"]
    elif not billing_candidates:
        billing_candidates = [effective_country(req)]
    elif not pm_candidates:
        pm_candidates = [effective_payment_method_country(req)]
    combos: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for checkout_country in billing_candidates:
        for pm_country in pm_candidates:
            item = (checkout_country, pm_country)
            if item in seen:
                continue
            seen.add(item)
            combos.append(item)
    return combos


def locale_parts(locale: str) -> tuple[str, str]:
    return LOCALE_MAP.get(str(locale or "").strip(), LOCALE_MAP["en"])


def find_token(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("accessToken", "access_token", "token"):
            token = str(value.get(key) or "").strip()
            if token:
                return token
        for item in value.values():
            token = find_token(item)
            if token:
                return token
    if isinstance(value, list):
        for item in value:
            token = find_token(item)
            if token:
                return token
    return ""


def normalize_access_token(raw: str) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    if token.startswith("{") or token.startswith("["):
        try:
            return find_token(json.loads(token)) or token
        except json.JSONDecodeError:
            return token
    return token


def extract_processor_entity(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("processor_entity") or data.get("processorEntity")
    if direct:
        return str(direct).strip()
    for key in ("checkout_session", "session", "checkout", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_processor_entity(nested)
            if found:
                return found
    return ""


def extract_stripe_publishable_key(data: Any) -> str:
    if isinstance(data, str):
        match = re.search(r"pk_live_[A-Za-z0-9]+", data)
        return match.group(0) if match else ""
    if isinstance(data, dict):
        for key in (
            "stripe_publishable_key",
            "publishable_key",
            "publishableKey",
            "stripePublishableKey",
            "key",
        ):
            found = extract_stripe_publishable_key(data.get(key))
            if found:
                return found
        for item in data.values():
            found = extract_stripe_publishable_key(item)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = extract_stripe_publishable_key(item)
            if found:
                return found
    return ""


def build_chatgpt_session(req: LongLinkRequest) -> Any:
    access_token = normalize_access_token(req.access_token)
    if not access_token:
        raise HTTPException(status_code=400, detail="accessToken is required")

    device_id = req.device_id.strip() or str(uuid.uuid4())
    user_agent = req.user_agent.strip() or DEFAULT_USER_AGENT
    proxy = checkout_stage_proxy(req)
    session = new_session(proxy)
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Authorization": f"Bearer {access_token}",
            "Origin": "https://chatgpt.com",
            "Referer": "https://chatgpt.com/",
            "Content-Type": "application/json",
            "oai-device-id": device_id,
            "oai-language": "en-US",
            "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "Cookie": f"oai-did={device_id}",
        }
    )
    set_proxy_url(session, proxy)
    return session


def create_checkout(req: LongLinkRequest, chatgpt_session: Any | None = None) -> dict[str, Any]:
    billing_country = effective_country(req)
    currency = currency_for_country(billing_country)
    checkout_ui_mode = (req.checkout_ui_mode or "custom").strip() or "custom"
    if CTF_MOCK_MODE:
        profile = mock_combo_profile(req)
        return {
            "cs_id": f"cs_mock_{uuid.uuid4().hex[:24]}",
            "processor_entity": processor_entity_for_country(billing_country),
            "stripe_publishable_key": req.stripe_publishable_key.strip() or "pk_mock_ctf",
            "billing_country": billing_country,
            "currency": currency,
            "checkout_url": "",
            "mock_mode": profile["mode"],
        }
    body = {
        "plan_name": "chatgptplusplan",
        "billing_details": {
            "country": billing_country,
            "currency": currency,
        },
        "promo_campaign": {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        },
        "checkout_ui_mode": checkout_ui_mode,
    }
    headers = {
        "Referer": "https://chatgpt.com/",
        "x-openai-target-path": "/backend-api/payments/checkout",
        "x-openai-target-route": "/backend-api/payments/checkout",
    }
    response = (chatgpt_session or build_chatgpt_session(req)).post(
        "https://chatgpt.com/backend-api/payments/checkout",
        json=body,
        headers=headers,
        timeout=CHATGPT_TIMEOUT,
    )
    if response.status_code >= 400:
        body_text = response.text[:500] if response.text else ""
        raise HTTPException(
            status_code=response.status_code,
            detail=f"checkout create failed: {body_text}",
        )

    data = response.json() or {}
    cs_id = data.get("checkout_session_id") or data.get("session_id") or data.get("id")
    if not cs_id or not str(cs_id).startswith("cs_"):
        raise HTTPException(status_code=502, detail=f"checkout response missing cs_id: {data}")
    # The checkout response may already contain the PayPal BA approve URL.
    checkout_url = str(data.get("url") or "").strip()
    return {
        "cs_id": str(cs_id),
        "processor_entity": extract_processor_entity(data),
        "stripe_publishable_key": extract_stripe_publishable_key(data),
        "billing_country": billing_country,
        "currency": currency,
        "checkout_url": checkout_url,
    }


def create_checkout_with_retry(req: LongLinkRequest, emit: Any | None = None) -> tuple[LongLinkRequest, Any, dict[str, Any]]:
    last_error = ""
    for attempt in range(1, CHATGPT_RETRY_ATTEMPTS + 1):
        attempt_req = request_with_rotated_jp_session(req)
        if emit:
            emit("checkout", f"checkout 第 {attempt}/{CHATGPT_RETRY_ATTEMPTS} 次：正在检测 JP 出口。")
        probe = probe_proxy("checkout JP", checkout_stage_proxy(attempt_req), "JP", required=True)
        if not probe.ok:
            last_error = probe.error or "JP 代理检测失败"
            if emit:
                emit("checkout", f"checkout 第 {attempt} 次 JP session 不可用：{last_error}")
            continue
        if emit:
            emit("checkout", f"checkout JP 出口：{probe.ip} / {probe.country_code} {probe.country}。")
        try:
            if emit:
                emit("checkout", f"checkout 第 {attempt}/{CHATGPT_RETRY_ATTEMPTS} 次：正在创建 ChatGPT checkout。")
            chatgpt = build_chatgpt_session(attempt_req)
            checkout = create_checkout(attempt_req, chatgpt)
            return attempt_req, chatgpt, checkout
        except HTTPException as exc:
            # 403 返回 HTML 通常是 Cloudflare 临时拦截，应重试
            if exc.status_code == 403 and "<html" in str(exc.detail or ""):
                last_error = str(exc.detail or exc)
                if emit:
                    emit("checkout", f"checkout 第 {attempt} 次被 Cloudflare 拦截，正在更换 JP session")
                continue
            raise
        except Exception as exc:
            if not is_retryable_network_error(exc):
                raise
            last_error = str(exc)
            if emit:
                emit("checkout", f"checkout 第 {attempt} 次网络超时/连接失败，正在更换 JP session：{last_error}")
    raise HTTPException(
        status_code=504,
        detail=f"ChatGPT checkout 连续超时，已自动更换 JP session {CHATGPT_RETRY_ATTEMPTS} 次仍失败: {last_error}",
    )


def stripe_key_for_request(req: LongLinkRequest, checkout: dict[str, Any] | None = None) -> str:
    return (
        req.stripe_publishable_key.strip()
        or str((checkout or {}).get("stripe_publishable_key") or "").strip()
        or DEFAULT_STRIPE_PK
    )


def _stripe_init_request(stripe: Any, cs_id: str, req: LongLinkRequest, stripe_pk: str) -> dict[str, Any]:
    browser_locale, elements_locale = locale_parts(req.payment_locale)
    if CTF_MOCK_MODE:
        profile = mock_combo_profile(req)
        currency = currency_for_country(profile["checkout_country"]).lower()
        return {
            "_stripe_js_id": str(uuid.uuid4()),
            "config_id": f"cfg_mock_{uuid.uuid4().hex[:10]}",
            "init_checksum": f"chk_{uuid.uuid4().hex[:12]}",
            "currency": currency,
            "stripe_hosted_url": f"https://pay.openai.com/c/pay/{cs_id}",
            "total_summary": {"due": 0},
            "mock_mode": profile["mode"],
            "browser_locale": browser_locale,
            "elements_locale": elements_locale,
            "key": stripe_pk,
        }
    stripe_js_id = str(uuid.uuid4())
    body = {
        "browser_locale": browser_locale,
        "browser_timezone": "Asia/Shanghai",
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[stripe_js_id]": stripe_js_id,
        "elements_session_client[locale]": elements_locale,
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    response = stripe.post(
        f"https://api.stripe.com/v1/payment_pages/{cs_id}/init",
        data=body,
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        try:
            error = (response.json() or {}).get("error") or {}
            if error.get("code") == "resource_missing":
                detail = (
                    f"{detail}；诊断：Stripe 找不到该 checkout.session，通常是 checkout_ui_mode "
                    f"不是 custom，或 Stripe publishable key 与 checkout session 所属账户不匹配。"
                )
        except Exception:
            pass
        raise HTTPException(
            status_code=response.status_code,
            detail=f"stripe init failed: {detail}",
        )
    payload = response.json() or {}
    payload["_stripe_js_id"] = stripe_js_id
    return payload


def stripe_init(cs_id: str, req: LongLinkRequest, proxy_override: str = "", checkout: dict[str, Any] | None = None) -> dict[str, Any]:
    stripe_pk = stripe_key_for_request(req, checkout)
    proxy = proxy_override or checkout_stage_proxy(req)
    stripe = new_session(proxy)
    stripe.headers.update(
        {
            "User-Agent": req.user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    set_proxy_url(stripe, proxy)
    return _stripe_init_request(stripe, cs_id, req, stripe_pk)


def to_openai_pay_url(stripe_hosted_url: str) -> str:
    url = str(stripe_hosted_url or "").strip()
    if not url:
        return ""
    if url.startswith("https://checkout.stripe.com"):
        return "https://pay.openai.com" + url[len("https://checkout.stripe.com") :]

    parsed = urlsplit(url)
    if parsed.netloc.lower() == "checkout.stripe.com":
        return urlunsplit((parsed.scheme or "https", "pay.openai.com", parsed.path, parsed.query, parsed.fragment))
    return url


def processor_entity_for_country(country: str, processor_entity: str = "") -> str:
    entity = str(processor_entity or "").strip()
    if entity:
        return entity
    return "openai_llc" if str(country or "").upper() == "US" else "openai_ie"


def deep_find_first_string(value: Any, predicate: Any) -> str:
    if isinstance(value, dict):
        for item in value.values():
            found = deep_find_first_string(item, predicate)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = deep_find_first_string(item, predicate)
            if found:
                return found
    elif isinstance(value, str):
        text = value.strip()
        try:
            if text and predicate(text):
                return text
        except Exception:
            return ""
    return ""


def deep_find_key_string(value: Any, wanted_keys: tuple[str, ...], predicate: Any | None = None) -> str:
    lowered = {item.lower() for item in wanted_keys}
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text in lowered and isinstance(item, str):
                text = item.strip()
                if text and (predicate is None or predicate(text)):
                    return text
            found = deep_find_key_string(item, wanted_keys, predicate)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = deep_find_key_string(item, wanted_keys, predicate)
            if found:
                return found
    return ""


def extract_elements_session_id(init_payload: dict[str, Any]) -> str:
    by_key = deep_find_key_string(
        init_payload,
        ("elements_session_id", "elementsSessionId", "session_id", "sessionId"),
        lambda text: text.startswith("elements_session_"),
    )
    if by_key:
        return by_key
    return deep_find_first_string(init_payload, lambda text: text.startswith("elements_session_"))


def chatgpt_success_return_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    entity = processor_entity_for_country(country, processor_entity)
    return f"https://chatgpt.com/checkout/verify?stripe_session_id={cs_id}&processor_entity={entity}&plan_type=plus"


def stripe_checkout_long_url(cs_id: str, country: str, processor_entity: str = "") -> str:
    return (
        f"https://checkout.stripe.com/c/pay/{cs_id}"
        f"?returned_from_redirect=true&ui_mode=custom&return_url="
        f"{quote(chatgpt_success_return_url(cs_id, country, processor_entity), safe='')}"
    )


def stripe_confirm_return_url(cs_id: str, checkout: dict[str, Any], stripe_hosted_url: str) -> str:
    hosted_url = to_openai_pay_url(stripe_hosted_url) or stripe_checkout_long_url(
        cs_id,
        checkout["billing_country"],
        checkout.get("processor_entity", ""),
    )
    if "pay.openai.com/" in hosted_url or "checkout.stripe.com/" in hosted_url:
        parsed = urlsplit(hosted_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault(
            "success_return_url",
            chatgpt_success_return_url(
                cs_id,
                checkout["billing_country"],
                checkout.get("processor_entity", ""),
            ),
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return hosted_url


def expected_amount(init_payload: Any) -> str:
    """Return the checkout amount from a Stripe init payload, or empty string if unknown."""
    if not isinstance(init_payload, dict):
        return ""
    total_summary = init_payload.get("total_summary")
    if isinstance(total_summary, dict) and total_summary.get("due") is not None:
        return str(total_summary.get("due"))
    invoice = init_payload.get("invoice")
    if isinstance(invoice, dict) and invoice.get("amount_due") is not None:
        return str(invoice.get("amount_due"))
    line_items = init_payload.get("line_items")
    if isinstance(line_items, list):
        total = 0
        found = False
        for item in line_items:
            if isinstance(item, dict) and item.get("amount") is not None:
                try:
                    total += int(item.get("amount") or 0)
                    found = True
                except Exception:
                    pass
        if found:
            return str(total)
    return ""


def stripe_context(cs_id: str, init_payload: dict[str, Any], req: LongLinkRequest) -> dict[str, Any]:
    _, elements_locale = locale_parts(req.payment_locale)
    amount_str = expected_amount(init_payload) or "0"
    elements_session_id = extract_elements_session_id(init_payload) or f"elements_session_{uuid.uuid4().hex[:11]}"
    # AU 含 10% GST：stripe_init 返回的 invoice 金额通常不含税，创建 PM 后 Stripe 重新计算 upcoming_invoice 会加上 GST
    if str(req.payment_method_country or "").upper() == "AU" or str(req.billing_country or "").upper() == "AU":
        try:
            amount_str = str(int(int(amount_str) * 1.1 + 0.9999))
        except Exception:
            pass
    return {
        "stripe_js_id": str(init_payload.get("_stripe_js_id") or uuid.uuid4()),
        "elements_session_id": elements_session_id,
        "elements_session_config_id": str(init_payload.get("config_id") or uuid.uuid4()),
        "config_id": init_payload.get("config_id") or "",
        "init_checksum": init_payload.get("init_checksum") or "",
        "currency": str(init_payload.get("currency") or currency_for_country(effective_country(req))).lower(),
        "checkout_amount": amount_str,
        "locale": elements_locale,
    }


def billing_for_country(country: str) -> dict[str, str]:
    country = normalize_country(country)
    if country == "DE":
        first_name, last_name = random.choice(DE_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(DE_BILLING_STREETS)
    elif country == "US":
        first_name, last_name = random.choice(US_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(US_BILLING_STREETS)
    elif country == "AU":
        first_name, last_name = random.choice(AU_BILLING_NAMES)
        line1, city, state, postal_code = random.choice(AU_BILLING_STREETS)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的账单资料地区: {country}")
    suffix = random.randint(1000, 9999)
    return {
        "name": f"{first_name} {last_name}",
        "email": f"{first_name.lower()}.{last_name.lower()}{suffix}@example.com",
        "country": country,
        "line1": line1,
        "city": city,
        "state": state,
        "postal_code": postal_code,
    }


def build_stripe_session(req: LongLinkRequest, proxy_override: str = "") -> Any:
    proxy = proxy_override or checkout_stage_proxy(req)
    stripe = new_session(proxy)
    stripe.headers.update(
        {
            "User-Agent": req.user_agent.strip() or DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    set_proxy_url(stripe, proxy)
    return stripe


def stripe_create_payment_method(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    billing: dict[str, str],
    ctx: dict[str, Any],
) -> str:
    if CTF_MOCK_MODE:
        return f"pm_mock_{uuid.uuid4().hex[:18]}"
    runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
    body = {
        "billing_details[name]": billing.get("name") or "John Doe",
        "billing_details[email]": billing.get("email") or "buyer@example.com",
        "billing_details[address][country]": billing.get("country") or "US",
        "billing_details[address][line1]": billing.get("line1") or "3110 Sunset Boulevard",
        "billing_details[address][city]": billing.get("city") or "Los Angeles",
        "billing_details[address][postal_code]": billing.get("postal_code") or "90026",
        "billing_details[address][state]": billing.get("state") or "CA",
        "type": "paypal",
        "payment_user_agent": f"stripe.js/{runtime_version}; stripe-js-v3/{runtime_version}; payment-element; deferred-intent",
        "referrer": "https://chatgpt.com",
        "time_on_page": str(random.randint(25000, 55000)),
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
        "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "elements",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "2021",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    response = stripe.post("https://api.stripe.com/v1/payment_methods", data=body, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe payment_methods failed: {response.text[:500]}")
    pm_id = str((response.json() or {}).get("id") or "")
    if not pm_id.startswith("pm_"):
        raise HTTPException(status_code=502, detail=f"stripe payment_methods bad response: {response.text[:300]}")
    return pm_id


def stripe_confirm(
    stripe: Any,
    cs_id: str,
    pm_id: str,
    stripe_pk: str,
    init_payload: dict[str, Any],
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    stripe_hosted_url: str,
) -> dict[str, Any]:
    if CTF_MOCK_MODE:
        profile = mock_combo_profile(req)
        if profile["mode"] == "failed":
            return {
                "submission_attempt": {
                    "state": "failed",
                    "failure_reason": "mock_combo_rejected",
                    "failure_code": "mock_failed",
                    "failure_message": "Mock scenario rejected this combo.",
                }
            }
        redirect_url = f"https://www.paypal.com/agreements/approve?ba_token={profile['ba_token']}"
        if profile["mode"] == "approve":
            return {
                "submission_attempt": {"state": "requires_approval"},
                "approval_method": "chatgpt_approve",
            }
        return {
            "submission_attempt": {"state": "processing"},
            "next_action": {"type": "redirect_to_url", "redirect_to_url": {"url": redirect_url}},
        }
    return_url = stripe_confirm_return_url(cs_id, checkout, stripe_hosted_url)
    runtime_version = str(ctx.get("runtime_version") or DEFAULT_STRIPE_RUNTIME_VERSION)
    body: dict[str, str] = {
        "guid": uuid.uuid4().hex,
        "muid": uuid.uuid4().hex,
        "sid": uuid.uuid4().hex,
        "payment_method": pm_id,
        "init_checksum": str(init_payload.get("init_checksum") or ctx.get("init_checksum") or ""),
        "version": runtime_version,
        "expected_payment_method_type": "paypal",
        "return_url": return_url,
        "elements_session_client[session_id]": ctx["elements_session_id"],
        "elements_session_client[locale]": str(ctx.get("locale") or "en"),
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "client_attribution_metadata[client_session_id]": ctx["stripe_js_id"],
        "client_attribution_metadata[checkout_session_id]": cs_id,
        "client_attribution_metadata[checkout_config_id]": ctx.get("config_id") or "",
        "client_attribution_metadata[elements_session_id]": ctx["elements_session_id"],
        "client_attribution_metadata[elements_session_config_id]": ctx["elements_session_config_id"],
        "client_attribution_metadata[merchant_integration_source]": "checkout",
        "client_attribution_metadata[merchant_integration_subtype]": "payment-element",
        "client_attribution_metadata[merchant_integration_version]": "custom",
        "client_attribution_metadata[payment_intent_creation_flow]": "deferred",
        "client_attribution_metadata[payment_method_selection_flow]": "automatic",
        "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
        "client_attribution_metadata[merchant_integration_additional_elements][1]": "address",
        "consent[terms_of_service]": "accepted",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    body["expected_amount"] = str(ctx.get("checkout_amount") or expected_amount(init_payload))
    response = stripe.post(f"https://api.stripe.com/v1/payment_pages/{cs_id}/confirm", data=body, timeout=DEFAULT_TIMEOUT)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=f"stripe confirm failed: {response.text[:500]}")
    return response.json() or {}


def is_external_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_paypal_url(value: str) -> bool:
    host = (urlsplit(value).netloc or "").lower()
    return bool(re.match(r"^(?:.+\.)?paypal\.com(?:\.[a-z]{2,3})?$", host)) or bool(re.match(r"^(?:.+\.)?paypalobjects\.com$", host))


def is_paypal_ba_approve_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if not re.match(r"^(?:.+\.)?paypal\.com(?:\.[a-z]{2,3})?$", host):
        return False
    path = parsed.path.rstrip("/").lower()
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return path == "/agreements/approve" and bool(str(query.get("ba_token") or "").strip())


def is_ignored_resource_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    ignored_hosts = {
        "stripe-camo.global.ssl.fastly.net",
        "files.stripe.com",
        "q.stripe.com",
        "js.stripe.com",
        "m.stripe.network",
    }
    ignored_suffixes = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".ico", ".css", ".js", ".woff", ".woff2")
    if host in ignored_hosts or any(host.endswith(f".{item}") for item in ignored_hosts):
        return True
    if path.endswith(ignored_suffixes):
        return True
    return False


def is_non_return_external_url(value: str) -> bool:
    host = (urlsplit(value).netloc or "").lower()
    return (
        is_external_url(value)
        and not is_ignored_resource_url(value)
        and host not in {"chatgpt.com", "pay.openai.com"}
        and not host.endswith(".chatgpt.com")
    )


def collect_urls(payload: Any, urls: list[str] | None = None) -> list[str]:
    found = urls if urls is not None else []
    if isinstance(payload, str):
        for match in re.findall(r"https?://[^\s\"'<>]+", payload):
            found.append(match.rstrip("),.;]"))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if key in ("url", "return_url", "redirect_url", "redirect_to_url") and isinstance(value, str) and is_external_url(value):
                found.append(value)
            else:
                collect_urls(value, found)
    elif isinstance(payload, list):
        for item in payload:
            collect_urls(item, found)
    return found


def extract_redirect_to_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        urls = collect_urls(payload)
        return next(
            (item for item in urls if is_paypal_ba_approve_url(item)),
            next((item for item in urls if is_paypal_url(item) and not is_ignored_resource_url(item)), ""),
        )
    next_action = payload.get("next_action")
    if isinstance(next_action, dict) and next_action.get("type") == "redirect_to_url":
        redirect_to_url = next_action.get("redirect_to_url") or {}
        if isinstance(redirect_to_url, dict):
            url = str(redirect_to_url.get("url") or "").strip()
            if url:
                return url
    for key in ("setup_intent", "payment_intent"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = extract_redirect_to_url(nested)
            if found:
                return found
    urls = collect_urls(payload)
    return next(
        (item for item in urls if is_paypal_ba_approve_url(item)),
        next((item for item in urls if is_paypal_url(item) and not is_ignored_resource_url(item)), ""),
    )


def payload_approval_method(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get("approval_method")
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        return str(value.get("type") or value.get("method") or value.get("name") or "").strip()
    return ""


def payload_next_action_type(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get("next_action")
    if isinstance(value, dict):
        return str(value.get("type") or "").strip()
    return ""


def diagnostic_url_candidates(payload: Any, limit: int = 2) -> list[str]:
    urls = collect_urls(payload)
    found: list[str] = []
    seen: set[str] = set()
    for item in urls:
        url = str(item or "").strip()
        if not url or url in seen or is_ignored_resource_url(url):
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= max(1, int(limit or 1)):
            break
    return found


def stripe_payload_diagnostics(payload: Any, ctx: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return f"payload_type={type(payload).__name__}"
    keys = ",".join(sorted(payload.keys())[:12])
    urls = collect_urls(payload)
    paypal_count = sum(1 for item in urls if is_paypal_url(item))
    ba_count = sum(1 for item in urls if is_paypal_ba_approve_url(item))
    ignored_count = sum(1 for item in urls if is_ignored_resource_url(item))
    submission = find_submission_attempt(payload)
    submission_state = str(submission.get("state") or "") if isinstance(submission, dict) else ""
    submission_fields = submission_attempt_failure_fields(submission)
    submission_reason = first_non_empty(
        submission_fields,
        "reason",
        "failure_reason",
        "decline_code",
        "failure_code",
        "code",
    )
    submission_code = first_non_empty(submission_fields, "code", "decline_code", "failure_code")
    submission_message = first_non_empty(submission_fields, "message", "failure_message", "error")
    approval_method = payload_approval_method(payload)
    next_action_type = payload_next_action_type(payload)
    redirect_candidate = extract_redirect_to_url(payload)
    candidate_urls = diagnostic_url_candidates(payload)
    return (
        f"keys=[{keys}], urls={len(urls)}, paypal_urls={paypal_count}, ba_approve_urls={ba_count}, "
        f"ignored_resource_urls={ignored_count}, submission_attempt={bool(submission)}, submission_state={submission_state or '未知'}, "
        f"submission_reason={submission_reason or '无'}, submission_code={submission_code or '无'}, "
        f"submission_message={submission_message or '无'}, approval_method={approval_method or '无'}, "
        f"next_action_type={next_action_type or '无'}, redirect_candidate={short_error(redirect_candidate, 120) or '无'}, "
        f"candidate_urls={' | '.join(short_error(item, 90) for item in candidate_urls) or '无'}, "
        f"ctx_session={ctx.get('elements_session_id') or ''}"
    )


def first_non_empty(values: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(values.get(key) or "").strip()
        if value:
            return value
    return ""


def submission_attempt_failure_fields(submission: Any) -> dict[str, str]:
    wanted = {
        "error",
        "code",
        "message",
        "reason",
        "failure_reason",
        "decline_code",
        "failure_code",
        "failure_message",
    }
    found: dict[str, str] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key or "").strip()
                if normalized in wanted and normalized not in found:
                    if isinstance(item, (str, int, float, bool)):
                        text = str(item).strip()
                    elif isinstance(item, dict):
                        text = str(
                            item.get("message")
                            or item.get("code")
                            or item.get("reason")
                            or item.get("type")
                            or ""
                        ).strip()
                    else:
                        text = ""
                    if text:
                        found[normalized] = text[:240]
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    if isinstance(submission, dict):
        walk(submission)
    return found


def submission_attempt_summary(submission: dict[str, Any]) -> str:
    if not submission:
        return "未找到 submission_attempt"
    fields = submission_attempt_failure_fields(submission)
    state = str(submission.get("state") or "未知").strip()
    reason = first_non_empty(fields, "reason", "failure_reason", "decline_code", "failure_code", "code")
    code = first_non_empty(fields, "code", "decline_code", "failure_code")
    message = first_non_empty(fields, "message", "failure_message", "error")
    parts = [f"state={state}"]
    if reason:
        parts.append(f"reason={reason}")
    if code:
        parts.append(f"code={code}")
    if message:
        parts.append(f"message={message}")
    return "，".join(parts)


def find_submission_attempt(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        item = payload.get("submission_attempt")
        if isinstance(item, dict):
            return item
        for value in payload.values():
            found = find_submission_attempt(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_submission_attempt(value)
            if found:
                return found
    return {}


class StripeRequiresApproval(Exception):
    pass


def stripe_payment_page_redirect_url(
    stripe: Any,
    cs_id: str,
    stripe_pk: str,
    req: LongLinkRequest,
    ctx: dict[str, Any],
    timeout_seconds: float = 30,
    emit: Any | None = None,
) -> str:
    if CTF_MOCK_MODE:
        profile = mock_combo_profile(req)
        if profile["mode"] == "failed":
            raise HTTPException(status_code=502, detail="redirect url resolution timeout: mock combo rejected")
        return f"https://www.paypal.com/agreements/approve?ba_token={profile['ba_token']}"
    deadline = time.time() + max(1.0, float(timeout_seconds or 30))
    last_err = ""
    params = {
        "elements_session_client[client_betas][0]": "custom_checkout_server_updates_1",
        "elements_session_client[client_betas][1]": "custom_checkout_manual_approval_1",
        "elements_session_client[elements_init_source]": "custom_checkout",
        "elements_session_client[referrer_host]": "chatgpt.com",
        "elements_session_client[session_id]": ctx["elements_session_id"],
        "elements_session_client[stripe_js_id]": ctx["stripe_js_id"],
        "elements_session_client[locale]": str(ctx.get("locale") or locale_parts(req.payment_locale)[1]),
        "elements_session_client[is_aggregation_expected]": "false",
        "elements_options_client[saved_payment_method][enable_save]": "never",
        "elements_options_client[saved_payment_method][enable_redisplay]": "never",
        "key": stripe_pk,
        "_stripe_version": STRIPE_VERSION_FULL,
    }
    if emit:
        emit("redirect", "confirm 未返回跳转，复用 Stripe session 上下文轮询 payment page。")
    poll_count = 0
    failed_grace = 3
    refreshed_active_session = False
    while time.time() < deadline:
        poll_count += 1
        if emit:
            emit("redirect", f"等待 PayPal BA 链...第 {poll_count} 次。")
        response = stripe.get(f"https://api.stripe.com/v1/payment_pages/{cs_id}", params=params, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            payload = response.json() or {}
            if emit and poll_count == 1:
                emit("redirect", f"payment page 诊断：{stripe_payload_diagnostics(payload, ctx)}")
            redirect_url = extract_redirect_to_url(payload)
            if redirect_url:
                if emit:
                    emit("redirect", "轮询响应发现 PayPal 跳转候选。")
                return redirect_url
            submission = find_submission_attempt(payload)
            if submission.get("state") == "requires_approval":
                raise StripeRequiresApproval("payment page requires ChatGPT approval")
            if submission.get("state") == "failed":
                if poll_count <= failed_grace:
                    if emit:
                        emit("redirect", f"第 {poll_count} 次轮询发现 submission failed，继续等待状态同步...")
                    time.sleep(2)
                    continue
                last_err = stripe_payload_diagnostics(payload, ctx)
                if emit:
                    emit("redirect", f"Stripe submission 已失败：{submission_attempt_summary(submission)}。")
                raise HTTPException(status_code=502, detail=f"stripe submission failed: {last_err}")
            last_err = stripe_payload_diagnostics(payload, ctx)
            if emit and (poll_count == 1 or poll_count % 5 == 0):
                if any(is_ignored_resource_url(item) for item in collect_urls(payload)):
                    emit("redirect", "检测到 Stripe 资源 URL，已忽略，不作为 PayPal 授权链。")
                emit("redirect", "仍在等待 PayPal BA approve 链。")
        else:
            last_err = f"http {response.status_code}: {response.text[:120]}"
            if response.status_code == 400:
                try:
                    error = (response.json() or {}).get("error") or {}
                except Exception:
                    error = {}
                error_code = str(error.get("code") or "").strip()
                if error_code == "checkout_not_active_session" and not refreshed_active_session:
                    refreshed_active_session = True
                    if emit:
                        emit("redirect", "Stripe active session 已失效，正在刷新 payment page session。")
                    try:
                        refreshed_init = _stripe_init_request(stripe, cs_id, req, stripe_pk)
                        refreshed_ctx = stripe_context(cs_id, refreshed_init, req)
                        ctx.update(
                            {
                                "stripe_js_id": refreshed_ctx["stripe_js_id"],
                                "elements_session_id": refreshed_ctx["elements_session_id"],
                                "elements_session_config_id": refreshed_ctx["elements_session_config_id"],
                                "config_id": refreshed_ctx["config_id"],
                                "init_checksum": refreshed_ctx["init_checksum"],
                                "currency": refreshed_ctx["currency"],
                                "checkout_amount": refreshed_ctx["checkout_amount"],
                                "locale": refreshed_ctx["locale"],
                            }
                        )
                        params["elements_session_client[session_id]"] = ctx["elements_session_id"]
                        params["elements_session_client[stripe_js_id]"] = ctx["stripe_js_id"]
                        params["elements_session_client[locale]"] = str(ctx.get("locale") or locale_parts(req.payment_locale)[1])
                        if emit:
                            emit("redirect", "Stripe active session 已刷新，继续轮询 BA 链。")
                        time.sleep(1)
                        continue
                    except Exception as exc:
                        if emit:
                            emit("redirect", f"刷新 Stripe active session 失败：{short_error(str(exc), 160)}")
            if emit and (poll_count == 1 or poll_count % 5 == 0):
                emit("redirect", f"Stripe 轮询暂未成功：HTTP {response.status_code}。")
        time.sleep(1)
    raise HTTPException(status_code=504, detail=f"redirect url resolution timeout: {last_err}")


def html_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", str(text or ""), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:160]


def response_diagnostic_summary(response: Any, body_limit: int = 240) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type") or "").strip()
    location = str(headers.get("location") or "").strip()
    text = str(getattr(response, "text", "") or "")
    title = html_title(text)
    looks_html = "<html" in text.lower() or "<head" in text.lower() or content_type.lower().startswith("text/html")
    parts = [f"status={status}"]
    if content_type:
        parts.append(f"content_type={content_type}")
    if location:
        parts.append(f"location={short_error(location, 120)}")
    if title:
        parts.append(f"title={short_error(title, 80)}")
    if looks_html:
        parts.append("body_type=html")
    snippet = short_error(re.sub(r"\s+", " ", text), body_limit)
    if snippet:
        parts.append(f"body={snippet}")
    return ", ".join(parts)


def chatgpt_approve(chatgpt: Any, cs_id: str, checkout: dict[str, Any]) -> None:
    if CTF_MOCK_MODE:
        return
    country = checkout["billing_country"]
    processor_entity = processor_entity_for_country(country, checkout.get("processor_entity", ""))
    try:
        chatgpt.post(
            "https://chatgpt.com/backend-api/sentinel/ping",
            json={},
            headers={
                "Referer": "https://chatgpt.com/",
                "x-openai-target-path": "/backend-api/sentinel/ping",
                "x-openai-target-route": "/backend-api/sentinel/ping",
            },
            timeout=CHATGPT_TIMEOUT,
        )
    except Exception:
        pass
    response = chatgpt.post(
        "https://chatgpt.com/backend-api/payments/checkout/approve",
        json={"checkout_session_id": cs_id, "processor_entity": processor_entity},
        headers={
            "Referer": f"https://chatgpt.com/checkout/{processor_entity}/{cs_id}",
            "x-openai-target-path": "/backend-api/payments/checkout/approve",
            "x-openai-target-route": "/backend-api/payments/checkout/approve",
        },
        timeout=CHATGPT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"chatgpt approve failed: {response_diagnostic_summary(response, body_limit=320)}",
        )
    try:
        payload = response.json() or {}
        result = payload.get("result")
    except Exception:
        result = ""
        payload = None
    if payload is None:
        raise HTTPException(status_code=502, detail=f"chatgpt approve non-json response: {response_diagnostic_summary(response, body_limit=320)}")
    if result != "approved":
        raise HTTPException(
            status_code=502,
            detail=(
                f"chatgpt approve unexpected result: result={result!r}, "
                f"{response_diagnostic_summary(response, body_limit=220)}"
            ),
        )


def chatgpt_approve_with_retry(
    req: LongLinkRequest,
    cs_id: str,
    checkout: dict[str, Any],
    emit: Any | None = None,
) -> Any:
    last_error = ""
    for attempt in range(1, CHATGPT_RETRY_ATTEMPTS + 1):
        attempt_req = request_with_rotated_jp_session(req)
        if emit:
            emit("approve", f"approve 第 {attempt}/{CHATGPT_RETRY_ATTEMPTS} 次：正在检测 JP 出口。")
        probe = probe_proxy("approve JP", checkout_stage_proxy(attempt_req), "JP", required=True)
        if not probe.ok:
            last_error = probe.error or "JP 代理检测失败"
            if emit:
                emit("approve", f"approve 第 {attempt} 次 JP session 不可用：{last_error}")
            continue
        if emit:
            emit("approve", f"approve JP 出口：{probe.ip} / {probe.country_code} {probe.country}。")
        try:
            if emit:
                emit("approve", f"approve 第 {attempt}/{CHATGPT_RETRY_ATTEMPTS} 次：正在建立 ChatGPT 会话。")
            chatgpt = build_chatgpt_session(attempt_req)
            if emit:
                emit("approve", f"approve 第 {attempt}/{CHATGPT_RETRY_ATTEMPTS} 次：正在提交 ChatGPT approve。")
            chatgpt_approve(chatgpt, cs_id, checkout)
            if emit:
                emit("approve", "ChatGPT approve 请求成功。")
            return chatgpt
        except HTTPException as exc:
            if not is_retryable_provider_http_exception(exc):
                raise
            last_error = str(exc.detail or exc)
            if emit:
                emit("provider", f"provider 网络异常，准备更换 US session：{short_error(last_error)}")
        except Exception as exc:
            if not is_retryable_network_error(exc):
                raise
            last_error = str(exc)
            if emit:
                emit("approve", f"approve 第 {attempt} 次网络超时/连接失败，正在更换 JP session：{last_error}")
    raise HTTPException(
        status_code=504,
        detail=f"ChatGPT approve 连续超时，已自动更换 JP session {CHATGPT_RETRY_ATTEMPTS} 次仍失败: {last_error}",
    )


def redirect_url_after_confirm(
    chatgpt: Any,
    stripe: Any,
    confirm_payload: dict[str, Any],
    cs_id: str,
    stripe_pk: str,
    ctx: dict[str, Any],
    checkout: dict[str, Any],
    req: LongLinkRequest,
    emit: Any | None = None,
) -> str:
    def approve_with_existing_or_retry() -> Any:
        try:
            chatgpt_approve(chatgpt, cs_id, checkout)
            if emit:
                emit("approve", "ChatGPT approve 请求成功（复用 checkout session）。")
            return chatgpt
        except HTTPException as exc:
            if is_retryable_provider_http_exception(exc):
                return chatgpt_approve_with_retry(req, cs_id, checkout, emit=emit)
            raise
        except Exception as exc:
            if is_retryable_network_error(exc):
                return chatgpt_approve_with_retry(req, cs_id, checkout, emit=emit)
            raise

    if emit:
        emit("redirect", "正在从 confirm payload 提取 PayPal 跳转。")
    redirect_url = extract_redirect_to_url(confirm_payload)
    if redirect_url:
        return redirect_url
    if emit:
        emit("redirect", f"confirm 诊断：{stripe_payload_diagnostics(confirm_payload, ctx)}")
    submission = find_submission_attempt(confirm_payload)
    if submission.get("state") == "requires_approval":
        if emit:
            emit("approve", "Stripe 要求 ChatGPT approve，正在使用 JP 代理提交 approve。")
        chatgpt = approve_with_existing_or_retry()
        return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx, timeout_seconds=45, emit=emit)
    if submission.get("state") == "failed":
        diagnostics = stripe_payload_diagnostics(confirm_payload, ctx)
        if emit:
            emit("redirect", f"Stripe submission 已失败：{submission_attempt_summary(submission)}。")
        raise HTTPException(status_code=502, detail=f"stripe submission failed: {diagnostics}")
    try:
        return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx, timeout_seconds=30, emit=emit)
    except StripeRequiresApproval:
        if emit:
            emit("approve", "轮询 payment page 发现 requires_approval，正在提交 ChatGPT approve。")
        chatgpt = approve_with_existing_or_retry()
        if emit:
            emit("approve", "ChatGPT approve 已通过，继续轮询 PayPal BA approve 跳转。")
        return stripe_payment_page_redirect_url(stripe, cs_id, stripe_pk, req, ctx, timeout_seconds=45, emit=emit)


def resolve_external_redirect(stripe: Any, redirect_url: str, preferred_hosts: tuple[str, ...] = (), max_hops: int = 10) -> str:
    current = str(redirect_url or "").strip()
    for _ in range(max(1, int(max_hops or 1))):
        if not current:
            return ""
        if is_paypal_ba_approve_url(current):
            return current
        host = (urlsplit(current).netloc or "").lower()
        try:
            response = stripe.get(current, allow_redirects=False, timeout=DEFAULT_TIMEOUT)
        except Exception:
            return current
        if response.status_code not in (301, 302, 303, 307, 308):
            return current
        location = str(response.headers.get("Location") or "").strip()
        if not location:
            return current
        current = urljoin(current, location)
    return current


def create_provider_link(
    chatgpt: Any,
    checkout: dict[str, Any],
    init_payload: dict[str, Any],
    stripe_hosted_url: str,
    req: LongLinkRequest,
    provider_proxy: str = "",
    emit: Any | None = None,
) -> dict[str, str]:
    stripe_pk = stripe_key_for_request(req, checkout)
    if emit:
        emit("provider", "正在创建 Stripe/Provider 会话。")
    stripe = build_stripe_session(req, proxy_override=provider_proxy)
    ctx = stripe_context(checkout["cs_id"], init_payload, req)
    pm_country = effective_payment_method_country(req)
    billing = billing_for_country(pm_country)
    if emit:
        emit("billing", f"已选择 PM 账单 {billing['country']} 随机资料：{billing['name']} / {billing['city']}。")
        emit("payment_method", "正在请求 Stripe 创建 PayPal payment_method。")
    pm_id = stripe_create_payment_method(stripe, checkout["cs_id"], stripe_pk, billing, ctx)
    if emit:
        emit("payment_method", f"PayPal payment_method 创建成功：{pm_id}。")
        emit("confirm", "正在请求 Stripe confirm。")
    confirm_payload = stripe_confirm(
        stripe,
        checkout["cs_id"],
        pm_id,
        stripe_pk,
        init_payload,
        ctx,
        checkout,
        req,
        stripe_hosted_url,
    )
    if emit:
        emit("confirm", "Stripe confirm 已返回，正在解析 PayPal 跳转。")
    stripe_redirect_url = redirect_url_after_confirm(
        chatgpt,
        stripe,
        confirm_payload,
        checkout["cs_id"],
        stripe_pk,
        ctx,
        checkout,
        req,
        emit=emit,
    )
    if emit:
        emit("redirect", "正在跟随 Stripe 跳转并提取 PayPal BA approve 链。")
    provider_url = (
        stripe_redirect_url
        if is_paypal_ba_approve_url(stripe_redirect_url)
        else resolve_external_redirect(stripe, stripe_redirect_url, preferred_hosts=("paypal.com",))
    )
    if not is_paypal_ba_approve_url(provider_url):
        resource_hint = "仅发现 Stripe 资源 URL，未发现 PayPal BA approve 链；" if is_ignored_resource_url(provider_url) else ""
        raise HTTPException(
            status_code=502,
            detail=(
                f"{resource_hint}未提取到最终 PayPal BA approve 链；成功标准必须为 "
                "https://www.paypal.com/agreements/approve?ba_token=...；"
                f"当前结果: {provider_url or stripe_redirect_url}"
            ),
        )
    if emit:
        emit("done", "已提取到 PayPal BA approve 链。")
    return {
        "payment_method_id": pm_id,
        "stripe_redirect_url": stripe_redirect_url,
        "provider_redirect_url": provider_url,
        "long_url": provider_url,
    }


def create_provider_link_with_retry(
    chatgpt: Any,
    checkout: dict[str, Any],
    req: LongLinkRequest,
    provider_country: str = "US",
    emit: Any | None = None,
) -> dict[str, str]:
    proxy_country = (provider_country or "US").upper()
    last_error = ""
    base_proxy = provider_proxy_for_country(req, proxy_country)
    rotated = rotate_kookeey_proxy_session(base_proxy, proxy_country)
    can_rotate = rotated != base_proxy
    max_attempts = PROVIDER_RETRY_ATTEMPTS if can_rotate else 1
    for attempt in range(1, max_attempts + 1):
        if can_rotate:
            rotated_proxy = rotate_kookeey_proxy_session(base_proxy, proxy_country)
            attempt_req = req.model_copy(update={"us_proxy": rotated_proxy, "au_proxy": rotated_proxy})
            if emit:
                emit("provider", f"provider 第 {attempt}/{max_attempts} 次：轮换 {proxy_country} session。")
                emit("proxy", f"provider 第 {attempt}/{max_attempts} 次：正在检测 {proxy_country} 出口。")
        else:
            attempt_req = req
            if emit:
                emit("provider", f"provider {proxy_country} 单代理模式，跳过轮换。")
        provider_proxy = provider_proxy_for_country(attempt_req, proxy_country)
        provider_probe = check_provider_proxy_for(attempt_req, proxy_country)
        if not provider_probe.ok:
            last_error = provider_probe.error or f"provider {proxy_country} 代理不可用"
            if emit:
                emit("proxy", f"provider {proxy_country} session 不可用，准备更换：{last_error}")
            continue
        if emit:
            emit("proxy", f"provider {proxy_country} 出口：{provider_probe.ip} / {provider_probe.country_code} {provider_probe.country}。")
            emit("stripe_init", "正在请求 Stripe init。")
        try:
            init_payload = stripe_init(checkout["cs_id"], attempt_req, proxy_override=provider_proxy, checkout=checkout)
            stripe_hosted_url = str(init_payload.get("stripe_hosted_url") or "").strip()
            if not stripe_hosted_url:
                raise HTTPException(
                    status_code=502,
                    detail=f"stripe init response missing stripe_hosted_url, keys={sorted(init_payload.keys())}",
                )
            if emit:
                emit("stripe_init", "Stripe init 成功。")
            # Free-trial guard: the promo "plus-1-month-free" must produce $0.
            # If the amount is non-zero the access token is not eligible and
            # we should stop immediately instead of creating a paid agreement.
            init_amount = expected_amount(init_payload)
            if init_amount and init_amount != "0":
                if emit:
                    emit("stripe_init", f"结账金额非 $0（当前: {init_amount}），此号无免费试用资格，终止。")
                raise HTTPException(
                    status_code=400,
                    detail=f"此 access token 无免费试用资格（结账金额: {init_amount}），已终止。请使用有免费试用资格的账号。",
                )
            if emit:
                if init_amount == "0":
                    emit("stripe_init", f"结账金额确认：$0（免费试用），继续。")
                else:
                    emit("stripe_init", "结账金额未检测到，继续。")
            provider = create_provider_link(
                chatgpt,
                checkout,
                init_payload,
                stripe_hosted_url,
                attempt_req,
                provider_proxy=provider_proxy,
                emit=emit,
            )
            provider["stripe_hosted_url"] = stripe_hosted_url
            return provider
        except HTTPException as exc:
            if not is_retryable_provider_http_exception(exc):
                raise
            last_error = str(exc.detail or exc)
            if emit:
                emit("provider", f"provider 网络异常，准备更换 US session：{short_error(last_error)}")
        except Exception as exc:
            if not is_retryable_network_error(exc):
                raise
            last_error = str(exc)
            if emit:
                emit("provider", f"provider 网络异常，准备更换 US session：{short_error(last_error)}")
    raise HTTPException(
        status_code=504,
        detail=f"provider 网络异常，已更换 US session 重试 {PROVIDER_RETRY_ATTEMPTS} 次仍失败: {short_error(last_error)}",
    )


app = FastAPI(title="OpenAI Pay Long Link")
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/check-proxy", response_model=ProxyCheckResponse)
def check_proxy(req: ProxyCheckRequest) -> ProxyCheckResponse:
    results = [
        probe_proxy("checkout/approve JP", req.jp_proxy, "JP", required=True),
    ]
    if req.us_proxy:
        results.append(probe_proxy("provider US", req.us_proxy, "US", required=False))
    if req.au_proxy:
        results.append(probe_proxy("provider AU", req.au_proxy, "AU", required=False))
    if not req.us_proxy and not req.au_proxy:
        results.append(probe_proxy("provider US", req.us_proxy or req.au_proxy, "US", required=True))
    mark_same_exit(results)
    return ProxyCheckResponse(ok=all(item.ok for item in results), results=results)


@app.post("/api/long-link", response_model=LongLinkResponse)
def generate_long_link(req: LongLinkRequest) -> LongLinkResponse:
    return generate_long_link_payload(req)


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def cleanup_run_jobs(now: float | None = None) -> None:
    current_time = time.time() if now is None else now
    with RUN_JOBS_LOCK:
        expired = [
            run_id
            for run_id, job in RUN_JOBS.items()
            if bool(job.get("done")) and current_time - float(job.get("completed_at") or job.get("created_at") or current_time) > RUN_JOB_TTL_SECONDS
        ]
        for run_id in expired:
            RUN_JOBS.pop(run_id, None)
        if len(RUN_JOBS) > RUN_JOB_MAX_ITEMS:
            ordered = sorted(RUN_JOBS.items(), key=lambda item: float(item[1].get("created_at") or 0))
            for run_id, job in ordered[: max(0, len(RUN_JOBS) - RUN_JOB_MAX_ITEMS)]:
                if bool(job.get("done")):
                    RUN_JOBS.pop(run_id, None)


def make_log_event(run_id: str, step: str, message: str, started_at: float, **extra: Any) -> dict[str, Any]:
    now = time.time()
    raw_message = str(message or "")
    compacted = compact_log_message(step, raw_message)
    include_raw = compacted != re.sub(r"\s+", " ", raw_message).strip() and (
        "诊断：" in raw_message or "Stripe submission 已失败" in raw_message or step in {"redirect", "error"}
    )
    return {
        "type": "log",
        "run_id": run_id,
        "step": step,
        "message": compacted,
        "ts": now,
        "elapsed_ms": int((now - started_at) * 1000),
        **({"raw_message": raw_message} if include_raw else {}),
        **extra,
    }


def make_error_event(run_id: str, message: str, started_at: float, status_code: int | None = None) -> dict[str, Any]:
    now = time.time()
    raw_message = str(message or "")
    compacted = compact_log_message("error", raw_message)
    event: dict[str, Any] = {
        "type": "error",
        "run_id": run_id,
        "step": "error",
        "message": compacted,
        "ts": now,
        "elapsed_ms": int((now - started_at) * 1000),
    }
    if compacted != re.sub(r"\s+", " ", raw_message).strip():
        event["raw_message"] = raw_message
    if status_code is not None:
        event["status_code"] = status_code
    return event


def compact_log_message(step: str, message: str) -> str:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return ""
    if step == "summary" or text.startswith("组合结果："):
        return short_error(text, 360)
    if "运行编号：" in text:
        return text
    if "尝试组合" in text:
        match = re.search(r"尝试组合\s+(\d+/\d+).*checkout=([A-Z]{2})/([A-Z]{3})，PM=([A-Z]{2})", text)
        return f"组合 {match.group(1)}：{match.group(2)}+{match.group(4)} / {match.group(3)}" if match else short_error(text, 80)
    if "开始执行 PP 链提取流程" in text:
        return "开始执行，组合回退已开启"
    if "当前组合：" in text:
        match = re.search(r"checkout账单=([A-Z]{2})/([A-Z]{3})，PM账单=([A-Z]{2})，provider代理=([A-Z]{2})", text)
        return (
            f"账单 {match.group(1)}/{match.group(2)}，PM {match.group(3)}，provider {match.group(4)}"
            if match else short_error(text, 90)
        )
    if "检测 provider " in text and "出口" in text:
        match = re.search(r"检测 provider\s+([A-Z]{2})\s+出口", text)
        return f"预检 {match.group(1)}，JP 分阶段检测" if match else "预检 provider，JP 分阶段检测"
    if "provider " in text and "自动轮换粘性 session" in text:
        match = re.search(r"provider\s+([A-Z]{2})\s+第\s+(\d+/\d+)", text)
        return f"轮换 {match.group(1)} 节点 {match.group(2)}" if match else "轮换 provider 节点"
    if "自动切换下一个组合" in text:
        match = re.search(r"checkout=([A-Z]{2})，PM=([A-Z]{2})，proxy=([A-Z]{2})", text)
        return (
            f"切换组合：{match.group(1)}+{match.group(2)}@{match.group(3)}"
            if match else "切换下一个组合"
        )
    if "未拿到 BA approve" in text:
        match = re.search(r"组合\s+([A-Z]{2}\+[A-Z]{2}(?:@[A-Z]{2})?)", text)
        return f"组合 {match.group(1)} 失败，未拿到 BA 链" if match else "当前组合失败，未拿到 BA 链"
    if "失败且不可回退" in text:
        match = re.search(r"组合\s+([A-Z]{2}\+[A-Z]{2}(?:@[A-Z]{2})?)", text)
        return f"组合 {match.group(1)} 失败，停止运行" if match else "组合失败，停止运行"
    if "Stripe submission 已失败" in text:
        reason = re.search(r"reason=([^，。]+)", text)
        return f"Stripe 拒绝：{reason.group(1)}" if reason else "Stripe 拒绝付款"
    if text.startswith("confirm 诊断：") or text.startswith("payment page 诊断："):
        prefix = "confirm 诊断" if text.startswith("confirm 诊断：") else "payment page 诊断"
        state = re.search(r"submission_state=([^,，]+)", text)
        reason = re.search(r"submission_reason=([^,，]+)", text)
        code = re.search(r"submission_code=([^,，]+)", text)
        approval = re.search(r"approval_method=([^,，]+)", text)
        redirect = re.search(r"redirect_candidate=([^,，]+)", text)
        parts = []
        if state:
            parts.append(f"state={state.group(1)}")
        if reason:
            parts.append(f"reason={reason.group(1)}")
        if code:
            parts.append(f"code={code.group(1)}")
        if approval:
            parts.append(f"approval={approval.group(1)}")
        if redirect:
            parts.append(f"redirect={redirect.group(1)}")
        return f"{prefix}：" + ("，".join(parts) if parts else short_error(text, 180))
    if "Stripe key 来源" in text:
        match = re.search(r"Stripe key 来源：([^；。]+)", text)
        return f"Stripe key：{match.group(1)}" if match else "Stripe key 已确认"
    if "已选择 PM 账单" in text:
        match = re.search(r"PM 账单\s+([A-Z]{2}).*?：([^/。]+)", text)
        return f"PM 资料：{match.group(1)} / {match.group(2).strip()}" if match else "PM 资料已生成"
    if "正在从 confirm payload 提取 PayPal 跳转" in text:
        return "解析 confirm 跳转"
    if "Stripe 要求 ChatGPT approve" in text:
        return "需要 approve，切 JP"
    if "正在建立 ChatGPT 会话" in text:
        match = re.search(r"approve 第\s+(\d+/\d+)", text)
        return f"建立 ChatGPT 会话 {match.group(1)}" if match else "建立 ChatGPT 会话"
    if "正在提交 ChatGPT approve" in text:
        match = re.search(r"approve 第\s+(\d+/\d+)", text)
        return f"提交 approve {match.group(1)}" if match else "提交 approve"
    if "继续轮询 PayPal BA approve 跳转" in text:
        return "继续轮询 BA 链"
    if "provider 代理检测通过" in text:
        match = re.search(r"provider\s+([A-Z]{2}):\s*([^/。]+)\s*/\s*([A-Z]{2})", text)
        return (
            f"{match.group(1)} 预检通过：{match.group(2).strip()} / {match.group(3)}"
            if match else "provider 预检通过"
        )
    if "provider " in text and "出口：" in text:
        match = re.search(r"provider\s+([A-Z]{2})\s+出口：([^/。]+)\s*/\s*([A-Z]{2})", text)
        return (
            f"{match.group(1)} 出口：{match.group(2).strip()} / {match.group(3)}"
            if match else "provider 出口通过"
        )
    if "checkout JP 出口" in text:
        match = re.search(r"checkout JP 出口：([^/。]+)\s*/\s*([A-Z]{2})", text)
        return f"JP 出口：{match.group(1).strip()} / {match.group(2)}" if match else "JP 出口通过"
    if "approve JP 出口" in text:
        match = re.search(r"approve JP 出口：([^/。]+)\s*/\s*([A-Z]{2})", text)
        return f"approve JP：{match.group(1).strip()} / {match.group(2)}" if match else "approve JP 通过"
    if "checkout 创建成功" in text:
        match = re.search(r"/\s*([A-Z]{2})\s*/\s*([A-Z]{3})", text)
        return f"checkout 成功：{match.group(1)}/{match.group(2)}" if match else "checkout 成功"
    if "正在使用 JP 代理创建 ChatGPT checkout" in text:
        return "准备 checkout"
    if "正在切换到 provider 阶段代理" in text:
        match = re.search(r"provider 阶段代理：([A-Z]{2})", text)
        return f"切换 provider {match.group(1)}" if match else "切换 provider"
    if "正在创建 Stripe/Provider 会话" in text:
        return "创建 provider 会话"
    if "PayPal payment_method 创建成功" in text:
        return "PM 创建成功"
    if "Stripe confirm 已返回" in text:
        return "confirm 成功，解析跳转"
    if "ChatGPT approve 请求成功" in text or "ChatGPT approve 已通过" in text:
        return "approve 成功"
    if "JP session 不可用" in text:
        return "JP 节点不可用，换节点"
    if "provider " in text and ("session 不可用" in text or " 不可用" in text):
        match = re.search(r"provider\s+([A-Z]{2})", text)
        return f"{match.group(1)} 节点不可用，换节点" if match else "provider 节点不可用，换节点"
    if "provider 网络异常" in text:
        match = re.search(r"更换\s+([A-Z]{2})\s+session", text)
        return f"provider 网络异常，换 {match.group(1)} 节点" if match else "provider 网络异常，换节点"
    if "provider " in text and "代理检测未通过" in text:
        match = re.search(r"provider\s+([A-Z]{2})", text)
        return f"provider {match.group(1)} 代理检测失败" if match else "provider 代理检测失败"
    if "代理检测未通过" in text:
        return "代理检测失败"
    if "网络超时/连接失败" in text:
        return "网络异常，换节点"
    if "正在检测 JP 出口" in text:
        return "检测 JP 出口"
    if "正在检测 " in text and " 出口" in text:
        match = re.search(r"正在检测\s+([A-Z]{2})\s+出口", text)
        return f"检测 {match.group(1)} 出口" if match else "检测 provider 出口"
    if "正在创建 ChatGPT checkout" in text:
        return "创建 checkout"
    if "正在请求 Stripe init" in text:
        return "请求 Stripe init"
    if "Stripe init 成功" in text:
        return "Stripe init 成功"
    if "正在请求 Stripe 创建 PayPal payment_method" in text:
        return "创建 PM"
    if "正在请求 Stripe confirm" in text:
        return "请求 confirm"
    if "等待 PayPal BA 链" in text:
        return text.replace("PayPal BA 链", "BA 链")
    if len(text) > 140:
        return short_error(text, 140)
    return text


@app.post("/api/long-link/stream")
def generate_long_link_stream(req: LongLinkRequest) -> StreamingResponse:
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    run_id = new_run_id()
    started_at = time.time()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{run_id}.ndjson"
    heartbeat_seconds = 1.5

    def write_event(event: dict[str, Any]) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def emit(step: str, message: str, **extra: Any) -> None:
        event = make_log_event(run_id, step, message, started_at, **extra)
        write_event(event)
        events.put(event)

    def encode_event(event: dict[str, Any]) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n" + (" " * 16384) + "\n"

    def worker() -> None:
        try:
            emit("run", f"运行编号：{run_id}", log_path=str(log_path))
            result = generate_long_link_payload(req, emit=emit)
            now = time.time()
            event = {"type": "result", "run_id": run_id, "data": result.model_dump(), "ts": now, "elapsed_ms": int((now - started_at) * 1000)}
            write_event(event)
            events.put(event)
        except HTTPException as exc:
            event = make_error_event(run_id, str(exc.detail), started_at, exc.status_code)
            write_event(event)
            events.put(event)
        except Exception as exc:
            event = make_error_event(run_id, str(exc), started_at)
            write_event(event)
            events.put(event)
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream() -> Any:
        heartbeat_count = 0
        while True:
            try:
                event = events.get(timeout=heartbeat_seconds)
            except queue.Empty:
                heartbeat_count += 1
                yield encode_event(
                    {
                        "type": "heartbeat",
                        "run_id": run_id,
                        "step": "heartbeat",
                        "message": f"仍在执行当前步骤...{heartbeat_count}",
                        "ts": time.time(),
                        "elapsed_ms": int((time.time() - started_at) * 1000),
                    }
                )
                continue
            if event is None:
                break
            yield encode_event(event)

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def create_long_link_job(req: LongLinkRequest) -> dict[str, str]:
    cleanup_run_jobs()
    run_id = new_run_id()
    started_at = time.time()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{run_id}.ndjson"
    job: dict[str, Any] = {
        "run_id": run_id,
        "log_path": str(log_path),
        "events": [],
        "done": False,
        "created_at": started_at,
        "started_at": started_at,
        "last_heartbeat": 0.0,
    }
    with RUN_JOBS_LOCK:
        RUN_JOBS[run_id] = job

    def append_event(event: dict[str, Any]) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        with RUN_JOBS_LOCK:
            current = RUN_JOBS.get(run_id)
            if current is not None:
                current["events"].append(event)

    def emit(step: str, message: str, **extra: Any) -> None:
        append_event(make_log_event(run_id, step, message, started_at, **extra))

    def worker() -> None:
        try:
            emit("run", f"运行编号：{run_id}", log_path=str(log_path))
            result = generate_long_link_payload(req, emit=emit)
            now = time.time()
            append_event({"type": "result", "run_id": run_id, "data": result.model_dump(), "ts": now, "elapsed_ms": int((now - started_at) * 1000)})
        except HTTPException as exc:
            append_event(make_error_event(run_id, str(exc.detail), started_at, exc.status_code))
        except Exception as exc:
            append_event(make_error_event(run_id, str(exc), started_at))
        finally:
            with RUN_JOBS_LOCK:
                current = RUN_JOBS.get(run_id)
                if current is not None:
                    current["done"] = True
                    current["completed_at"] = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return {"run_id": run_id, "log_path": str(log_path)}


@app.post("/api/long-link/start")
def start_long_link_job(req: LongLinkRequest) -> dict[str, str]:
    return create_long_link_job(req)


@app.get("/api/long-link/events/{run_id}")
def long_link_job_events(run_id: str, cursor: int = 0) -> dict[str, Any]:
    cleanup_run_jobs()
    with RUN_JOBS_LOCK:
        job = RUN_JOBS.get(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="运行编号不存在或已过期")
        events = list(job["events"])
        done = bool(job["done"])
        log_path = str(job["log_path"])
        started_at = float(job.get("started_at") or job.get("created_at") or time.time())
        now = time.time()
        heartbeat_due = not done and cursor >= len(events) and now - float(job.get("last_heartbeat") or 0) >= 1.5
        if heartbeat_due:
            job["last_heartbeat"] = now
    next_cursor = max(cursor, 0)
    new_events = events[next_cursor:]
    next_cursor += len(new_events)
    if heartbeat_due:
        now = time.time()
        new_events.append(
            {
                "type": "heartbeat",
                "run_id": run_id,
                "step": "heartbeat",
                "message": "仍在执行当前步骤...",
                "ts": now,
                "elapsed_ms": int((now - started_at) * 1000),
            }
        )
    return {"run_id": run_id, "cursor": next_cursor, "done": done, "log_path": log_path, "events": new_events}


def generate_long_link_payload(req: LongLinkRequest, emit: Any | None = None) -> LongLinkResponse:
    def log(step: str, message: str) -> None:
        if emit:
            emit(step, message)

    billing_combos = configured_billing_combos(req)
    # Expand with provider proxy options: try US first, then AU if provided
    proxy_opts = _provider_proxy_options(req)
    combos: list[tuple[str, str, tuple[str, str, str]]] = []
    for cc, pm in billing_combos:
        for label, proxy_val, expected_country in proxy_opts:
            combos.append((cc, pm, (label, proxy_val, expected_country)))
    combos = sort_bill_match_priority_combos(combos)
    if req.diagnostic_mode:
        limit = max(1, min(len(combos), int(req.max_combos or 1)))
        combos = combos[:limit]
    failures: list[str] = []
    combo_results: list[dict[str, str]] = []
    failure_class_counts: dict[str, int] = {}
    log("start", f"开始执行 PP 链提取流程，{len(combos)} 种组合（{len(billing_combos)} 账单 × {len(proxy_opts)} 代理）。")
    if req.diagnostic_mode:
        log("start", f"诊断模式已启用：仅尝试前 {len(combos)} 组，避免重复空转。")

    early_stop_reason = ""
    for index, (checkout_country, pm_country, (proxy_label, proxy_url, proxy_country)) in enumerate(combos, start=1):
        combo_started_at = time.time()
        combo_label = f"{combo_name(checkout_country, pm_country)}@{proxy_country}"
        priority_label = bill_match_priority_label(checkout_country, pm_country, proxy_country)
        combo_result = {
            "combo": combo_label,
            "status": "运行中",
            "detail": "",
            "failure_class": "",
            "priority_label": priority_label,
        }
        combo_results.append(combo_result)
        combo_req = req.model_copy(
            update={
                "billing_country": checkout_country,
                "payment_method_country": pm_country,
                "provider_proxy_country": proxy_country,
            }
        )
        log(
            "combo",
            (
                f"尝试组合 {index}/{len(combos)}：checkout={checkout_country}/{currency_for_country(checkout_country)}，"
                f"PM={pm_country}，provider={proxy_country}。"
                + (f" [{priority_label}]" if priority_label else "")
            ),
        )
        try:
            result = run_single_combo(
                combo_req,
                checkout_country,
                pm_country,
                fallback=False,
                prior_failures=failures,
                provider_proxy_country=proxy_country,
                emit=emit,
            )
            if result.fallback:
                log("combo", f"组合 {combo_label} 回退成功。")
            combo_result["status"] = "成功"
            combo_result["elapsed_ms"] = str(int((time.time() - combo_started_at) * 1000))
            emit_combo_result(
                emit,
                index,
                checkout_country,
                pm_country,
                proxy_country,
                combo_req.payment_locale,
                "成功",
                int(combo_result["elapsed_ms"]),
                priority_label=priority_label,
            )
            log("summary", format_combo_results(combo_results))
            return result
        except HTTPException as exc:
            detail = str(exc.detail)
            short_detail = short_error(detail)
            failure_class = classify_combo_failure(detail)
            summary = f"{combo_label}: {short_detail}"
            failures.append(summary)
            combo_result["status"] = "失败"
            combo_result["detail"] = summarize_combo_failure(detail)
            combo_result["failure_class"] = failure_class
            combo_result["elapsed_ms"] = str(int((time.time() - combo_started_at) * 1000))
            failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
            emit_combo_result(
                emit,
                index,
                checkout_country,
                pm_country,
                proxy_country,
                combo_req.payment_locale,
                "失败",
                int(combo_result["elapsed_ms"]),
                combo_result["detail"],
                failure_class,
                priority_label,
            )
            # Always continue to next combo — never stop early
            log("combo", f"组合 {combo_label} 未拿到 BA approve：{short_detail}")
            if req.diagnostic_mode and failure_class_counts.get(failure_class, 0) >= 2:
                early_stop_reason = f"诊断模式下失败类型 {failure_class} 已重复 {failure_class_counts[failure_class]} 次"
                log("combo", f"{early_stop_reason}，提前停止后续组合。")
                break
            if index < len(combos):
                next_checkout, next_pm, _next_proxy = combos[index]
                log("combo", f"自动切换下一个组合：checkout={next_checkout}，PM={next_pm}，proxy={_next_proxy[2]}。")
        except Exception as exc:
            if not is_retryable_network_error(exc):
                log("error", f"组合 {combo_label} 异常：{exc}")
            if index < len(combos):
                log("combo", "跳过异常，尝试下一个组合。")
            detail = f"provider 网络异常: {exc}"
            short_detail = short_error(detail)
            failure_class = classify_combo_failure(detail)
            summary = f"{combo_label}: {short_detail}"
            failures.append(summary)
            combo_result["status"] = "失败"
            combo_result["detail"] = "provider 网络异常"
            combo_result["failure_class"] = failure_class
            combo_result["elapsed_ms"] = str(int((time.time() - combo_started_at) * 1000))
            failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
            emit_combo_result(
                emit,
                index,
                checkout_country,
                pm_country,
                proxy_country,
                combo_req.payment_locale,
                "失败",
                int(combo_result["elapsed_ms"]),
                combo_result["detail"],
                failure_class,
                priority_label,
            )
            log("combo", f"组合 {combo_label} 网络异常，进入下一个组合：{short_detail}")
            if req.diagnostic_mode and failure_class_counts.get(failure_class, 0) >= 2:
                early_stop_reason = f"诊断模式下失败类型 {failure_class} 已重复 {failure_class_counts[failure_class]} 次"
                log("combo", f"{early_stop_reason}，提前停止后续组合。")
                break
            if index < len(combos):
                next_checkout, next_pm, _next_proxy = combos[index]
                log("combo", f"自动切换下一个组合：checkout={next_checkout}，PM={next_pm}，proxy={_next_proxy[2]}。")

    last_detail = failures[-1] if failures else "没有可用组合"
    log("summary", format_combo_results(combo_results))
    class_summary = summarize_failure_classes(failure_class_counts)
    stop_suffix = f"；{early_stop_reason}" if early_stop_reason else ""
    class_suffix = f"；失败分类：{class_summary}" if class_summary else ""
    raise HTTPException(
        status_code=502,
        detail=f"所有组合均未提取到 PayPal BA approve 链；{'; '.join(failures) or last_detail}{class_suffix}{stop_suffix}",
    )


def combo_name(checkout_country: str, pm_country: str) -> str:
    return f"{checkout_country}+{pm_country}"


def bill_match_priority_label(checkout_country: str, pm_country: str, provider_proxy_country: str) -> str:
    checkout = normalize_country(checkout_country)
    pm = normalize_country(pm_country)
    provider = normalize_country(provider_proxy_country)
    if checkout == "US" and pm == "AU" and provider == "US":
        return "账单匹配优先#1"
    if checkout == "US" and pm == "AU" and provider == "AU":
        return "账单匹配优先#2"
    return ""


def sort_bill_match_priority_combos(
    combos: list[tuple[str, str, tuple[str, str, str]]],
) -> list[tuple[str, str, tuple[str, str, str]]]:
    def _priority(item: tuple[str, str, tuple[str, str, str]]) -> tuple[int, int]:
        checkout_country, pm_country, (_label, _proxy_val, proxy_country) = item
        priority_label = bill_match_priority_label(checkout_country, pm_country, proxy_country)
        if priority_label == "账单匹配优先#1":
            return (0, 0)
        if priority_label == "账单匹配优先#2":
            return (0, 1)
        return (1, 0)

    return sorted(list(combos), key=_priority)


def format_combo_results(combo_results: list[dict[str, str]]) -> str:
    compact: list[str] = []
    detailed: list[str] = []
    for item in combo_results:
        combo = item.get("combo") or "未知组合"
        status = item.get("status") or "未知"
        detail = item.get("detail") or ""
        priority_label = item.get("priority_label") or ""
        display_combo = f"{combo}[{priority_label}]" if priority_label else combo
        compact.append(f"{display_combo} {status}")
        detailed.append(f"{display_combo} {status}{'：' + detail if detail and status == '失败' else ''}")
    if not compact:
        return "组合结果：无已尝试组合"
    if compact == detailed:
        return "组合结果：" + "；".join(compact)
    return "组合结果：" + "；".join(compact) + "。组合详情：" + "；".join(detailed)


def emit_combo_result(
    emit: Any | None,
    index: int,
    checkout_country: str,
    pm_country: str,
    provider_proxy_country: str,
    locale: str,
    status: str,
    elapsed_ms: int,
    detail: str = "",
    failure_class: str = "",
    priority_label: str = "",
) -> None:
    if not emit:
        return
    status_text = "成功" if status == "成功" else "失败"
    provider_country = (provider_proxy_country or "US").upper()
    locale_text = locale_parts(locale)[0] if locale else "en-US"
    prefix = f"[{priority_label}] " if priority_label else ""
    message = prefix + (
        f"组合测试：{checkout_country} / {pm_country} / {currency_for_country(checkout_country)} / "
        f"{locale_text} / JP / {provider_country}"
    )
    emit(
        "combo_result",
        message,
        combo_index=index,
        combo=combo_name(checkout_country, pm_country),
        checkout_country=checkout_country,
        pm_country=pm_country,
        currency=currency_for_country(checkout_country),
        locale=locale_text,
        checkout_proxy_country="JP",
        provider_proxy_country=provider_country,
        status=status_text,
        detail=detail,
        failure_class=failure_class,
        priority_label=priority_label,
        combo_elapsed_ms=elapsed_ms,
    )


def classify_combo_failure(detail: str) -> str:
    text = str(detail or "").lower()
    if "checkout_confirm_error" in text or "confirm failed" in text:
        return "confirm_invalid_request"
    if "checkout_approval_payment_failure_with_payment_error" in text or "generic_decline" in text:
        return "submission_generic_decline"
    if "chatgpt approve non-json response" in text:
        return "approve_html_interstitial"
    if "body_type=html" in text and "chatgpt approve failed" in text:
        return "approve_html_interstitial"
    if "chatgpt approve" in text:
        return "approve_failed"
    if "provider 网络异常" in text or "proxy" in text and "不可用" in text:
        return "network_or_proxy"
    if "redirect url resolution timeout" in text or "未提取到最终 paypal ba approve 链" in text:
        return "redirect_not_found"
    return "unknown"


def summarize_failure_classes(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "；".join(f"{name} x{count}" for name, count in ordered if count > 0)


def summarize_combo_failure(detail: str) -> str:
    text = str(detail or "")

    def _extract(pattern: str) -> str:
        m = re.search(pattern, text)
        return (m.group(1) or "").strip() if m else ""

    def _extract_json_error_field(key: str) -> str:
        patterns = [
            rf'"{re.escape(key)}"\s*:\s*"([^"]+)"',
            rf"'{re.escape(key)}'\s*:\s*'([^']+)'",
        ]
        for pattern in patterns:
            value = _extract(pattern)
            if value:
                return value
        return ""

    # For stripe submission failures, compile ALL key diagnostic fields
    if "stripe submission failed" in text:
        state = _extract(r"submission_state=([^,，;；]+)")
        reason = _extract(r"submission_reason=([^,，;；]+)")
        code = _extract(r"submission_code=([^,，;；]+)")
        msg = _extract(r"submission_message=([^,，;；]+)")
        approval = _extract(r"approval_method=([^,，;；]+)")
        redirect = _extract(r"redirect_candidate=([^,，;；]+)")
        parts = []
        if state and state.lower() not in {"无", "none", "unknown", "未知"}:
            parts.append(f"state={state}")
        if reason and reason.lower() not in {"无", "none", "unknown", "未知"}:
            parts.append(f"reason={reason}")
        if code and code.lower() not in {"无", "none", "unknown", "未知"}:
            parts.append(f"code={code}")
        if msg and msg.lower() not in {"无", "none", "unknown", "未知"}:
            parts.append(f"message={short_error(msg, 50)}")
        if approval and approval.lower() not in {"无", "none", "unknown", "未知"}:
            parts.append(f"approval={approval}")
        if redirect and redirect.lower() not in {"无", "none", "unknown", "未知"}:
            parts.append(f"redirect={short_error(redirect, 40)}")
        if parts:
            return "submission failed: " + ", ".join(parts)
        return "Stripe submission failed"

    if "stripe confirm failed" in text:
        code = _extract_json_error_field("code")
        message = _extract_json_error_field("message")
        decline = _extract_json_error_field("decline_code")
        payment_type = _extract_json_error_field("type")
        parts = []
        if code:
            parts.append(f"code={code}")
        if decline:
            parts.append(f"decline={decline}")
        if payment_type:
            parts.append(f"type={payment_type}")
        if message:
            parts.append(f"message={short_error(message, 120)}")
        if parts:
            return "confirm failed: " + ", ".join(parts)
        return short_error(text, 180)

    # Generic fallback extraction
    markers = [
        r"submission_reason=([^,，;；]+)",
        r"submission_code=([^,，;；]+)",
        r"submission_message=([^,，;；]+)",
        r"reason=([^,，;；]+)",
        r"code=([^,，;；]+)",
        r"message=([^,，;；]+)",
    ]
    for marker in markers:
        match = re.search(marker, text)
        if match:
            value = match.group(1).strip()
            if value and value.lower() not in {"无", "none", "unknown", "未知"}:
                return short_error(value, 80)
    if "chatgpt approve unexpected result" in text.lower():
        return short_error(text.replace("chatgpt approve unexpected result:", "approve"), 80)
    if "代理检测未通过" in text or "代理不能为空" in text:
        return "代理检测失败"
    if "provider 网络异常" in text:
        return "provider 网络异常"
    if "redirect url resolution timeout" in text:
        return "未解析到 BA approve 链"
    if "未提取到最终 PayPal BA approve 链" in text:
        return "未提取到 BA approve 链"
    return short_error(text, 80)


def combo_attempt_order(checkout_country: str, pm_country: str) -> list[tuple[str, str]]:
    """Generate EVERY possible (checkout, PM) combination — leave no stone unturned."""
    checkout = normalize_country(checkout_country)
    pm = normalize_country(pm_country)
    all_countries = ["US", "DE", "AU"]
    ordered: list[tuple[str, str]] = []
    # Start with the selected PM and US checkout (most likely to work)
    if (checkout, pm) not in ordered:
        ordered.append((checkout, pm))
    for cc in all_countries:
        for pc in all_countries:
            item = (cc, pc)
            if item not in ordered:
                ordered.append(item)
    # Move (US, pm) and (US, US) to front
    preferred = [("US", pm), ("US", "US")]
    for p in reversed(preferred):
        if p in ordered:
            ordered.remove(p)
            ordered.insert(0, p)
    return ordered


def short_error(detail: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(detail or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def is_retryable_combo_failure(exc: HTTPException) -> bool:
    if exc.status_code in (400, 401, 403):
        return False
    detail = str(exc.detail or "").lower()
    non_retryable_markers = (
        "access token",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "invalid publishable key",
        "provider us 代理检测未通过",
        "jp 代理检测失败",
        "代理检测未通过",
    )
    if any(marker in detail for marker in non_retryable_markers):
        return False
    retryable_markers = (
        "ba approve",
        "redirect url resolution timeout",
        "stripe submission failed",
        "submission_attempt",
        "stripe 资源 url",
        "未提取到最终 paypal",
        "paypal url",
    )
    return exc.status_code in (502, 504) or any(marker in detail for marker in retryable_markers)


def run_single_combo(
    req: LongLinkRequest,
    checkout_country: str,
    pm_country: str,
    fallback: bool,
    prior_failures: list[str],
    provider_proxy_country: str = "US",
    emit: Any | None = None,
) -> LongLinkResponse:
    def log(step: str, message: str) -> None:
        if emit:
            emit(step, message)

    checkout_country = effective_country(req)
    pm_country = effective_payment_method_country(req)
    proxy_country = (provider_proxy_country or "US").upper()
    flow_type = "paypal_de" if checkout_country == "DE" else "paypal_jp"
    log(
        "billing",
        f"当前组合：checkout账单={checkout_country}/{currency_for_country(checkout_country)}，"
        f"PM账单={pm_country}，provider代理={proxy_country}。",
    )
    log("proxy", f"检测 provider {proxy_country} 出口；checkout/approve JP 会在对应阶段检测。")
    run_req = req
    proxy_error = ""
    base_provider_proxy = provider_proxy_for_country(req, proxy_country)
    rotated = rotate_kookeey_proxy_session(base_provider_proxy, proxy_country)
    can_rotate = rotated != base_provider_proxy
    max_attempts = 5 if can_rotate else 1
    for attempt in range(1, max_attempts + 1):
        if can_rotate:
            rotated_proxy = rotate_kookeey_proxy_session(base_provider_proxy, proxy_country)
            run_req = req.model_copy(update={"us_proxy": rotated_proxy, "au_proxy": rotated_proxy})
            log("proxy", f"provider {proxy_country} 第 {attempt}/{max_attempts} 次：自动轮换粘性 session。")
        else:
            run_req = req
            if attempt == 1 and proxy_country != "US":
                log("proxy", f"provider {proxy_country} 非 Kookeey 格式，跳过轮换。")
        provider_probe = check_provider_proxy_for(run_req, proxy_country)
        if provider_probe.ok:
            break
        proxy_error = provider_probe.error or f"provider {proxy_country} 代理不可用"
        log("proxy", f"provider {proxy_country} 不可用，准备更换：{proxy_error}")
    else:
        raise HTTPException(status_code=400, detail=f"provider {proxy_country} 代理检测未通过: {proxy_error}")
    log("proxy", f"provider 代理检测通过：{format_proxy_probe_summary([provider_probe])}。")
    log("checkout", "正在使用 JP 代理创建 ChatGPT checkout。")
    run_req, chatgpt, checkout = create_checkout_with_retry(run_req, emit=log)
    log("checkout", f"checkout 创建成功：{checkout['cs_id']} / {checkout['billing_country']} / {checkout['currency']}。")

    # Fast path: checkout response may already contain the PayPal BA URL.
    checkout_url = str(checkout.get("checkout_url") or "").strip()
    if checkout_url:
        log("checkout", f"checkout 响应包含 URL：{checkout_url[:200]}")
    else:
        log("checkout", "checkout 响应未包含 PayPal URL，将走 Stripe 完整流程。")
    if is_paypal_ba_approve_url(checkout_url):
        log("done", "checkout 响应直接包含 PayPal BA approve 链，跳过 Stripe 流程！")
        return LongLinkResponse(
            ok=True,
            cs_id=checkout["cs_id"],
            processor_entity=checkout["processor_entity"],
            billing_country=checkout["billing_country"],
            payment_method_country=pm_country,
            currency=checkout["currency"],
            payment_locale=locale_parts(run_req.payment_locale)[0],
            flow_type=flow_type,
            payment_method_type="paypal",
            payment_method_id="",
            stripe_redirect_url=checkout_url,
            provider_redirect_url=checkout_url,
            fallback=fallback,
            provider_error="; ".join(prior_failures),
            stripe_hosted_url="",
            long_url=checkout_url,
        )

    stripe_key_source = (
        "手动填写"
        if run_req.stripe_publishable_key.strip()
        else ("checkout 响应" if checkout.get("stripe_publishable_key") else "内置默认")
    )
    log("stripe_init", f"Stripe key 来源：{stripe_key_source}；checkout_ui_mode=custom。")
    log("provider", f"正在切换到 provider 阶段代理：{proxy_country}。")
    provider = create_provider_link_with_retry(chatgpt, checkout, run_req, provider_country=proxy_country, emit=log)
    stripe_hosted_url = provider["stripe_hosted_url"]
    hosted_long_url = to_openai_pay_url(stripe_hosted_url)
    log("done", "PP 链提取完成。")

    return LongLinkResponse(
        ok=True,
        cs_id=checkout["cs_id"],
        processor_entity=checkout["processor_entity"],
        billing_country=checkout["billing_country"],
        payment_method_country=pm_country,
        currency=checkout["currency"],
        payment_locale=locale_parts(run_req.payment_locale)[0],
        flow_type=flow_type,
        payment_method_type="paypal",
        payment_method_id=provider["payment_method_id"],
        stripe_redirect_url=provider["stripe_redirect_url"],
        provider_redirect_url=provider["provider_redirect_url"],
        fallback=fallback,
        provider_error="; ".join(prior_failures),
        stripe_hosted_url=stripe_hosted_url,
        long_url=provider["long_url"] or hosted_long_url,
    )
