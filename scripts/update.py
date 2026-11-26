"""Aggiorna i dati del sito e genera _site/index.html.

Fonti:
- orario IED (iCal Cineca): sempre, non serve nessuna chiave
- Notion (materie, scadenze, avvisi, documenti, FAQ): solo se c'e' il segreto NOTION_TOKEN
Se una fonte non risponde, restano i dati dell'ultima versione di data.json.
Solo libreria standard di Python: niente da installare.
"""
import json, os, re, shutil, sys, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ROME = ZoneInfo("Europe/Rome")
ICAL_URL = "https://ied.prod.up.cineca.it/api/FiltriICal/impegniICal?id=6aed9deaf488cc0014c74dcc"
NOTION_DB = {
    "materie":   "ca968f4869cc4227ba5d61f2aa532c5b",
    "scadenze":  "706b32805135439083de95804963191d",
    "avvisi":    "be5461cd0acc4bf79a1a7effe8a902dd",
    "documenti": "92f13379a359425198821c50c13d5fb0",
    "domande":   "d5ebe4c523b547c4afc2529a74fe7ff8",
}

def get(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "full-gas-site", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

# ---------- iCal ----------
def parse_dt(value, params):
    if "VALUE=DATE" in params or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=ROME)
        return d.astimezone(timezone.utc)
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    tz = ZoneInfo(m.group(1)) if (m := re.search(r"TZID=([^;:]+)", params)) else ROME
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz).astimezone(timezone.utc)

def unescape(s):
    return s.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()

def parse_ics(text):
    text = re.sub(r"\r?\n[ \t]", "", text)  # righe spezzate
    events, cur = [], None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT": cur = {}
        elif line == "END:VEVENT":
            if cur and "DTSTART" in cur: events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, val = line.split(":", 1)
            name, _, params = head.partition(";")
            if name in ("DTSTART", "DTEND"): cur[name] = parse_dt(val, params)
            elif name in ("SUMMARY", "LOCATION", "DESCRIPTION"): cur[name] = unescape(val)
    now = datetime.now(timezone.utc)
    out = []
    for e in events:
        s = e["DTSTART"]; en = e.get("DTEND", s + timedelta(hours=1))
        if now - timedelta(days=21) <= s <= now + timedelta(days=150):
            loc = e.get("LOCATION", "")
            loc = " - ".join(loc.split(" - ")[:2])
            out.append([s.strftime("%Y-%m-%dT%H:%M:%SZ"), en.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        e.get("SUMMARY", ""), loc, e.get("DESCRIPTION", "")])
    return sorted(out)

# ---------- Notion ----------
def notion_rows(db, token):
    rows, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        res = json.loads(get(f"https://api.notion.com/v1/databases/{db}/query",
                             {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
                              "Content-Type": "application/json"}, json.dumps(body).encode()))
        rows += [{"_id": r["id"], **{k: val(v) for k, v in r["properties"].items()}} for r in res["results"]]
        if not res.get("has_more"): return rows
        cursor = res["next_cursor"]

def val(p):
    t = p["type"]
    if t in ("title", "rich_text"): return "".join(x["plain_text"] for x in p[t]).strip() or None
    if t in ("select", "status"): return (p[t] or {}).get("name")
    if t == "date": return (p["date"] or {}).get("start")
    if t in ("url", "email", "number", "checkbox"): return p[t]
    if t == "relation": return [x["id"] for x in p["relation"]]
    return None

SEM_ORDER = {"I": 0, "I/II": 1, "II": 2}

def links(t):
    out = []
    for x in lines(t):
        if "|" in x:
            label, url = (y.strip() for y in x.split("|", 1))
            if url.startswith("http"): out.append({"label": label, "url": url})
    return out

def lines(t):
    return [x.strip() for x in (t or "").splitlines() if x.strip()]

def from_notion(data, token):
    m = notion_rows(NOTION_DB["materie"], token)
    if m:
        data["subjects"] = sorted([{
            "name": r["Materia"], "key": (r.get("Sigla") or " ".join((r["Materia"] or "").upper().split()[:2])),
            "cfa": r.get("CFA") or 0, "ore": r.get("Ore") or 0, "sem": r.get("Semestre") or "",
            "tipo": r.get("Tipo") or "", "esame": r.get("Esame") or "Da verificare", "note": r.get("Note") or "",
            "moodle": r.get("Link Moodle"), "drive": r.get("Cartella Drive"), "pdf": r.get("PDF programma"),
            "docenti": r.get("Docente") or "", "obiettivi": r.get("Obiettivi") or "",
            "programma": lines(r.get("Programma")), "valutazione": r.get("Valutazione") or "",
            "bibliografia": lines(r.get("Bibliografia")), "links": links(r.get("Altri link"))} for r in m if r.get("Materia")],
            key=lambda s: (SEM_ORDER.get(s["sem"], 3), -s["cfa"], s["name"]))
    names = {r["_id"]: r["Materia"] for r in m if r.get("Materia")}
    data["deadlines"] = sorted([{"title": r["Cosa"], "date": r["Data"], "type": r.get("Tipo") or "Consegna", "url": r.get("Link"),
                          "note": r.get("Note") or "", "subject": next((names[i] for i in (r.get("Materia") or []) if i in names), None)}
                         for r in notion_rows(NOTION_DB["scadenze"], token) if r.get("Cosa") and r.get("Data")], key=lambda d: d["date"])
    data["news"] = sorted([{"date": (r.get("Data") or "")[:10], "title": r["Avviso"], "text": r.get("Testo") or "",
                            "source": r.get("Fonte") or "Classe", "important": r.get("Priorità") == "Importante" or bool(r.get("In evidenza")),
                            "url": r.get("Link")} for r in notion_rows(NOTION_DB["avvisi"], token) if r.get("Avviso") and r.get("Data")],
                          key=lambda n: n["date"], reverse=True)[:12]
    d = notion_rows(NOTION_DB["documenti"], token)
    if d:
        data["docs"] = [{"name": r["Documento"], "cat": r.get("Categoria") or "Altro", "ver": r.get("Versione") or "",
                         "note": r.get("Note") or "", "url": r.get("Link")} for r in d if r.get("Documento")]
    f = [r for r in notion_rows(NOTION_DB["domande"], token) if r.get("Domanda") and r.get("Stato") == "Risposta verificata"]
    if f:
        data["faq"] = [{"q": r["Domanda"], "a": r.get("Risposta") or "", "src": r.get("Fonte") or ""} for r in f]

# ---------- main ----------
def main():
    data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
    try:
        data["events"] = parse_ics(get(ICAL_URL)); print(f"orario: {len(data['events'])} eventi")
    except Exception as e:
        print("orario non raggiunto, tengo quello vecchio:", e, file=sys.stderr)
    token = os.environ.get("NOTION_TOKEN")
    if token:
        try:
            from_notion(data, token); print("notion: ok")
        except Exception as e:
            print("notion non raggiunto, tengo i dati vecchi:", e, file=sys.stderr)
    else:
        print("notion: nessun NOTION_TOKEN, uso data.json")
    data["generatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (ROOT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    html = (ROOT / "template.html").read_text(encoding="utf-8")
    out = ROOT / "_site"; out.mkdir(exist_ok=True)
    if (ROOT / "files").is_dir():
        shutil.copytree(ROOT / "files", out / "files", dirs_exist_ok=True)
    (out / "index.html").write_text(html.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
    print("sito generato in _site/index.html")

if __name__ == "__main__":
    main()
