"""Refresh ECHO grant data for the dashboard.

Pulls every DG ECHO grant under the last three HIP years from ECHO's IATI
publication (via d-portal.org) and the HIP budgets from DG ECHO's HIP pages,
then writes data/grants.json, data/hip_totals.json and data/meta.json.
"""
import datetime, json, re, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "echo-partners-dashboard (GitHub Action)"}
DPORTAL = "https://d-portal.org/q"
HIP_PAGE = "https://civil-protection-humanitarian-aid.ec.europa.eu/funding-evaluations/funding-humanitarian-aid/financing-decisions-hips{suffix}_en"

HIPNAME = {"-AF": "West and Central Africa", "-HF": "Greater Horn of Africa", "COD": "Great Lakes",
    "-AS": "Afghanistan, Pakistan, Iran", "-AM": "Latin America and Caribbean", "-NF": "North Africa",
    "PSE": "Palestine", "-RN": "Regional – Protect Aid Workers", "RLF": "ReliefEU",
    "-XA": "South, East, SE Asia and Pacific", "-SF": "Southern Africa and Indian Ocean",
    "SSC": "Strategic supply chain", "ERC": "Strategic Priorities / Enhanced Response Capacity",
    "SYR": "Syria regional and Lebanon", "TUR": "Türkiye, Caucasus, C. Asia, Balkans",
    "UKR": "Ukraine and Moldova", "YEM": "Yemen", "IRQ": "Iraq", "DRF": "Emergency Toolbox",
    "HRC": "European Humanitarian Response Capacity"}

FAMILIES = [
    (r"comite international de la croix|international committee of the red cross|\bcicr\b|\bicrc\b", "ICRC"),
    (r"r[oø]de kors|rotes kreuz|cruz roja|croce rossa|punainen risti|rode kruis|red cross|croix[- ]rouge|crveni|czerwony|röda korset|ifrc|federation internationale des societes", "Red Cross / Red Crescent"),
    (r"contre la faim|contra el hambre|action against hunger|azione contro la fame", "Action Against Hunger"),
    (r"save the children|rädda barnen|redd barna|pelastakaa lapset|red barnet", "Save the Children"),
    (r"oxfam", "Oxfam"), (r"international rescue committee", "IRC"), (r"\bcare\b", "CARE"),
    (r"world vision", "World Vision"), (r"welthungerhilfe", "Welthungerhilfe"),
    (r"m[eé]decins du monde|m[eé]dicos del mundo", "Médecins du Monde"), (r"m[eé]decins sans fronti[eè]res", "MSF"),
    (r"norwegian refugee", "NRC"), (r"dansk flygtninge|danish refugee", "DRC (Danish Refugee Council)"),
    (r"plan international", "Plan International"), (r"handicap international|humanity (&|and) inclusion", "Humanity & Inclusion"),
    (r"cesvi", "CESVI"), (r"intersos", "INTERSOS"), (r"\bacted\b", "ACTED"), (r"solidarit[eé]s international", "Solidarités International"),
    (r"premi[eè]re urgence", "Première Urgence Internationale"), (r"alliance for international medical action|\balima\b", "ALIMA"),
    (r"mercy corps", "Mercy Corps"), (r"concern worldwide", "Concern Worldwide"), (r"\bgoal\b", "GOAL"),
    (r"christian aid", "Christian Aid"), (r"terre des hommes", "Terre des Hommes"), (r"cooperazione internazionale|\bcoopi\b", "COOPI"),
    (r"caritas", "Caritas"), (r"malteser", "Malteser"), (r"medicinski zbor|international medical corps", "International Medical Corps"),
    (r"world food prog", "WFP"), (r"unicef|children's fund", "UNICEF"), (r"high commissioner for refugees|unhcr", "UNHCR"),
    (r"organization for migration|\biom\b", "IOM"), (r"food and agriculture", "FAO"), (r"world health", "WHO"),
    (r"population fund|unfpa", "UNFPA"), (r"office for the coordination|\bocha\b", "OCHA")]
UN = {"WFP", "UNICEF", "UNHCR", "IOM", "FAO", "WHO", "UNFPA", "OCHA"}


def get(url, params=None, tries=4, timeout=240):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"not found: {url}")
            print(f"  retry {i + 1} for {url[:120]}: {e}", file=sys.stderr)
            time.sleep(10 * (i + 1))
        except Exception as e:  # network hiccups: retry with backoff
            print(f"  retry {i + 1} for {url[:120]}: {e}", file=sys.stderr)
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"failed: {url}")


def family(name):
    n = name.lower()
    for pat, fam in FAMILIES:
        if re.search(pat, n):
            return fam
    return name


def category(name, fam):
    n = name.lower()
    if fam.startswith("Partner name redacted"):
        return "Redacted"
    if fam in ("ICRC", "Red Cross / Red Crescent"):
        return "Red Cross / Red Crescent"
    if fam in UN or re.search(r"united nations|\bundp\b|unops|undss|unmas|undrr|un-habitat|un women|world bank", n):
        return "UN / multilateral"
    return "NGO"


def clean(n):
    n = re.sub(r"\s+", " ", n or "").strip()
    return n.title() if n.isupper() and len(n) > 6 else n


def pull_grants(years):
    grants = []
    for y in years:
        ids = json.loads(get(DPORTAL + ".json", {"from": "act", "limit": 5000, "reporting_ref": "XI-IATI-EC_ECHO",
                                                 "aid_like": f"%/BUD/{y}/%", "select": "aid"}))["rows"]
        codes = sorted({r["aid"].split("ECHO-ECHO/")[-1].split("/BUD")[0] for r in ids})
        print(f"{y}: {len(ids)} activities across {len(codes)} HIP codes")
        for code in codes:
            xml = get(DPORTAL + ".xml", {"from": "act", "limit": 2000, "reporting_ref": "XI-IATI-EC_ECHO",
                                         "aid_like": f"%ECHO/{code}/BUD/{y}/%"})
            for a in ET.fromstring(xml).iter("iati-activity"):
                aid = (a.findtext("iati-identifier") or "").split("EC_ECHO-")[-1]
                if aid.endswith("/91000"):
                    continue  # the HIP itself, not a grant
                ps = [p for p in a.findall("participating-org") if p.get("role") == "4"]
                partner = clean(ps[0].findtext("narrative")) if ps else "Unknown"
                if set(partner) <= set("* "):
                    partner = "Partner name redacted by ECHO"
                fam = "Partner name redacted by ECHO" if partner.startswith("Partner name redacted") else family(partner)
                eur, dates = 0.0, []
                for tr in a.findall("transaction"):
                    tt = tr.find("transaction-type")
                    if tt is not None and tt.get("code") == "2":
                        eur += float(tr.findtext("value") or 0)
                        d = tr.find("transaction-date")
                        if d is not None:
                            dates.append(d.get("iso-date"))
                sectors = sorted({s.findtext("narrative") for s in a.findall("sector")
                                  if s.get("vocabulary") not in (None, "1", "2") and s.findtext("narrative")})
                grants.append({"grant_id": aid, "hip": code, "hip_name": HIPNAME.get(code, code), "year": y,
                               "partner": partner, "family": fam, "category": category(partner, fam),
                               "countries": ",".join(c.get("code") for c in a.findall("recipient-country")),
                               "eur": round(eur), "first_commitment": min(dates) if dates else "",
                               "sectors": "|".join(sectors), "title": (a.findtext("title/narrative") or "").strip()})
            time.sleep(1)
    return grants


def parse_amount(s):
    s = s.strip()
    s = re.sub(r"[.,]\d{2}$", "", s)  # drop cents, whichever separator
    return int(re.sub(r"\D", "", s) or 0)


def pull_totals(years, current_year):
    totals = []
    for y in years:
        text = ""
        for suffix in ([""] if y == current_year else []) + [f"-{y}"]:
            try:
                html = get(HIP_PAGE.format(suffix=suffix), timeout=60).decode("utf-8", "ignore")
                text += re.sub(r"<[^>]+>", " ", html)
            except RuntimeError:
                pass
        text = re.sub(r"\s+", " ", text)
        found = {}
        for m in re.finditer(r"ECHO/([A-Z\-]{2,4})/BUD/(\d{4})/91000.{0,200}?Amount \(EUR\):\s*([\d.,]+)", text):
            if int(m.group(2)) == y and m.group(1) not in found:
                found[m.group(1)] = parse_amount(m.group(3))
        print(f"HIP budgets {y}: {len(found)} found")
        for code, v in found.items():
            totals.append({"hip": code, "hip_name": HIPNAME.get(code, code), "year": y, "hip_total_eur": v})
    return totals


def main():
    today = datetime.date.today()
    y = today.year
    years = [y - 2, y - 1, y]
    grants = pull_grants(years)
    if len(grants) < 100:
        sys.exit(f"Only {len(grants)} grants found – keeping existing data.")
    totals = pull_totals(years, y)
    old_totals = DATA / "hip_totals.json"
    if old_totals.exists():  # keep earlier budgets where the ECHO page could not be read
        have = {(t["hip"], t["year"]) for t in totals}
        totals += [t for t in json.loads(old_totals.read_text()) if (t["hip"], t["year"]) not in have and t["year"] in years]
    DATA.mkdir(exist_ok=True)
    (DATA / "grants.json").write_text(json.dumps(grants, ensure_ascii=False, separators=(",", ":")))
    (DATA / "hip_totals.json").write_text(json.dumps(totals, ensure_ascii=False, indent=0))
    latest = max((g["first_commitment"] for g in grants if g["first_commitment"]), default="")
    (DATA / "meta.json").write_text(json.dumps({"pulled": today.isoformat(), "latest_commitment": latest,
                                                "years": years, "grants": len(grants)}, indent=1))
    print(f"Wrote {len(grants)} grants, {len(totals)} HIP budgets; newest commitment {latest}")


if __name__ == "__main__":
    main()
