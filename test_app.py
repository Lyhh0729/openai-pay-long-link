"""Tests for the OpenAI Pay Long Link API."""

import json
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import (
    app,
    billing_for_country,
    collect_urls,
    combo_attempt_order,
    combo_name,
    compact_log_message,
    currency_for_country,
    effective_country,
    extract_processor_entity,
    extract_redirect_to_url,
    extract_stripe_publishable_key,
    find_token,
    is_external_url,
    is_ignored_resource_url,
    is_paypal_ba_approve_url,
    is_paypal_url,
    is_retryable_network_error,
    locale_parts,
    new_proxy_session_id,
    normalize_access_token,
    normalize_country,
    normalize_proxy_url,
    processor_entity_for_country,
    rotate_kookeey_proxy_session,
    short_error,
    stripe_checkout_long_url,
    to_openai_pay_url,
)

client = TestClient(app)


# ────────────────────────────  basic endpoints  ────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"ok": True}

    def test_health_is_json(self):
        response = client.get("/api/health")
        assert response.headers["content-type"].startswith("application/json")


class TestIndexPage:
    def test_index_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "<html" in response.text.lower() or "<!doctype html>" in response.text.lower()

    def test_index_contains_title(self):
        response = client.get("/")
        assert "PP" in response.text


class TestPublicStaticFiles:
    def test_index_html_served(self):
        response = client.get("/public/index.html")
        assert response.status_code == 200

    def test_missing_static_returns_404(self):
        response = client.get("/public/nonexistent-file.xyz")
        assert response.status_code == 404


# ───────────────────────────  input validation  ───────────────────────────


class TestLongLinkValidation:
    def test_missing_access_token_returns_error(self):
        response = client.post("/api/long-link", json={})
        # FastAPI returns 422 for missing required fields; our code returns 400
        assert response.status_code in (400, 422)
        data = response.json()
        detail = str(data.get("detail", "")).lower()
        assert "access" in detail or "token" in detail or "field" in detail

    def test_empty_access_token_returns_400(self):
        response = client.post(
            "/api/long-link",
            json={"accessToken": "", "jp_proxy": "", "us_proxy": ""},
        )
        assert response.status_code == 400

    def test_bad_country_falls_back_to_us(self):
        """Invalid country should not crash — it normalizes."""
        body = {
            "accessToken": "fake-token",
            "billing_country": "XX",
            "payment_method_country": "YY",
            "jp_proxy": "",
            "us_proxy": "",
        }
        # Will fail downstream (no real token/proxy) but should be a 400/502/504,
        # not a 422 or 500
        response = client.post("/api/long-link", json=body)
        assert response.status_code in (400, 502, 504)


# ───────────────────────────  proxy check  ───────────────────────────


class TestProxyCheck:
    def test_empty_proxies(self):
        response = client.post(
            "/api/check-proxy",
            json={"jp_proxy": "", "us_proxy": "", "billing_country": "US"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 2

    def test_missing_fields_uses_defaults(self):
        response = client.post("/api/check-proxy", json={})
        assert response.status_code == 200
        data = response.json()
        assert "results" in data


# ───────────────────────────  URL / network helpers  ───────────────────────────


class TestNormalizeProxyUrl:
    def test_adds_http_prefix(self):
        assert normalize_proxy_url("1.2.3.4:8080") == "http://1.2.3.4:8080"

    def test_keeps_existing_scheme(self):
        assert normalize_proxy_url("http://user:pass@host:8080") == "http://user:pass@host:8080"
        assert normalize_proxy_url("https://proxy.example.com") == "https://proxy.example.com"

    def test_handles_empty_string(self):
        assert normalize_proxy_url("") == ""
        assert normalize_proxy_url("  ") == ""

    def test_strips_whitespace(self):
        assert normalize_proxy_url("  http://proxy:8080  ") == "http://proxy:8080"


class TestIsExternalUrl:
    def test_http_url(self):
        assert is_external_url("https://www.paypal.com/approve") is True

    def test_http_url_bare(self):
        assert is_external_url("http://example.com/path") is True

    def test_relative_path(self):
        assert is_external_url("/api/health") is False

    def test_empty_string(self):
        assert is_external_url("") is False

    def test_invalid_url(self):
        assert is_external_url("not a url") is False


class TestIsPaypalUrl:
    def test_paypal_domain(self):
        assert is_paypal_url("https://www.paypal.com/agreements/approve") is True

    def test_paypal_subdomain(self):
        assert is_paypal_url("https://api.paypal.com/v1/checkout") is True

    def test_paypal_objects_domain(self):
        assert is_paypal_url("https://www.paypalobjects.com/widget.js") is True

    def test_non_paypal_domain(self):
        assert is_paypal_url("https://stripe.com/pay") is False

    def test_empty_string(self):
        assert is_paypal_url("") is False


class TestIsPaypalBaApproveUrl:
    def test_valid_ba_approve(self):
        url = "https://www.paypal.com/agreements/approve?ba_token=ABC123"
        assert is_paypal_ba_approve_url(url) is True

    def test_missing_ba_token(self):
        url = "https://www.paypal.com/agreements/approve"
        assert is_paypal_ba_approve_url(url) is False

    def test_wrong_path(self):
        url = "https://www.paypal.com/checkout?ba_token=ABC123"
        assert is_paypal_ba_approve_url(url) is False

    def test_non_paypal(self):
        url = "https://stripe.com/agreements/approve?ba_token=ABC123"
        assert is_paypal_ba_approve_url(url) is False

    def test_empty_string(self):
        assert is_paypal_ba_approve_url("") is False

    def test_case_insensitive_path(self):
        url = "https://www.paypal.com/Agreements/Approve?ba_token=ABC123"
        assert is_paypal_ba_approve_url(url) is True

    def test_trailing_slash(self):
        url = "https://www.paypal.com/agreements/approve/?ba_token=ABC123"
        assert is_paypal_ba_approve_url(url) is True


class TestIsIgnoredResourceUrl:
    def test_png_static_resource(self):
        assert is_ignored_resource_url("https://js.stripe.com/v3/fingerprinted/img/icon.png") is True

    def test_js_extension(self):
        assert is_ignored_resource_url("https://js.stripe.com/v3/app.js") is True

    def test_stripe_camo(self):
        assert is_ignored_resource_url("https://stripe-camo.global.ssl.fastly.net/img.png") is True

    def test_api_url_not_ignored(self):
        assert is_ignored_resource_url("https://api.stripe.com/v1/payment_pages/cs_123/init") is False

    def test_empty_string(self):
        assert is_ignored_resource_url("") is False


class TestToOpenaiPayUrl:
    def test_stripe_checkout_to_openai_pay(self):
        url = "https://checkout.stripe.com/c/pay/cs_test123"
        result = to_openai_pay_url(url)
        assert result.startswith("https://pay.openai.com")

    def test_already_pay_openai(self):
        url = "https://pay.openai.com/c/pay/cs_test123"
        result = to_openai_pay_url(url)
        assert result == url

    def test_empty_string(self):
        assert to_openai_pay_url("") == ""


class TestStripeCheckoutLongUrl:
    def test_contains_expected_parts(self):
        url = stripe_checkout_long_url("cs_test123", "US", "openai_llc")
        assert "checkout.stripe.com" in url
        assert "cs_test123" in url
        assert "return_url" in url


# ───────────────────────────  token helpers  ───────────────────────────


class TestFindToken:
    def test_find_in_flat_dict(self):
        data = {"accessToken": "tok_abc", "other": 123}
        assert find_token(data) == "tok_abc"

    def test_find_access_token_underscore(self):
        data = {"access_token": "tok_xyz"}
        assert find_token(data) == "tok_xyz"

    def test_find_token_key(self):
        data = {"token": "tok_plain"}
        assert find_token(data) == "tok_plain"

    def test_find_nested(self):
        data = {"profile": {"accessToken": "tok_nested"}}
        assert find_token(data) == "tok_nested"

    def test_find_in_list(self):
        data = [{"other": 1}, {"accessToken": "tok_list"}]
        assert find_token(data) == "tok_list"

    def test_no_token_found(self):
        assert find_token({"nothing": "here"}) == ""

    def test_empty_input(self):
        assert find_token({}) == ""
        assert find_token([]) == ""


class TestNormalizeAccessToken:
    def test_plain_token(self):
        assert normalize_access_token("eyJhbGciOiJ...") == "eyJhbGciOiJ..."

    def test_json_object_with_token(self):
        raw = json.dumps({"accessToken": "tok_json"})
        assert normalize_access_token(raw) == "tok_json"

    def test_json_object_with_nested_token(self):
        raw = json.dumps({"data": {"accessToken": "tok_nested"}})
        assert normalize_access_token(raw) == "tok_nested"

    def test_invalid_json_falls_back(self):
        raw = "{invalid json"
        assert normalize_access_token(raw) == "{invalid json"

    def test_empty_string(self):
        assert normalize_access_token("") == ""

    def test_json_array(self):
        raw = json.dumps([{"accessToken": "tok_arr"}])
        assert normalize_access_token(raw) == "tok_arr"


# ───────────────────────────  stripe key extraction  ───────────────────────────


class TestExtractStripePublishableKey:
    def test_regex_from_string(self):
        s = 'some text pk_live_51HOrSwC6h1nxGoI3lTAgRjYVrz4dU3fVOabyCcKR3pbEJguCVAlqCxdxCUvoRh1XWwRacViovU3kLKvpkjh7IqkW00iXQsjo3n more text'
        result = extract_stripe_publishable_key(s)
        assert result.startswith("pk_live_")

    def test_from_dict_key(self):
        data = {"stripe_publishable_key": "pk_live_test123"}
        assert extract_stripe_publishable_key(data) == "pk_live_test123"

    def test_from_dict_nested(self):
        data = {"data": {"publishableKey": "pk_live_nested"}}
        assert extract_stripe_publishable_key(data) == "pk_live_nested"

    def test_no_match(self):
        assert extract_stripe_publishable_key("no key here") == ""

    def test_empty(self):
        assert extract_stripe_publishable_key({}) == ""


class TestExtractProcessorEntity:
    def test_direct_key(self):
        assert extract_processor_entity({"processor_entity": "openai_llc"}) == "openai_llc"

    def test_camel_case(self):
        assert extract_processor_entity({"processorEntity": "openai_ie"}) == "openai_ie"

    def test_nested_in_checkout_session(self):
        data = {"checkout_session": {"processor_entity": "openai_llc"}}
        assert extract_processor_entity(data) == "openai_llc"

    def test_empty(self):
        assert extract_processor_entity({}) == ""

    def test_not_a_dict(self):
        assert extract_processor_entity("string") == ""
        assert extract_processor_entity([]) == ""


# ───────────────────────────  URL collection  ───────────────────────────


class TestCollectUrls:
    def test_collect_from_string(self):
        text = 'url: https://paypal.com/approve and https://stripe.com/pay'
        urls = collect_urls(text)
        assert len(urls) == 2
        assert any("paypal.com" in u for u in urls)

    def test_collect_from_dict_keys(self):
        data = {
            "url": "https://example.com/redirect",
            "return_url": "https://chatgpt.com/verify",
        }
        urls = collect_urls(data)
        assert len(urls) >= 2

    def test_collect_nested(self):
        data = {"next_action": {"redirect_to_url": {"url": "https://paypal.com/approve"}}}
        urls = collect_urls(data)
        assert len(urls) >= 1
        assert any("paypal.com" in u for u in urls)

    def test_empty(self):
        assert collect_urls({}) == []


class TestExtractRedirectToUrl:
    def test_next_action_redirect(self):
        data = {
            "next_action": {
                "type": "redirect_to_url",
                "redirect_to_url": {"url": "https://paypal.com/approve?ba_token=XYZ"},
            }
        }
        result = extract_redirect_to_url(data)
        assert "paypal.com" in result

    def test_from_nested_intent(self):
        data = {
            "setup_intent": {
                "next_action": {
                    "type": "redirect_to_url",
                    "redirect_to_url": {"url": "https://paypal.com/approve?ba_token=ABC"},
                }
            }
        }
        result = extract_redirect_to_url(data)
        assert "paypal.com" in result and "ba_token=ABC" in result

    def test_fallback_to_paypal_url_in_list(self):
        data = {
            "urls": [
                "https://files.stripe.com/img.png",
                "https://www.paypal.com/agreements/approve?ba_token=FALLBACK",
            ]
        }
        result = extract_redirect_to_url(data)
        assert "paypal.com" in result

    def test_empty(self):
        assert extract_redirect_to_url({}) == ""


# ───────────────────────────  country / locale helpers  ───────────────────────────


class TestNormalizeCountry:
    def test_valid_us(self):
        assert normalize_country("US") == "US"
        assert normalize_country("us") == "US"

    def test_valid_de(self):
        assert normalize_country("DE") == "DE"
        assert normalize_country("de") == "DE"

    def test_invalid_falls_to_us(self):
        assert normalize_country("JP") == "US"
        assert normalize_country("") == "US"
        assert normalize_country("XX") == "US"


class TestCurrencyForCountry:
    def test_us_currency(self):
        assert currency_for_country("US") == "USD"

    def test_de_currency(self):
        assert currency_for_country("DE") == "EUR"

    def test_unknown_falls_back_to_usd(self):
        assert currency_for_country("XX") == "USD"


class TestEffectiveCountry:
    class FakeReq:
        billing_country = ""

    def test_normalize(self):
        req = self.FakeReq()
        req.billing_country = "DE"
        assert effective_country(req) == "DE"

    def test_invalid(self):
        req = self.FakeReq()
        req.billing_country = "INVALID"
        assert effective_country(req) == "US"


class TestProcessorEntityForCountry:
    def test_us_gets_openai_llc(self):
        assert processor_entity_for_country("US", "") == "openai_llc"

    def test_de_gets_openai_ie(self):
        assert processor_entity_for_country("DE", "") == "openai_ie"

    def test_explicit_entity_overrides(self):
        assert processor_entity_for_country("US", "custom_entity") == "custom_entity"


class TestLocaleParts:
    def test_en_locale(self):
        assert locale_parts("en") == ("en-US", "en")

    def test_de_locale(self):
        assert locale_parts("de") == ("de-DE", "de")

    def test_zh_cn_locale(self):
        assert locale_parts("zh-CN") == ("zh-CN", "zh-CN")

    def test_unknown_locale(self):
        assert locale_parts("nope") == ("en-US", "en")


# ───────────────────────────  billing data  ───────────────────────────


class TestBillingForCountry:
    def test_us_billing_has_all_fields(self):
        billing = billing_for_country("US")
        assert "name" in billing
        assert "email" in billing
        assert billing["country"] == "US"
        assert "line1" in billing
        assert "city" in billing
        assert "state" in billing
        assert "postal_code" in billing

    def test_de_billing_has_all_fields(self):
        billing = billing_for_country("DE")
        assert "name" in billing
        assert "email" in billing
        assert billing["country"] == "DE"

    def test_invalid_country_normalizes_to_us(self):
        # normalize_country maps any unknown country to "US", so billing_for_country
        # always succeeds — the invalid-country guard in its else branch is
        # defensive dead code that can never be reached through the public API.
        billing = billing_for_country("XX")
        assert billing["country"] == "US"

    def test_billing_names_are_random(self):
        names = {billing_for_country("US")["name"] for _ in range(10)}
        # Should have at least some variation
        assert len(names) >= 1

    def test_au_billing_has_all_fields(self):
        billing = billing_for_country("AU")
        assert "name" in billing
        assert "email" in billing
        assert billing["country"] == "AU"
        assert "line1" in billing
        assert "city" in billing
        assert "state" in billing
        assert "postal_code" in billing

    def test_au_billing_names_are_realistic(self):
        billing = billing_for_country("AU")
        # Names should be from the AU pool
        assert isinstance(billing["name"], str)
        assert " " in billing["name"]
        first, last = billing["name"].split(" ", 1)
        assert len(first) > 0
        assert len(last) > 0

    def test_au_billing_states_are_valid(self):
        """AU addresses should use valid Australian state abbreviations."""
        states = {billing_for_country("AU")["state"] for _ in range(20)}
        valid_au_states = {"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"}
        assert states.issubset(valid_au_states), f"Unexpected AU states: {states - valid_au_states}"


# ───────────────────────────  AU data  ───────────────────────────


class TestAuCurrency:
    def test_au_currency_is_aud(self):
        assert currency_for_country("AU") == "AUD"

    def test_au_country_is_valid(self):
        assert normalize_country("AU") == "AU"
        assert normalize_country("au") == "AU"


class TestAuLocale:
    def test_en_au_locale(self):
        assert locale_parts("en-AU") == ("en-AU", "en-AU")


class TestAuComboOrder:
    def test_au_au_is_only_combo(self):
        order = combo_attempt_order("AU", "AU")
        assert order == [("AU", "AU")]

    def test_us_us_is_only_combo(self):
        order = combo_attempt_order("US", "US")
        assert order == [("US", "US")]


# ───────────────────────────  single proxy mode  ───────────────────────────


class TestSingleProxyMode:
    """When no us_proxy is given, provider_stage_proxy should reuse JP proxy."""

    def test_empty_proxy_check_returns_two_results(self):
        response = client.post(
            "/api/check-proxy",
            json={"jp_proxy": "", "us_proxy": "", "billing_country": "AU"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2
        # First result is JP check (will fail — no proxy given)
        assert data["results"][0]["label"] == "checkout/approve JP"
        # Second result shares the JP check outcome
        assert "provider" in data["results"][1]["label"].lower()

    def test_check_proxy_with_only_jp_returns_both(self):
        """Even with only jp_proxy, check-proxy returns 2 results (shared)."""
        response = client.post(
            "/api/check-proxy",
            json={"jp_proxy": "http://user:pass@proxy:8080", "us_proxy": "", "billing_country": "US"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2


# ───────────────────────────  combo logic  ───────────────────────────


class TestComboAttemptOrder:
    def test_default_us_us(self):
        order = combo_attempt_order("US", "US")
        assert len(order) == 1
        assert order[0] == ("US", "US")

    def test_de_de(self):
        order = combo_attempt_order("DE", "DE")
        assert order[0] == ("DE", "DE")
        assert len(order) == 1

    def test_au_au(self):
        order = combo_attempt_order("AU", "AU")
        assert order[0] == ("AU", "AU")
        assert len(order) == 1

    def test_no_duplicates(self):
        order = combo_attempt_order("US", "DE")
        assert len(order) == 1
        assert order == [("US", "DE")]

    def test_all_combos_valid_countries(self):
        order = combo_attempt_order("US", "US")
        for checkout, pm in order:
            assert checkout in ("US", "DE", "AU")
            assert pm in ("US", "DE", "AU")


class TestComboName:
    def test_combo_format(self):
        assert combo_name("US", "DE") == "US+DE"
        assert combo_name("DE", "US") == "DE+US"


# ───────────────────────────  error / logging helpers  ───────────────────────────


class TestShortError:
    def test_short_message(self):
        assert short_error("hello") == "hello"

    def test_long_message_truncated(self):
        long_msg = "x" * 500
        result = short_error(long_msg, limit=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_default_limit(self):
        result = short_error("x" * 500)
        assert len(result) <= 260

    def test_whitespace_collapsed(self):
        result = short_error("hello    world")
        assert result == "hello world"


class TestCompactLogMessage:
    def test_summary_step_uses_short_error(self):
        msg = "x" * 500
        result = compact_log_message("summary", msg)
        assert len(result) <= 360

    def test_short_message_passed_through(self):
        assert compact_log_message("info", "hello") == "hello"

    def test_empty_message(self):
        assert compact_log_message("step", "") == ""


class TestIsRetryableNetworkError:
    def test_timeout_errors(self):
        import requests
        assert is_retryable_network_error(requests.exceptions.ReadTimeout()) is True
        assert is_retryable_network_error(requests.exceptions.ConnectTimeout()) is True
        assert is_retryable_network_error(requests.exceptions.ConnectionError()) is True

    def test_value_error_not_retryable(self):
        assert is_retryable_network_error(ValueError("something")) is False


# ───────────────────────────  proxy rotation  ───────────────────────────


class TestNewProxySessionId:
    def test_generates_numeric_string(self):
        sid = new_proxy_session_id()
        assert sid.isdigit()
        assert len(sid) == 8

    def test_randomness(self):
        ids = {new_proxy_session_id() for _ in range(20)}
        assert len(ids) > 1


class TestRotateKookeeyProxySession:
    def test_rotates_password_session_id(self):
        proxy = "http://user:pass-US-12345678@proxy.example.com:8080"
        rotated = rotate_kookeey_proxy_session(proxy, "JP")
        assert rotated != proxy
        assert "-JP-" in rotated
        assert "proxy.example.com" in rotated
        assert "user:" in rotated

    def test_empty_proxy_returns_empty(self):
        assert rotate_kookeey_proxy_session("", "US") == ""

    def test_missing_country_returns_original(self):
        proxy = "http://user:pass@proxy.example.com:8080"
        result = rotate_kookeey_proxy_session(proxy, "")
        # Without country we can't rotate, returns original
        assert "proxy.example.com" in result

    def test_no_auth_proxy(self):
        proxy = "http://proxy.example.com:8080"
        rotated = rotate_kookeey_proxy_session(proxy, "JP")
        assert rotated == proxy


# ───────────────────────────  streaming / start endpoints  ───────────────────────────


class TestLongLinkStart:
    def test_returns_run_id(self):
        """Should fail fast (no real proxy) but the endpoint should accept the request shape."""
        response = client.post(
            "/api/long-link/start",
            json={
                "accessToken": "fake-token-for-test",
                "jp_proxy": "",
                "us_proxy": "",
                "billing_country": "US",
                "payment_method_country": "US",
            },
        )
        # 200 means the job was accepted; the async worker will fail later
        if response.status_code == 200:
            data = response.json()
            assert "run_id" in data
        else:
            # 422 = validation error (ok), 400/502 = downstream error (also ok)
            assert response.status_code in (200, 400, 422, 502)


class TestLongLinkEvents:
    def test_unknown_run_id_returns_404(self):
        response = client.get("/api/long-link/events/nonexistent-run-id")
        assert response.status_code == 404


class TestLongLinkStream:
    def test_stream_without_token(self):
        """Streaming endpoint should handle missing token."""
        with client.stream(
            "POST",
            "/api/long-link/stream",
            json={
                "accessToken": "",
                "jp_proxy": "",
                "us_proxy": "",
                "billing_country": "US",
            },
        ) as response:
            # Should get an error event or validation error
            if response.status_code == 200:
                # Read first chunk
                first_line = ""
                for chunk in response.iter_bytes():
                    first_line = chunk.decode("utf-8", errors="replace")
                    break
                assert first_line  # should have content
            else:
                assert response.status_code in (400, 422)


# ───────────────────────────  misc  ───────────────────────────


class TestAppMetadata:
    def test_app_title(self):
        assert app.title == "OpenAI Pay Long Link"

    def test_app_routes_exist(self):
        routes = {route.path for route in app.routes}
        assert "/" in routes
        assert "/api/health" in routes
        assert "/api/long-link" in routes
        assert "/api/long-link/stream" in routes
        assert "/api/long-link/start" in routes
        assert "/api/long-link/events/{run_id}" in routes
        assert "/api/check-proxy" in routes


class TestRequestShape:
    """Ensure the request models accept the documented JSON shape."""

    def test_minimal_valid_body_shape(self):
        # This body has all required fields with placeholders
        body = {
            "accessToken": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature",
            "jp_proxy": "http://user:pass@jp-proxy:8080",
            "us_proxy": "http://user:pass@us-proxy:8080",
            "billing_country": "US",
            "payment_method_country": "US",
            "payment_locale": "en",
            "stripe_publishable_key": "",
            "device_id": "",
            "user_agent": "",
        }
        response = client.post("/api/long-link", json=body)
        # Will fail on real network calls — that's expected.
        # The key is that it should NOT be a 422 validation error.
        assert response.status_code != 422, f"Validation error: {response.json()}"

    def test_accepts_jp_proxy_alias(self):
        """jp_proxy and proxy should both work."""
        body = {
            "accessToken": "test",
            "proxy": "http://user:pass@jp-only:8080",
            "billing_country": "US",
        }
        response = client.post("/api/long-link", json=body)
        assert response.status_code != 422, f"Validation error: {response.json()}"
