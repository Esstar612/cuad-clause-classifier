import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src import config
from src.infer import Predictor, Scored, ServiceBudget, ServiceUpstream
from tests.test_pdf_text import _pdf

LABELS = ["Governing Law", "Insurance"]
TEXT = ("This Agreement is governed by the laws of the State of Delaware, without regard to conflicts.\n\n"
        "The Supplier shall maintain insurance with reputable insurers <script>alert(1)</script> at all times.")


def _scorer(texts):
    n = len(texts)
    proba = np.array([[0.9, 0.0]] + [[0.0, 0.3]] * (n - 1))
    unscored = np.zeros(n, dtype=bool)
    unscored[-1] = n > 1
    return Scored(proba, unscored, 1.0, 0.0)


def _raise(exc):
    def score(texts):
        raise exc
    return score


def _stub(name, score=_scorer, points=("balanced", "high_recall")):
    thr = {"balanced": {"Governing Law": 0.5, "Insurance": 0.5}, "high_recall": {"Governing Law": 0.5, "Insurance": 0.2}}
    return Predictor(name, f"{name}-v1", LABELS, {p: thr[p] for p in points}, score,
                     {"high_recall": "Below the target on validation: Insurance."})


def _loader(names):
    ok = {"stub": _stub("stub"), "fireworks-deepseek": _stub("fireworks-deepseek"),
          "budget": _stub("budget", _raise(ServiceBudget("per-request cap"))),
          "upstream": _stub("upstream", _raise(ServiceUpstream("HTTPStatusError: 401"))),
          "balanced-only": _stub("balanced-only", points=("balanced",))}
    return ok, {"broken": "SystemExit: artifacts changed since selection"}


def _app(monkeypatch, tmp_path, loader=_loader):
    from service import app as service_app

    monkeypatch.setattr(service_app, "_oov", lambda state: None)
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path)
    return service_app.create_app(loader=loader)


@pytest.fixture
def client(monkeypatch, tmp_path):
    (tmp_path / "llm_repeat_fireworks-deepseek.json").write_text(json.dumps({"all_runs_exact_agreement": 0.5}))
    with TestClient(_app(monkeypatch, tmp_path)) as c:
        yield c


def test_health_and_models(client):
    assert client.get("/health").json()["status"] == "ok"
    info = client.get("/models").json()
    assert info["served"]["fireworks-deepseek"]["repeat_agreement"] == 0.5
    assert "CUAD has been public" in info["served"]["fireworks-deepseek"]["caveat"]
    assert info["served"]["stub"]["repeat_agreement"] == "not measured"
    assert "artifacts changed" in info["unavailable"]["broken"]


def test_classify_both_operating_points(client):
    bal = client.post("/classify", json={"text": TEXT, "model": "stub"}).json()
    assert bal["segments_total"] == 2 and bal["segments_flagged"] == 1 and bal["segments_not_classified"] == 1
    assert bal["segments"][0]["labels"] == [{"label": "Governing Law", "confidence": 0.9}]
    assert any("not cleared" in n for n in bal["notices"])
    high = client.post("/classify", json={"text": TEXT, "model": "stub", "operating_point": "high_recall"}).json()
    assert "validation" in high["operating_point_note"] and "Below the target on validation: Insurance" in high[
        "operating_point_note"]
    assert "Below the target" not in bal["operating_point_note"] and "input_check" not in bal


@pytest.mark.parametrize("body,status", [({"text": TEXT, "model": "nope"}, 400),
                                         ({"text": TEXT, "model": "broken"}, 400),
                                         ({"text": TEXT, "model": "stub", "operating_point": "max"}, 400),
                                         ({"text": TEXT, "model": "balanced-only", "operating_point": "high_recall"}, 400),
                                         ({"text": "   ", "model": "stub"}, 422),
                                         ({"text": TEXT, "model": "budget"}, 402),
                                         ({"text": TEXT, "model": "upstream"}, 502)])
def test_classify_errors(client, body, status):
    assert client.post("/classify", json=body).status_code == status


def test_pdf_upload_malformed_and_oversized(client, monkeypatch):
    ok = client.post("/classify/pdf", files={"file": ("c.pdf", _pdf([TEXT[:90]]), "application/pdf")},
                     data={"model": "stub"})
    assert ok.status_code == 200 and ok.json()["extraction"]["pages"] == 1
    assert ok.json()["extraction"]["text"].startswith(TEXT[:40])
    bad = client.post("/classify/pdf", files={"file": ("c.pdf", b"not a pdf", "application/pdf")},
                      data={"model": "stub"})
    assert bad.status_code == 400
    monkeypatch.setattr(config, "SERVICE_MAX_UPLOAD_MB", 1e-6)
    big = client.post("/classify/pdf", files={"file": ("c.pdf", _pdf([TEXT[:90]]), "application/pdf")},
                      data={"model": "stub"})
    assert big.status_code == 413


def test_review_page_escapes_text_and_shows_notices(client):
    page = client.get("/").text
    assert "not cleared" in page and "sends the document text to Fireworks" in page
    out = client.post("/review", data={"text": TEXT, "model": "stub"}).text
    assert "&lt;script&gt;" in out and "<script>alert" not in out
    assert "Governing Law 0.90" in out and "not classified" in out


def test_service_settings_parse_the_environment():
    s = config.service_settings({"SERVICE_MODELS": " baseline, fireworks-deepseek ,", "SERVICE_LLM_CAP_USD": "2",
                                 "SERVICE_REQUEST_CAP_USD": "0.1", "SERVICE_MAX_UPLOAD_MB": "5"})
    assert s["models"] == ("baseline", "fireworks-deepseek") and s["llm_cap_usd"] == 2.0
    assert s["request_cap_usd"] == 0.1 and s["max_upload_mb"] == 5.0
    default = config.service_settings({})
    assert default["models"] == ("baseline", "transformer-tuned", "fireworks-deepseek")
    assert default["cors_origins"] == () and default["require_all_models"] is False
    assert default["max_text_chars"] == 1_000_000
    s = config.service_settings({"SERVICE_CORS_ORIGINS": "https://a.vercel.app, https://b.app",
                                 "SERVICE_REQUIRE_ALL_MODELS": "1", "SERVICE_MAX_TEXT_CHARS": "500"})
    assert s["cors_origins"] == ("https://a.vercel.app", "https://b.app")
    assert s["require_all_models"] is True and s["max_text_chars"] == 500


def test_input_check_reports_the_validation_percentile(monkeypatch, tmp_path):
    from scipy.stats import percentileofscore
    from sklearn.feature_extraction.text import TfidfVectorizer

    from service import app as service_app

    vectorizer = TfidfVectorizer().fit([TEXT])
    monkeypatch.setattr(service_app, "_oov", lambda state: (vectorizer, [0.0, 0.5, 1.0]))
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path)
    with TestClient(service_app.create_app(loader=_loader)) as c:
        check = c.post("/classify", json={"text": TEXT, "model": "stub"}).json()["input_check"]
    assert check["oov_rate"] == 0.0
    assert check["validation_percentile"] == pytest.approx(percentileofscore([0.0, 0.5, 1.0], 0.0))
    assert "batches of 5 contracts" in check["note"]


def test_strict_startup_refuses_a_failed_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SERVICE_REQUIRE_ALL_MODELS", True)
    with pytest.raises(RuntimeError, match="artifacts changed"):
        with TestClient(_app(monkeypatch, tmp_path)):
            pass
    with TestClient(_app(monkeypatch, tmp_path, lambda names: ({"stub": _stub("stub")}, {}))) as c:
        assert c.get("/health").json()["models"] == ["stub"]


def test_text_over_the_cap_is_refused(client, monkeypatch):
    monkeypatch.setattr(config, "SERVICE_MAX_TEXT_CHARS", 50)
    assert client.post("/classify", json={"text": TEXT, "model": "stub"}).status_code == 413
    pdf = client.post("/classify/pdf", files={"file": ("c.pdf", _pdf([TEXT[:90]]), "application/pdf")},
                      data={"model": "stub"})
    assert pdf.status_code == 413


def test_cors_allows_only_configured_origins(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SERVICE_CORS_ORIGINS", ("https://ok.vercel.app",))
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    with TestClient(_app(monkeypatch, tmp_path)) as c:
        ok = c.options("/classify", headers={"Origin": "https://ok.vercel.app", **preflight})
        other = c.options("/classify", headers={"Origin": "https://evil.example", **preflight})
        get = c.get("/models", headers={"Origin": "https://evil.example"})
    assert ok.headers["access-control-allow-origin"] == "https://ok.vercel.app"
    assert "access-control-allow-origin" not in other.headers and "access-control-allow-origin" not in get.headers
    assert "access-control-allow-credentials" not in ok.headers


def test_no_cors_headers_without_configured_origins(client):
    assert "access-control-allow-origin" not in client.get("/models", headers={"Origin": "https://x.app"}).headers


def test_models_and_page_show_only_served_models(monkeypatch, tmp_path):
    with TestClient(_app(monkeypatch, tmp_path, lambda names: ({"stub": _stub("stub")}, {}))) as c:
        info = c.get("/models").json()
        page = c.get("/").text
    assert list(info["served"]) == ["stub"] and any("not cleared" in n for n in info["notices"])
    assert "fireworks-deepseek" not in page and "Fireworks" not in page
