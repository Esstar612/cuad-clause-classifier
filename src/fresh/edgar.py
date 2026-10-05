"""SEC EDGAR client: full-text search (EFTS) and archive documents, at most 5 requests per second."""

from __future__ import annotations

import os
import time

import httpx
from dotenv import load_dotenv

from src.fresh import config as F


class EdgarError(RuntimeError):
    pass


class Edgar:
    def __init__(self, client: httpx.Client | None = None, sleep=time.sleep, clock=time.monotonic):
        if client is None:
            load_dotenv()
            agent = os.environ.get("SEC_USER_AGENT", "").strip()
            if not agent:
                raise SystemExit("Set SEC_USER_AGENT in .env (a name and contact email, as SEC requires)")
            client = httpx.Client(headers={"User-Agent": agent}, timeout=F.EDGAR_TIMEOUT_S)
        self.client, self.sleep, self.clock, self.last = client, sleep, clock, None

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(F.EDGAR_MAX_ATTEMPTS):
            if self.last is not None:
                self.sleep(max(0.0, F.EDGAR_MIN_INTERVAL_S - (self.clock() - self.last)))
            self.last = self.clock()
            try:
                r = self.client.get(url, params=params)
            except httpx.TransportError as e:
                error = f"transport: {type(e).__name__}"
            else:
                if r.status_code == 200:
                    return r
                error = f"HTTP {r.status_code}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            self.sleep(2 ** attempt)
        raise EdgarError(error)

    def search(self, phrase: str, start: str, end: str, offset: int = 0) -> dict:
        r = self.get(F.EFTS_URL, {"q": f'"{phrase}"', "dateRange": "custom", "startdt": start, "enddt": end,
                                  "from": offset})
        try:
            return r.json()["hits"]
        except (ValueError, KeyError) as e:
            raise EdgarError(f"unexpected EFTS response: {type(e).__name__}") from e

    def document(self, cik: str, accession: str, file_name: str) -> bytes:
        return self.get(document_url(cik, accession, file_name)).content


def document_url(cik: str, accession: str, file_name: str) -> str:
    return F.ARCHIVE_URL.format(cik=int(cik), folder=accession.replace("-", ""), file_name=file_name)
