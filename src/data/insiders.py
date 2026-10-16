"""
Compras de directivos (SEC Form 4) para H3 — ver DECISIONS.md, "PRE-REGISTRO H3".

Fuentes (gratis, sin clave; la SEC exige User-Agent y ≤ 10 peticiones/s):
  - Histórico: "Insider Transactions Data Sets", un zip por trimestre desde 2006T1
    (SUBMISSION + REPORTINGOWNER + NONDERIV_TRANS). Se publica con unas semanas de retraso.
  - Reciente (lo que aún no está en un trimestre publicado): índice diario de EDGAR
    + el XML de cada Form 4 (`fetch_recent`).

Tabla normalizada (una fila por operación y directivo):
    accession, filed, issuer_cik, owner_cik, trans_date, code (P/S), shares, price
"""
from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests
from pandas.tseries.offsets import BDay

from src.data.fundamentals import SEC_UA

INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
DAILY_IDX = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{d}.idx"
REQUEST_PAUSE = 0.15

ROLES = ("Director", "Officer")            # "TenPercentOwner" u "Other" solos no cuentan
WINDOW = 21                                # sesiones en que una compra cuenta para la puntuación
COLS = ["accession", "filed", "issuer_cik", "owner_cik", "trans_date", "code", "shares", "price"]


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": SEC_UA}, timeout=kw.pop("timeout", 120), **kw)
    r.raise_for_status()
    time.sleep(REQUEST_PAUSE)
    return r


def quarter_urls() -> dict[str, str]:
    """{'2016q1': url, ...} de todos los trimestres publicados."""
    links = re.findall(r'href="([^"]+/(\d{4}q\d)_form345\.zip)"', _get(INDEX_URL).text)
    return {q: "https://www.sec.gov" + u if u.startswith("/") else u for u, q in sorted(set(links), key=lambda x: x[1])}


def _date(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    miss = d.isna() & s.notna()
    if miss.any():
        d[miss] = pd.to_datetime(s[miss], errors="coerce")
    return d


def parse_quarter(content: bytes, ciks: set[int]) -> pd.DataFrame:
    """Operaciones P/S de Form 4 (no enmiendas) de directivos de los emisores `ciks`."""
    z = zipfile.ZipFile(io.BytesIO(content))

    def tsv(name, cols):
        with z.open(name) as f:
            return pd.read_csv(f, sep="\t", dtype=str, usecols=cols, quoting=3,
                               encoding="latin-1", on_bad_lines="skip")

    sub = tsv("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"])
    sub = sub[sub["DOCUMENT_TYPE"].str.strip() == "4"]
    sub["issuer_cik"] = pd.to_numeric(sub["ISSUERCIK"], errors="coerce")
    sub = sub[sub["issuer_cik"].isin(ciks)]

    own = tsv("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
    rel = own["RPTOWNER_RELATIONSHIP"].fillna("")
    own = own[rel.str.contains("|".join(ROLES), regex=True)]

    tr = tsv("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                     "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"])
    tr = tr[((tr["TRANS_CODE"] == "P") & (tr["TRANS_ACQUIRED_DISP_CD"] == "A"))
            | ((tr["TRANS_CODE"] == "S") & (tr["TRANS_ACQUIRED_DISP_CD"] == "D"))]

    df = (tr.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER"))
    out = pd.DataFrame({
        "accession":  df["ACCESSION_NUMBER"],
        "filed":      _date(df["FILING_DATE"]),
        "issuer_cik": df["issuer_cik"].astype("int64"),
        "owner_cik":  pd.to_numeric(df["RPTOWNERCIK"], errors="coerce"),
        "trans_date": _date(df["TRANS_DATE"]),
        "code":       df["TRANS_CODE"],
        "shares":     pd.to_numeric(df["TRANS_SHARES"], errors="coerce"),
        "price":      pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce"),
    })
    return out.dropna(subset=["filed", "owner_cik", "trans_date"]).astype({"owner_cik": "int64"})


def download_quarters(ciks: set[int], cache_dir: Path, until: str | None = None,
                      progress: Callable[[str], None] = print, after: str | None = None) -> pd.DataFrame:
    """Descarga (con caché de zips) y une los trimestres de (`after`, `until`], p. ej. '2026q3'."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for q, url in quarter_urls().items():
        if (until and q > until) or (after and q <= after):
            continue
        f = cache_dir / f"{q}_form345.zip"
        if not f.exists():
            f.write_bytes(_get(url, timeout=300).content)
        part = parse_quarter(f.read_bytes(), ciks)
        part.to_parquet(cache_dir / f"{q}_universo.parquet")      # para la cartera de hoy
        parts.append(part)
        progress(f"{q}: {len(part)} operaciones de directivos del universo")
    return pd.concat(parts, ignore_index=True)[COLS] if parts else pd.DataFrame(columns=COLS)


# ── Form 4 recientes (lo que aún no está en un trimestre publicado) ──────────

def _parse_form4_xml(xml: str, accession: str, filed: pd.Timestamp) -> list[dict]:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    if (root.findtext("documentType") or "").strip() != "4":
        return []
    issuer = int(root.findtext("issuer/issuerCik"))
    owners = []
    for o in root.findall("reportingOwner"):
        r = o.find("reportingOwnerRelationship")
        flags = {t: (r.findtext(t) or "").strip().lower() in ("1", "true") for t in ("isDirector", "isOfficer")} if r is not None else {}
        if any(flags.values()):
            owners.append(int(o.findtext("reportingOwnerId/rptOwnerCik")))
    rows = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = (t.findtext("transactionCoding/transactionCode") or "").strip()
        ad = (t.findtext("transactionAmounts/transactionAcquiredDisposedCode/value") or "").strip()
        if not ((code == "P" and ad == "A") or (code == "S" and ad == "D")):
            continue
        for oc in owners:
            rows.append({
                "accession": accession, "filed": filed, "issuer_cik": issuer, "owner_cik": oc,
                "trans_date": pd.to_datetime((t.findtext("transactionDate/value") or "")[:10], errors="coerce"),
                "code": code,
                "shares": pd.to_numeric(t.findtext("transactionAmounts/transactionShares/value"), errors="coerce"),
                "price": pd.to_numeric(t.findtext("transactionAmounts/transactionPricePerShare/value"), errors="coerce"),
            })
    return rows


def fetch_recent(ciks: set[int], since: pd.Timestamp, until: pd.Timestamp | None = None,
                 progress: Callable[[str], None] = print, cache_dir: Path | None = None) -> pd.DataFrame:
    """Form 4 presentadas en [since, until] leyendo el índice diario de EDGAR y cada XML.
    Con `cache_dir`, cada día ya cerrado se guarda y no se vuelve a pedir."""
    until = until or pd.Timestamp.today().normalize()
    today = pd.Timestamp.today().normalize()
    out = []
    for day in pd.bdate_range(since, until):
        cf = cache_dir / f"{day:%Y%m%d}.parquet" if cache_dir else None
        if cf is not None and cf.exists():
            out.append(pd.read_parquet(cf))
            continue
        rows = []
        url = DAILY_IDX.format(y=day.year, q=(day.month - 1) // 3 + 1, d=day.strftime("%Y%m%d"))
        try:
            idx = _get(url, timeout=60).text
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue                                # festivo o aún no publicado
            raise
        n = 0
        for line in idx.splitlines():
            if not line.startswith("4 "):
                continue
            parts = re.split(r"\s{2,}", line.strip())
            cik, path = int(parts[-3]), parts[-1]
            if cik not in ciks:                          # el índice lista emisor y declarante
                continue
            txt = _get("https://www.sec.gov/Archives/" + path, timeout=60).text
            m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", txt, re.S)
            if m:
                acc = Path(path).stem
                got = _parse_form4_xml(m.group(0), acc, day)
                rows += [r for r in got if r["issuer_cik"] in ciks]
                n += 1
        progress(f"{day.date()}: {n} Form 4 del universo")
        day_df = pd.DataFrame(rows, columns=COLS)
        if cf is not None and day < today:                  # el día de hoy aún puede crecer
            cache_dir.mkdir(parents=True, exist_ok=True)
            day_df.to_parquet(cf)
        out.append(day_df)
    out = [d for d in out if not d.empty]
    return pd.concat(out, ignore_index=True).drop_duplicates() if out else pd.DataFrame(columns=COLS)


# ── Señal ────────────────────────────────────────────────────────────────────

def opportunistic_purchases(trades: pd.DataFrame) -> pd.DataFrame:
    """Compras (P) no rutinarias: rutinaria = el directivo operó (P o S) en ese mismo mes
    natural en cada uno de los 3 años anteriores (Cohen, Malloy y Pomorski 2012, adaptado)."""
    t = trades.drop_duplicates(subset=["accession", "owner_cik", "trans_date", "code", "shares", "price"])
    ym = set(zip(t["issuer_cik"], t["owner_cik"], t["trans_date"].dt.year, t["trans_date"].dt.month))
    buys = t[(t["code"] == "P") & (t["shares"] > 0) & (t["price"] > 0)].copy()
    y, m = buys["trans_date"].dt.year, buys["trans_date"].dt.month
    routine = np.ones(len(buys), dtype=bool)
    for k in (1, 2, 3):
        routine &= np.array([(i, o, yy - k, mm) in ym for i, o, yy, mm
                             in zip(buys["issuer_cik"], buys["owner_cik"], y, m)], dtype=bool)
    buys["routine"] = routine
    buys["available"] = (buys["filed"] + BDay(1)).dt.normalize()
    buys["value"] = buys["shares"] * buys["price"]
    return buys[~buys["routine"]]


def insider_score(buys: pd.DataFrame, dates: pd.DatetimeIndex, window: int = WINDOW) -> pd.Series:
    """Puntuación en cada fecha: nº de directivos distintos con compra oportunista conocida
    en las últimas `window` sesiones + importe total / 1e12 (desempate). 0 si no hay."""
    days = pd.DatetimeIndex(dates).tz_localize(None).normalize() if dates.tz is not None else pd.DatetimeIndex(dates).normalize()
    score = np.zeros(len(days))
    if buys.empty:
        return pd.Series(score, index=dates)
    pos = np.searchsorted(days.values, buys["available"].values.astype("datetime64[ns]"), side="left")
    owners: dict[int, set] = {}
    value = np.zeros(len(days))
    for p, o, v in zip(pos, buys["owner_cik"], buys["value"]):
        for i in range(p, min(p + window, len(days))):
            owners.setdefault(i, set()).add(o)
            value[i] += v
    for i, s in owners.items():
        score[i] = len(s) + value[i] / 1e12
    return pd.Series(score, index=dates)
