"""Rule-based helpdesk router: the no-AI comparison baseline.

Pipeline: normalise the message, extract people (directory name index), systems
(alias table), dates (relative to TODAY) and intent cues, then run rule families
in a fixed priority order. Every write is pre-checked against the directory and
system catalogue with the same rules the policies state, so the router only files
what policy allows; anything it cannot place is escalated to a human.
Standard library only; no model calls.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re

from .episode import Episode
from .world import DIRECTORY, SYSTEMS, TODAY, business_days_until


def rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


# ------------------------------------------------------------------ systems
SYSTEM_ALIASES = {
    "email": r"\b(?:e-?mail|calendar|outlook|mailbox)\b",
    "chat": r"\b(?:team chat|chat|slack)\b",
    "hr_portal": r"\b(?:hr (?:self[- ]service )?portal|hr_portal)\b",
    "git": r"\b(?:git|github|gitlab|code ?(?:repo|repos|repository|repositories|base)|repos?|repository|source code)\b",
    "crm": r"\b(?:crm|salesdesk)\b",
    "tms": r"\b(?:tms|transport(?:ation)? management(?: system)?)\b",
    "bi": r"\b(?:bi|analytics|dashboards?|business intelligence)\b",
    "vpn": r"\bvpn\b",
    "erp": r"\berp\b",
    "hris": r"\b(?:hris|hr records|hr information system)\b",
    "payroll": r"\bpayroll\b",
    "prod_db": r"\b(?:prod(?:uction)?[ _-]?(?:db|database)s?|production data)\b",
    "admin_console": r"\b(?:(?:cloud )?admin[ _-]?console|cloud console|cloud admin)\b",
}
SYSTEM_RX = {k: rx(v) for k, v in SYSTEM_ALIASES.items()}
# words that are also everyday nouns: only a system when the clause is about access
WEAK_SYSTEMS = {"email", "chat", "hr_portal", "payroll"}
WEAK_CONTEXT = rx(r"\b(?:access|account|login|log-?in|permissions?|request|system)\b|\badd(?:ed|ing)? (?:me|him|her|them|\w+) (?:to|on|into)\b"
                  r"|\b(?:need|needs|want|wants|give|grant)\s+(?:\w+\s+)?(?:the\s+)?(?:payroll|e-?mail|chat|calendar|hr portal)\b")

# ------------------------------------------------------------------ intent cues
INJECTION = rx(r"ignore (?:all |any |the |your )?(?:previous |prior |above |earlier )?(?:instructions|rules|policies|guidelines)"
               r"|disregard (?:your|the|all|any) |system prompt|developer mode|jailbreak|\byou are now\b"
               r"|pretend (?:you are|to be)|override (?:the |your )?(?:policy|policies|rules|validation|checks)|admin mode")
SELF_APPROVE = rx(r"approve (?:it|this|my|the) ?(?:request)? ?(?:yourself|myself)|approve my own|self[- ]approv"
                  r"|(?:skip|bypass|without|circumvent|override) (?:the |any )?(?:approval|approver|sign[- ]off)"
                  r"|(?:can|could) you (?:just )?approve")
SEC_INCIDENT = rx(r"clicked (?:on )?(?:a |an |the |this |that )?(?:\w+ ){0,3}(?:link|attachment)|entered (?:my )?(?:password|credentials|login)"
                  r"|(?:account|laptop|device|computer|email|mailbox|machine) (?:has been |was |is |got |may have been |might be |been )?(?:compromised|hacked)"
                  r"|\bhacked\b|\bmalware\b|\bvirus\b|ransomware|someone (?:else )?(?:logged|is logging|has logged|logging) in"
                  r"|unauthori[sz]ed (?:access|login|sign-?in)|suspicious (?:login|sign-?in|activity)|strange (?:login|activity)")
DEVICE = r"(?:laptop|phone|device|computer|macbook|tablet|ipad|badge|mobile)"
LOST_DEVICE = rx(rf"\b(?:lost|stolen|stole|missing|misplaced|left)\b(?:\W+\w+){{0,4}}\W+{DEVICE}"
                 rf"|{DEVICE}\b(?:\W+\w+){{0,5}}\W+(?:lost|stolen|missing|taken|gone|nicked)\b"
                 rf"|(?:can'?t|cannot) find (?:my |the )?{DEVICE}")
PASSWORD = rx(r"(?<!wi-fi )(?<!wifi )(?<!guest )password|passcode|\bmfa\b|\b2fa\b|two[- ]factor|multi[- ]factor|authenticator|locked out")
SELF_SERVICE_BLOCKED = rx(r"lost (?:my )?phone|new phone|(?:phone|number) (?:was |is |got )?(?:stolen|broken|lost|dead|died|changed)"
                          r"|(?:don'?t|no longer) have (?:my |access to my |the )?(?:phone|registered phone|number)"
                          r"|changed (?:my )?(?:phone|number)|without (?:my )?phone"
                          r"|(?:can'?t|cannot|unable to) (?:get into|access|use|log ?in to|reach|open) (?:the )?(?:reset|self[- ]service)"
                          r"|locked out of (?:the )?(?:reset |self[- ]service )?portal|(?:reset|self[- ]service) portal (?:isn'?t|is not|doesn'?t|won'?t)"
                          r"|(?:can'?t|cannot|not) (?:receive|get) (?:the |my )?(?:code|text|sms)")
OTHERS_PASSWORD = rx(r"\b(?:his|her|their|someone'?s|somebody'?s|colleague'?s|coworker'?s|co-worker'?s|teammate'?s|boss'?s|manager'?s|report'?s)\s+(?:password|mfa|2fa|login|account)"
                     r"|(?:password|mfa|2fa)\s+for\s+(?:him|her|them|my (?:colleague|coworker|team|report|boss|manager))")
SHARE_CREDS = rx(r"share (?:my |a |our |the |his |her |their )?(?:password|login|credentials|account)|(?:password|login|credentials) with (?:my |a |\w+)"
                 r"|(?:log|sign) ?in as (?!an? (?:admin|guest))|use (?:his|her|their|\w+'s) (?:login|account|password)"
                 r"|forward(?:ing)? (?:\w+ ){0,3}(?:e-?mails?|mail|files) to (?:my |a )?(?:personal|gmail|yahoo|hotmail|home|private)"
                 r"|(?:company|work) (?:files|documents|data) (?:to|in|on) (?:my )?(?:personal|dropbox|google drive|icloud)")
PERSONAL_DATA = rx(r"salary|salaries|compensation|how much (?:does|do|did) \w+ (?:make|earn|get paid)|\bpay (?:rate|grade|band|slip|stub)"
                   r"|home address|(?<!e-mail )(?<!email )\baddress\b|\bbonus(?:es)?\b|pay ?(?:rise|raise)|where (?:does|do) \w+ live|personal (?:phone|cell|mobile|email|e-mail|number)|phone number|cell(?:phone)? number|mobile number"
                   r"|medical|health|diagnos|illness|condition|pregnan|why (?:is|was) (?:\w+'?s? ){1,3}(?:on leave|off|out|away)|why (?:\w+ ){1,3}(?:is|was) (?:on leave|off|out|away)"
                   r"|reason for (?:\w+'s |his |her |their )?(?:leave|absence)"
                   r"|performance (?:review|rating|issues?|problems?)|\brating\b|disciplin|\bwarning\b|\bpip\b|date of birth|birthday|\bage\b|social security|\bssn\b|bank (?:details|account)")
INFO_SEEKING = rx(r"\b(?:what|what's|whats|why|tell me|share|send me|give me|find out|look up|lookup|how much|do you know|can you (?:check|tell|find)|confirm|let me know|which|when did|is it true|did|has)\b")
DIRECTORY_Q = rx(r"\b(?:e-?mail(?: address)?|title|job title|role|position|department|dept|manager|boss|reports? to|location|office|based|where (?:does|do|is) \w+ (?:work|sit|located|based))\b")
DIRECTORY_CUE = rx(r"\b(?:what|what's|whats|who|who's|where|which|tell me|give me|send me|look up|find|do you know)\b")

INVOL = rx(r"\bfir(?:ed|ing)\b|\b(?:to|going to|want to|need to|have to|will) fire\b|terminat(?:e|ed|ing|ion)\b(?! (?:of )?(?:his|her|their|the) access)"
           r"|\blet (?:\w+ )?go\b|\bletting (?:\w+ )?go\b|laid off|\blay(?:ing)? (?:\w+ )?off\b|layoffs?|redundan\w*|dismiss\w*|for cause|misconduct"
           r"|walked out|escorted out|(?:role|position|job) (?:is being |was |has been )?eliminated|end(?:ing)? (?:his|her|their) (?:contract|employment) (?:early|immediately|now)")
LEAVE = rx(r"\b(?:parental|maternity|paternity|medical|sick|personal|unpaid|family|extended|disability|bereavement|compassionate|long-term) leave\b"
           r"|\bleave of absence\b|\bon leave\b|\bsabbatical\b|\bgoing on leave\b")
VOL_STRONG = rx(r"\boffboard\w*|\bresign\w*|\bquit(?:s|ting)?\b|(?:handed|put|gave|giving|hand) (?:in )?(?:his|her|their|two weeks'?|2 weeks'?)? ?notice"
                r"|\bretir(?:e|es|ing|ement)\b|accepted (?:an?|another) (?:offer|job|role|position)"
                r"|contract (?:ends|is ending|ending|is up|expires|will end|finishes|runs out|end date|comes to an end)")
VOL_WEAK = rx(r"\blast (?:working |work )?day\b|\bfinal day\b|\bleaving (?:the company|fernhollow|us|the team)\b|\bmoving on\b|\b(?:is|will be) leaving\b")
ONBOARD = rx(r"\bonboard\w*")
ONBOARD_SOFT = rx(r"\b(?:new hire|new starter|new employee|joins|joining|starts|starting|start date|first day)\b")
SETUP = rx(r"\b(?:set (?:\w+ )?up|get (?:\w+ )?(?:set up|ready|started)|accounts?|laptop)\b")
REMOVAL = rx(r"\b(?:remove|removed|revoke|disable|deactivate|cut off|take away|turn off|suspend|delete|shut off|lock)\b")
GRANT = rx(r"\b(?:access|permissions?|request|requests|requesting|give|grant|provision|enable|add|added|set (?:\w+ )?up|sign (?:\w+ )?up"
           r"|get|getting|need|needs|needed|want|wants|would like|i'd like|make sure|too|as well)\b")
NOT_REQUEST = rx(r"\b(?:do|does|did|should|will|is|are)\s+(?:i|we|you|he|she|they|[a-z]+)\s+(?:need|have|require|keep|lose|get to)\b")
ACCESS_WORDS = rx(r"\b(?:access|permissions?)\b")
ASK_WORDS = rx(r"\b(?:need|needs|give|grant|request|get|set (?:\w+ )?up|add|want|wants|like|please)\b")
SAME_AS = rx(r"same (?:access|permissions|systems|setup|set-?up|rights|tools) as|\bmirror\b|copy (?:\w+'s )?(?:access|permissions)"
             r"|whatever \w+ has|everything (?:that )?\w+ has|access (?:like|matching) \w+")
VAGUE_ALL = rx(r"\b(?:access to everything|all (?:the )?systems|full access|every system|all access)\b")
IT_ISSUE = rx(r"\b(?:can'?t|cannot|can not|unable to|couldn'?t|not able to|won'?t let (?:me|him|her)) (?:log ?in|sign ?in|get in|access|connect|open|load|use)\b"
              r"|\bnot working\b|\bisn'?t working\b|\bstopped working\b|\berror\b|\bbroken\b|\bcrash")
PROCESS_Q = rx(r"\bhow long\b|\bwho (?:approves|can approve|signs off|needs to approve|has to approve)\b"
               r"|\bhow (?:do|can|would|should) (?:i|we|you|someone|people|employees|an? \w+) (?:request|get|apply|ask)\b"
               r"|\bwhat(?:'s| is) the process\b|\bprocess for\b")
CLASS_WORDS = rx(r"\b(?:contractors?|interns?|part[- ]timers?|temps|full[- ]time (?:staff|employees|only)|eligib\w*|who can (?:get|have|access|use))\b")
DATA_RISK = rx(r"\busb\b|thumb ?drive|flash drive|external (?:hard )?drive|exfiltrat\w*|\bsteal(?:ing|s)?\b|\bstole\b(?! my)|sabotag\w*"
               r"|download(?:ing|ed|s)? (?:the |all |our )?(?:entire|whole|all|every)|cop(?:y|ying|ied) (?:the |all |our )?(?:entire|whole|all|customer|client)"
               r"|customer (?:list|data|database)|client list|(?:wiping|deleting|deleted|wiped) (?:the |all |our )?(?:files|data|records|repos?)|threaten\w*")
SELF_REF = rx(r"\b(?:i|me|my|myself|i'm|i'd|i've|i'll|mine)\b")
SELF_STRONG = rx(r"\b(?:for me|for myself|get me|give me|grant me|add me|set me up|me and|and me|and i|i and|both of us|myself)\b")
PRONOUN = rx(r"\b(?:he|she|him|her|they|them|his|their|hers)\b")
INHERIT_SYS = rx(r"\b(?:too|as well|also|same|so does|so do|both)\b")

# topics no policy covers: route these to a human instead of keyword-matching a policy
NO_POLICY_TOPIC = rx(r"tuition|\bgym\b|wellness|fitness|mileage|commut\w*|parking|home internet|internet (?:bill|service|costs?|plan)|phone (?:bill|plan)|insurance|\b401|pension"
                     r"|retirement plan|dental|vision plan|bonus|stock|equity|relocat\w*|referral|bereavement|funeral|jury|volunteer\w*|sabbatical|childcare"
                     r"|daycare|dress code|freelanc\w*|moonlight\w*|side (?:job|gig|business|hustle)|second job|overtime|\bpets?\b|\bdogs?\b|\bcats?\b"
                     r"|lunch|snacks?|coffee|training budget|learning budget|certification|union|promotion|pay ?day|paycheck|pay stub|payslip|\bw-?2\b"
                     r"|tax form|holiday party|office party|birthday|smok\w*|vap(?:e|ing)|dating|politic\w*|donat\w*|charity|blood")
IT_TOPIC = rx(r"\b(?:laptop|computer|monitor|screen|printer|keyboard|mouse|headset|webcam|wi-?fi|network|software|install|app|application|vpn"
              r"|login|log ?in|sign ?in|error|bug|crash|broken|not working|device|tablet|ipad|system|tool)\b")
SEC_TOPIC = rx(r"phish\w*|hack\w*|breach|malware|virus|ransomware|suspicious|compromis\w*|leak\w*|steal\w*|unauthori[sz]ed")

# ------------------------------------------------------------------ policy routing
POLICY_ROUTES = {
    "POL-PTO-01": ([r"\bpto\b", r"paid time off", r"vacation", r"\btime off\b", r"\b(?:days?|weeks?) off\b", r"annual leave"],
                   [r"carr(?:y|ied|ying) over|carryover|roll ?over", r"\baccru", r"unused days"]),
    "POL-SICK-01": ([r"\bsick\b", r"\billness\b", r"doctor'?s note", r"\bunwell\b", r"\bflu\b", r"\bill\b"], []),
    "POL-PAR-01": ([r"parental", r"maternity", r"paternity", r"\badopt", r"\bfoster", r"\bbaby\b", r"newborn", r"pregnan"], []),
    "POL-REM-01": ([r"work(?:ing)? from home", r"\bwfh\b", r"\bremote(?:ly)?\b", r"\bhybrid\b", r"another country", r"different country",
                    r"\babroad\b", r"overseas", r"telework|telecommut"], []),
    "POL-EQP-01": ([r"\blaptops?\b", r"home[- ]office", r"personal (?:device|phone|ipad|tablet|computer|mobile|laptop)", r"own (?:phone|device|ipad|tablet|laptop)",
                    r"\bbyod\b", r"\bequipment\b", r"stipend.*\b(?:home|desk|chair|setup|set-up)\b|\b(?:home|desk|chair|setup)\b.*stipend"], []),
    "POL-EXP-01": ([r"\bexpens(?:e|es|ed|ing)\b", r"reimburs", r"\breceipts?\b", r"per diem", r"\bmeals?\b", r"\balcohol\b", r"\bdrinks?\b"], []),
    "POL-TRV-01": ([r"\bfl(?:y|ying|ight|ights|ew)\b", r"\btravel", r"\bhotels?\b", r"business class", r"premium economy", r"economy class",
                    r"\btrips?\b", r"airfare"], []),
    "POL-HOL-01": ([r"\bholidays?\b", r"christmas", r"new year", r"thanksgiving", r"offices? (?:be )?clos", r"\bclosure\b", r"replacement day"], []),
    "POL-SEC-01": ([r"phish", r"suspicious (?:e-?mail|link|message|attachment)", r"\binstall", r"\bsoftware\b", r"personal (?:e-?mail|gmail|cloud|dropbox|drive|account)",
                    r"\b(?:gmail|dropbox|google drive|icloud|onedrive)\b", r"share (?:my |a )?(?:password|login|account)"], []),
    "POL-PWD-01": ([r"(?<!wi-fi )(?<!wifi )(?<!guest )password", r"\bmfa\b", r"\b2fa\b", r"two[- ]factor", r"multi[- ]factor", r"authenticator", r"locked out"], []),
    "POL-ACC-01": ([r"approv", r"access requests?", r"request access", r"on (?:someone|somebody)(?:'s)? behalf", r"how long\b.*\baccess|\baccess\b.*how long"], []),
    "POL-ACC-02": ([r"eligib", r"\bexception"], []),
    "POL-ONB-01": ([r"onboard", r"new hires?", r"new starters?", r"first day"], []),
    "POL-OFF-01": ([r"offboard", r"resign", r"\bquit", r"last (?:working )?day", r"leav(?:e|ing) the company", r"final pay", r"return (?:my |the |a )?(?:laptop|badge)"], []),
    "POL-OFF-02": ([r"terminat", r"layoffs?|laid off|lay off", r"leave of absence", r"\bfired\b", r"(?:while|during) (?:on |my |his |her |their )?\w* ?leave"], []),
}
POLICY_ROUTES = {k: ([rx(p) for p in s], [rx(p) for p in w]) for k, (s, w) in POLICY_ROUTES.items()}


WORK_FROM_PLACE = re.compile(r"\bwork(?:ing)? (?:from|in) (?!Home\b|Boston\b|Chicago\b)[A-Z][a-z]+")


def route_policies(text: str, orig: str = "") -> list[str]:
    strong = {k: sum(bool(p.search(text)) for p in s) for k, (s, _) in POLICY_ROUTES.items()}
    strong["POL-REM-01"] += bool(WORK_FROM_PLACE.search(orig))
    best = max(strong.values())
    if best:
        return [k for k, v in strong.items() if v == best][:3]
    weak = {k: sum(bool(p.search(text)) for p in w) for k, (_, w) in POLICY_ROUTES.items()}
    best = max(weak.values())
    return [k for k, v in weak.items() if v == best][:3] if best else []


# ------------------------------------------------------------------ people
COMMON_WORD_NAMES = {"grant", "park", "mark", "grace", "victor", "jordan", "brooks", "will", "may", "bill", "chase", "rose"}
SUBJECT_VERB_AFTER = rx(r"^(?:'s\b|\s+(?:is|has|needs|was|wants|will|starts|started|resigned|told|said|asked|and|can|could|should|just|also|needs?)\b)")
REPORT_AFTER = rx(r"^\W*(?:'s\s+)?(?:says|said|told|tells|approved|okayed|ok'd|agreed|confirmed|mentioned|signed off|thinks|asked me|wants me|has|had|already has)\b")
REPORT_BEFORE = rx(r"(?:same (?:access|permissions|systems) as|\blike|\bas|\bper|\bby|\bfrom|according to|\bthan|\bwith)\s*$")


def _norm_token(tok: str) -> str:
    tok = re.sub(r"'s$|s'$", "", tok)
    return tok.replace("'", "").lower()


def _build_index():
    first, last, full = {}, {}, []
    for e in DIRECTORY.values():
        toks = [_norm_token(t) for t in e["name"].split()]
        first.setdefault(toks[0], set()).add(e["id"])
        last.setdefault(toks[-1], set()).add(e["id"])
        variants = [toks[0]]
        nick = re.search(r"goes by (\w+)", e["notes"], re.I)   # only the nickname is read from notes
        if nick:
            n = nick.group(1).lower()
            first.setdefault(n, set()).add(e["id"])
            variants.append(n)
        lastpat = "'?".join(re.escape(c) for c in toks[-1])
        for v in variants:
            full.append((rx(rf"\b{re.escape(v)}\s+{lastpat}(?:'s)?\b"), e["id"]))
    return first, last, full


FIRST, LAST, FULL = _build_index()
NON_NAME_CAPS = {w.lower() for w in """I I'm I'd I've I'll HR IT CRM TMS BI VPN ERP HRIS Git GitHub Payroll Finance Engineering Sales
Operations Ops Executive Legal Boston Chicago Remote Fernhollow Freight Monday Tuesday Wednesday Thursday Friday Saturday Sunday
January February March April May June July August September October November December Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec
Q1 Q2 Q3 Q4 CEO CFO VP Please Hi Hello Hey Thanks Thank Can Could Would We Our My He She They The A An Also And But So Is What Who How
When Where Why Do Does Did Am Are Yes No OK Okay Dear Team Security Hello This That These His Her Their New Sorry Quick Urgent Just
Need Give File Start Get Onboard Offboard Request Mr Ms Mrs Dr Admin Console Production Database Analytics Dashboards Salesdesk Slack
Email Chat Portal Office Christmas Thanksgiving Year Day USB MFA PTO Zoom Google Microsoft Teams Excel AWS Dropbox Gmail Outlook
Contractor Intern Manager Director Engineer Support Specialist Analyst Coordinator Lead""".split()}


def find_mentions(text: str) -> list[dict]:
    """People mentioned in the message: [{start, end, ids, surface}]."""
    out, taken = [], []
    for pat, eid in FULL:
        for m in pat.finditer(text):
            if not any(a <= m.start() < b for a, b in taken):
                out.append({"start": m.start(), "end": m.end(), "ids": [eid], "surface": m.group(0)})
                taken.append((m.start(), m.end()))
    for m in re.finditer(r"\bE\d{3}\b", text):
        if m.group(0) in DIRECTORY:
            out.append({"start": m.start(), "end": m.end(), "ids": [m.group(0)], "surface": m.group(0)})
            taken.append((m.start(), m.end()))
    for m in re.finditer(r"[A-Za-z][A-Za-z']*", text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        raw, tok = m.group(0), _norm_token(m.group(0))
        cap = raw[0].isupper()
        before = text[:m.start()].rstrip()
        initial = not before or before[-1] in ".!?:\n"
        ids = set()
        if tok in FIRST:
            if tok in COMMON_WORD_NAMES:
                if not cap or (initial and not SUBJECT_VERB_AFTER.search(text[m.end() - (2 if raw.endswith("'s") else 0):])):
                    continue
            ids = FIRST[tok]
        elif tok in LAST and cap and not initial and tok not in COMMON_WORD_NAMES:
            ids = LAST[tok]
        if ids:
            out.append({"start": m.start(), "end": m.end(), "ids": sorted(ids), "surface": raw})
    # "I'm Laura from HR" / "this is Marcus": the requester is the session's employee, so a claimed identity is ignored
    claim_before, claim_after = rx(r"(?:\bi'm|\bi am|\bthis is)\s*$"), rx(r"^\s*(?:,|-|from\b|here\b|in\b|on\b|\.|$)")
    out = [m for m in out if not (claim_before.search(text[:m["start"]]) and claim_after.search(text[m["end"]:]))]
    return sorted(out, key=lambda x: x["start"])


def unknown_names(text: str) -> list[str]:
    """Capitalised words that look like a person's name but are not in the directory."""
    toks = list(re.finditer(r"[A-Za-z][A-Za-z']*", text))
    res = []
    for i, m in enumerate(toks):
        raw = m.group(0)
        if not raw[0].isupper() or raw.isupper() or _norm_token(raw) in NON_NAME_CAPS:
            continue
        if _norm_token(raw) in FIRST or _norm_token(raw) in LAST:
            continue
        before = text[:m.start()].rstrip()
        initial = not before or before[-1] in ".!?:\n"
        nxt = toks[i + 1].group(0) if i + 1 < len(toks) else ""
        if not initial or (nxt[:1].isupper() and _norm_token(nxt) not in NON_NAME_CAPS):
            res.append(raw)
    return res


# ------------------------------------------------------------------ dates
MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
          "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
          "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12}
MON = "|".join(sorted(MONTHS, key=len, reverse=True))
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "a": 1, "an": 1}


def _ymd(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _infer(m: int, d: int, y: str | None = None) -> dt.date | None:
    if y:
        y = int(y) + (2000 if int(y) < 100 else 0)
        return _ymd(y, m, d)
    c = _ymd(TODAY.year, m, d)
    if c and c < TODAY and (TODAY - c).days > 180:
        c = _ymd(TODAY.year + 1, m, d)
    return c


def _last_weekday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _weekday(wd: int, mod: str | None) -> dt.date:
    if mod == "next":
        next_monday = TODAY + dt.timedelta(days=7 - TODAY.weekday())
        return next_monday + dt.timedelta(days=wd)
    delta = (wd - TODAY.weekday()) % 7
    if delta == 0 and mod != "this":
        delta = 7
    return TODAY + dt.timedelta(days=delta)


def find_dates(text: str) -> list[tuple[int, dt.date]]:
    low = text.lower()
    out = []
    for m in re.finditer(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", low):
        out.append((m.start(), _ymd(int(m[1]), int(m[2]), int(m[3]))))
    for m in re.finditer(rf"\b({MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(20\d\d))?", low):
        out.append((m.start(), _infer(MONTHS[m[1]], int(m[2]), m[3])))
    for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MON})\b\.?(?:,?\s*(20\d\d))?", low):
        out.append((m.start(), _infer(MONTHS[m[2]], int(m[1]), m[3])))
    for m in re.finditer(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])", low):
        out.append((m.start(), _infer(int(m[1]), int(m[2]), m[3])))
    for m in re.finditer(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", low):
        d = int(m[1])
        c = _ymd(TODAY.year, TODAY.month, d)
        if c is None or c < TODAY:
            nm = TODAY.month % 12 + 1
            c = _ymd(TODAY.year + (TODAY.month == 12), nm, d)
        out.append((m.start(), c))
    out = [x for x in out if x[1]]
    if out:
        return sorted(out)
    rel = []
    for m in re.finditer(r"\b(?:today|tonight|end of (?:the )?day|eod|effective immediately|immediately)\b", low):
        rel.append((m.start(), TODAY))
    for m in re.finditer(r"\btomorrow\b", low):
        rel.append((m.start(), TODAY + dt.timedelta(days=1)))
    for m in re.finditer(r"\bend of (?:the |this )?week\b", low):
        rel.append((m.start(), _weekday(4, "this")))
    for m in re.finditer(r"\bend of next week\b", low):
        rel.append((m.start(), _weekday(4, "next")))
    for m in re.finditer(r"\bend of (?:the |this )?month\b", low):
        rel.append((m.start(), _last_weekday(TODAY.year, TODAY.month)))
    for m in re.finditer(r"\bend of next month\b", low):
        y, mo = (TODAY.year + 1, 1) if TODAY.month == 12 else (TODAY.year, TODAY.month + 1)
        rel.append((m.start(), _last_weekday(y, mo)))
    for m in re.finditer(rf"\bend of ({MON})\b", low):
        mo = MONTHS[m[1]]
        rel.append((m.start(), _last_weekday(TODAY.year + (mo < TODAY.month), mo)))
    for m in re.finditer(r"\bend of (?:the |this )?year\b", low):
        rel.append((m.start(), _last_weekday(TODAY.year, 12)))
    for m in re.finditer(r"\b(?:in (\d+|one|two|three|four|five|six|a) (day|week)s?|(\d+|one|two|three|four|five|six|a) (day|week)s? from (?:now|today))\b", low):
        n, unit = (m[1], m[2]) if m[1] else (m[3], m[4])
        n = int(n) if n.isdigit() else NUMWORDS[n]
        rel.append((m.start(), TODAY + dt.timedelta(days=n * (7 if unit == "week" else 1))))
    if not rel:
        for m in re.finditer(rf"\b(?:(this|next|coming)\s+)?({'|'.join(WEEKDAYS)})\b", low):
            rel.append((m.start(), _weekday(WEEKDAYS.index(m[2]), m[1])))
    return sorted(rel)


LAST_DAY_CUE = rx(r"last (?:working |work )?day|final day|leaving (?:on|at)|leaves (?:on|at)|effective|\bends?(?: on)?\b|ending|\buntil\b|through"
                  r"|out (?:on|from)|finish(?:es|ing)?|is up|expires|\bon\b")


def pick_last_day(text: str) -> dt.date | None:
    ds = find_dates(text)
    if not ds:
        return None
    if len({d for _, d in ds}) == 1:
        return ds[0][1]
    for m in LAST_DAY_CUE.finditer(text):
        for pos, d in ds:
            if 0 <= pos - m.end() <= 40:
                return d
    return None


# ------------------------------------------------------------------ the router
def split_clauses(text: str) -> list[tuple[int, int]]:
    bounds, pos = [], 0
    for m in re.finditer(r"(?<=[.!?;])\s+|,\s*(?:and|but|plus)\s+|\s+(?:and also|also|plus)\s+", text):
        bounds.append((pos, m.start()))
        pos = m.end()
    bounds.append((pos, len(text)))
    return [(a, b) for a, b in bounds if b > a]


class Router:
    def __init__(self, case: dict):
        self.ep = Episode.start(case)
        self.rid = case["requester_id"]
        self.me = DIRECTORY[self.rid]
        self.text = re.sub(r"[‘’]", "'", case["message"]).replace("“", '"').replace("”", '"')
        self.low = self.text.lower()
        self.read: dict[str, dict] = {}
        self.cite: list[str] = []
        self.parts: list[str] = []
        self.done = self.refused = self.clarified = self.answered = False
        self.queues: list[str] = []
        self.records: dict[str, dict] = {}
        self.mentions = find_mentions(self.text)

    # ---- tool helpers
    def policy(self, pid: str) -> dict:
        if pid not in self.read:
            res, _ = self.ep.tool("get_policy", {"policy_id": pid})
            self.read[pid] = res
        if pid not in self.cite:
            self.cite.append(pid)
        return self.read[pid]

    def quote(self, pid: str) -> str:
        p = self.policy(pid)
        return f"{p['title']} ({pid}): {p['text']}"

    def lookup(self, eid: str, refresh: bool = False) -> dict:
        if refresh or eid not in self.records:
            res, _ = self.ep.tool("lookup_employee", {"query": DIRECTORY[eid]["name"]})
            rec = next(r for r in res["matches"] if r["id"] == eid)
            rec["manager_id"] = rec["manager"].split()[0] if rec["manager"] else None
            self.records[eid] = rec
        return self.records[eid]

    def escalate(self, queue: str, why: str) -> None:
        if queue in self.queues:
            return
        summary = f"{why} Requester {self.rid} {self.me['name']} ({self.me['title']}) wrote: \"{self.text}\""
        res, err = self.ep.tool("escalate_to_human", {"queue": queue, "summary": summary})
        if not err:
            self.queues.append(queue)
            self.parts.append(f"I've passed this to the {queue.upper() if queue != 'security' else 'Security'} team "
                              f"(ticket {res['ticket_id']}); they will follow up with you.")

    def refuse(self, msg: str, pids: list[str] = ()) -> None:
        self.refused = True
        self.parts.append(msg + "".join(" " + self.quote(p) for p in pids))

    def clarify(self, msg: str) -> None:
        self.clarified = True
        self.parts.append(msg)

    def answer(self, msg: str, pids: list[str] = ()) -> None:
        self.answered = True
        self.parts.append(msg + "".join(" " + self.quote(p) for p in pids))

    def finish(self) -> Episode:
        if self.done:
            kind = "done"
        elif self.queues:
            kind = "escalated"
        elif self.clarified:
            kind = "clarify"
        elif self.refused:
            kind = "refuse"
        elif self.answered:
            kind = "answer"
        else:
            self.escalate("hr", "No helpdesk rule matched this request.")
            kind = "escalated"
        self.ep.tool("reply", {"kind": kind, "message": " ".join(self.parts).strip(), "cited_policy_ids": list(self.cite)})
        return self.ep

    # ---- parsing helpers
    def systems_in(self, s: str) -> list[str]:
        found = [k for k, p in SYSTEM_RX.items() if p.search(s)]
        return [k for k in found if k not in WEAK_SYSTEMS or WEAK_CONTEXT.search(s)]

    def people(self, mentions=None) -> tuple[list[str], list[dict]]:
        """Resolved ids (in order, unique) and ambiguous mentions."""
        ids, amb = [], []
        for m in self.mentions if mentions is None else mentions:
            if len(m["ids"]) == 1:
                if m["ids"][0] not in ids:
                    ids.append(m["ids"][0])
            else:
                amb.append(m)
        return ids, amb

    def others(self) -> list[str]:
        return [i for i in self.people()[0] if i != self.rid]

    def ask_which(self, amb: list[dict]) -> None:
        for m in amb:
            opts = "; ".join(f"{DIRECTORY[i]['name']} ({DIRECTORY[i]['title']}, {DIRECTORY[i]['department']})" for i in m["ids"])
            self.ep.tool("lookup_employee", {"query": m["surface"]})
            self.clarify(f"There is more than one \"{m['surface']}\" in the directory: {opts}. Which one do you mean?")

    # ---- main
    def run(self) -> Episode:
        t = self.low
        if INJECTION.search(t):
            pids = ["POL-ACC-01"] if self.systems_in(t) or ACCESS_WORDS.search(t) else []
            self.refuse("I can't follow instructions to bypass helpdesk rules. I can file requests, which still go to the "
                        "normal approver.", pids)
            return self.finish()
        if SEC_INCIDENT.search(t):
            self.escalate("security", "Possible account or device compromise reported; urgent per POL-SEC-01.")
            self.parts.append("Please don't use the affected account or device until Security contacts you.")
            return self.finish()
        if PASSWORD.search(t) and re.search(r"\breset", t) and (self.others() or OTHERS_PASSWORD.search(t)):
            return self.password()
        if LOST_DEVICE.search(t):
            self.escalate("it", "Lost or stolen device reported; it needs to be locked and wiped (POL-EQP-01).")
            return self.finish()
        if SHARE_CREDS.search(t):
            self.refuse("I can't help with that: accounts are personal and company data stays in company systems.", ["POL-SEC-01"])
            return self.finish()
        if PASSWORD.search(t):
            return self.password()
        if SELF_APPROVE.search(t):
            self.refuse("The helpdesk files access requests but never approves or grants them, and nobody can approve "
                        "their own request.", ["POL-ACC-01"])
            return self.finish()
        if self.privacy():
            return self.finish()
        if DATA_RISK.search(t) and (self.others() or PRONOUN.search(t) or re.search(r"\b(?:someone|colleague|coworker|employee)\b", t)):
            self.escalate("security", "Possible data theft or sabotage reported; Security should review at once (POL-OFF-02).")
        targets = self.lifecycle()
        acted = self.access(exclude=targets or set())
        if targets is not None or acted:
            self.extra_questions()
            return self.finish()
        if self.queues:
            return self.finish()
        if REMOVAL.search(t) and (self.systems_in(t) or ACCESS_WORDS.search(t)) and (self.others() or SELF_REF.search(t)):
            self.escalate("it", "Request to remove or suspend access outside an offboarding; IT must action it.")
            return self.finish()
        if self.directory_question():
            return self.finish()
        if self.policy_question():
            return self.finish()
        self.fallback()
        return self.finish()

    # ---- rule families
    def password(self) -> Episode:
        t = self.low
        others = self.others()
        if others or OTHERS_PASSWORD.search(t) or re.search(r"\breset (?:the )?(?:password|mfa) (?:for|of) (?!me\b|my\b)", t):
            self.refuse("I can't reset or arrange a reset of someone else's password or MFA; they need to use self-service "
                        "themselves or contact IT.", ["POL-PWD-01"])
        elif SELF_SERVICE_BLOCKED.search(t):
            self.escalate("it", "Employee cannot use password/MFA self-service; IT must verify identity on a video call (POL-PWD-01).")
        else:
            self.answer("You can reset your password or MFA yourself at reset.fernhollow.test using your registered phone; "
                        "the helpdesk can't reset it over chat.", ["POL-PWD-01"])
        return self.finish()

    def privacy(self) -> bool:
        """A request FOR someone's personal data: an info-seeking cue followed closely by a personal-data term."""
        t = self.low
        if REMOVAL.search(t) or ONBOARD.search(t) or VOL_STRONG.search(t):
            return False
        asks = [m.start() for m in INFO_SEEKING.finditer(t)]
        if not any(0 <= d.start() - a <= 60 for d in PERSONAL_DATA.finditer(t) for a in asks):
            return False
        ids, amb = self.people()
        about_other = [i for i in ids if i != self.rid] or amb or re.search(
            r"\b(?:his|her|their|someone'?s|colleague'?s|coworker'?s|co-worker'?s|employee'?s|team'?s)\b", t)
        if about_other:
            self.refuse("I can't share or confirm anyone's personal information (such as pay, home address, personal phone, "
                        "health or leave reasons, or performance) with anyone other than that person.", ["POL-PRIV-01"])
            return True
        if ids or SELF_REF.search(t):
            self.escalate("hr", "Employee is asking about their own personal HR data; the helpdesk does not hold it.")
            return True
        return False

    def directory_question(self) -> bool:
        t = self.low
        ids, amb = self.people()
        ids = [i for i in ids if i != self.rid]
        if not (DIRECTORY_Q.search(t) and DIRECTORY_CUE.search(t)) or not (ids or amb):
            return False
        if amb:
            self.ask_which(amb)
            return True
        lines = []
        for i in ids:
            r = self.lookup(i)
            mgr = r["manager"].split(" ", 1)[1] if r["manager"] else "none"
            lines.append(f"{r['name']}: {r['title']}, {r['department']}; work email {r['email']}; manager {mgr}; office {r['location']}.")
        self.answer(" ".join(lines), ["POL-PRIV-01"])
        return True

    def policy_question(self) -> bool:
        t = self.low
        if NO_POLICY_TOPIC.search(t):
            return False
        systems = self.systems_in(t)
        if systems and CLASS_WORDS.search(t) and not self.others() and not SELF_REF.search(t):
            lines = [self.eligibility_line(s) for s in systems]
            self.answer(" ".join(lines), ["POL-ACC-02"])
            return True
        if (systems or ACCESS_WORDS.search(t)) and PROCESS_Q.search(t):
            lines = [f"{SYSTEMS[s]['name']} requests are approved by {self.approver_text(s)}." for s in systems]
            self.answer(" ".join(lines), ["POL-ACC-01"])
            return True
        pids = route_policies(t, self.text)
        if not pids:
            return False
        self.answer("Here is what company policy says.", pids)
        return True

    def extra_questions(self) -> None:
        """After acting, answer any separate policy question sentence in the same message."""
        for sent in re.split(r"(?<=[.!?])\s+", self.low):
            if not sent.endswith("?") or self.systems_in(sent) or NO_POLICY_TOPIC.search(sent):
                continue
            if any(p.search(sent) for p in (ONBOARD, ONBOARD_SOFT, SETUP, VOL_STRONG, VOL_WEAK, INVOL, LEAVE)):
                continue
            pids = [p for p in route_policies(sent) if p not in ("POL-ONB-01", "POL-OFF-01", "POL-OFF-02")]
            if pids:
                self.answer("On your question:", pids)

    def fallback(self) -> None:
        t = self.low
        if NO_POLICY_TOPIC.search(t):
            q = "hr"
        elif SEC_TOPIC.search(t):
            q = "security"
        elif IT_TOPIC.search(t) or IT_ISSUE.search(t):
            q = "it"
        else:
            q = "hr"
        self.escalate(q, "No written policy or helpdesk rule covers this; a person needs to answer.")

    # ---- lifecycle: involuntary exits, leave, onboarding, offboarding
    def lifecycle(self) -> set[str] | None:
        t = self.low
        ids, amb = self.people()
        named = [i for i in ids if i != self.rid]
        third = bool(named or amb or PRONOUN.search(t))
        if INVOL.search(t) and third and not re.search(r"\b(?:policy|policies)\b", t):
            self.policy("POL-OFF-02")
            self.escalate("hr", "Involuntary exit: HR handles terminations and coordinates access removal (POL-OFF-02).")
            return set(self.cue_people(INVOL) or named) or {"?"}
        if LEAVE.search(t) and (named or amb) and (REMOVAL.search(t) or VOL_STRONG.search(t) or re.search(r"\b(?:access|accounts?|systems?)\b", t)):
            self.policy("POL-OFF-02")
            self.escalate("hr", "Leave of absence: not an offboarding; access stays on and HR handles the leave (POL-OFF-02).")
            return set(self.cue_people(LEAVE) or named) or {"?"}
        pre_start = any(DIRECTORY[i]["status"] == "pre_start" for i in named)
        if ONBOARD.search(t) or ((ONBOARD_SOFT.search(t) or pre_start) and SETUP.search(t) and not self.systems_in(t)):
            res = self.onboarding(named, amb)
            if res is not None:
                return res
        if VOL_STRONG.search(t) or (VOL_WEAK.search(t) and (named or amb or SELF_REF.search(t))):
            return self.offboarding(named, amb)
        return None

    def onboarding(self, named: list[str], amb: list[dict]) -> set[str] | None:
        t = self.low
        if amb:
            self.ask_which(amb)
            return set(named) or {"?"}
        recs = [self.lookup(i) for i in named]
        pre = [r for r in recs if r["status"] == "pre_start"]
        targets = pre or [r for r in recs if r["id"] not in {x.get("manager_id") for x in recs}][:1]
        if not targets:
            unknown = unknown_names(self.text)
            if unknown:
                self.ep.tool("lookup_employee", {"query": " ".join(unknown[:2])})
                self.refuse(f"I can't find {' '.join(unknown[:2])} in the directory. Onboarding needs an existing pre_start "
                            "record, so HR has to create it first.", ["POL-ONB-01"])
                return {"?"}
            if "?" in t or re.match(r"\s*(?:how|what|when|who|which|why|can i|do i|is|are)\b", t):
                return None
            self.clarify("Who is the new hire? Please give me their full name as it appears in the directory.")
            return {"?"}
        started = []
        for r in targets:
            why = []
            if r["status"] != "pre_start":
                why.append(f"{r['name']} has status {r['status']}, and onboarding needs a pre_start record")
            if self.rid != r.get("manager_id") and self.me["department"] != "HR":
                why.append(f"only {r['name']}'s manager or HR can start onboarding")
            if r["status"] == "pre_start":
                days = business_days_until(dt.date.fromisoformat(r["start_date"]))
                if days > 5:
                    why.append(f"{r['name']} starts {r['start_date']}, {days} business days away; onboarding opens 5 business "
                               "days before the start date")
            if why:
                self.refuse("I can't start onboarding yet: " + "; ".join(why) + ".", ["POL-ONB-01"])
                continue
            res, err = self.ep.tool("start_onboarding", {"employee_id": r["id"]})
            if err:
                self.refuse(f"Onboarding for {r['name']} was rejected: {res['error']}.", ["POL-ONB-01"])
                continue
            self.done = True
            started.append(r["id"])
            self.parts.append(f"Started onboarding for {r['name']} ({res['onboarding_id']}): accounts created for "
                              f"{', '.join(res['accounts_created'])}; the laptop {res['laptop']}.")
        systems = [s for s in self.systems_in(t) if not REMOVAL.search(t)]
        for eid in started:
            rec = self.lookup(eid, refresh=True)
            for s in systems:
                if s in rec["access"]:
                    self.parts.append(f"{SYSTEMS[s]['name']} is already included in the standard onboarding bundle.")
                else:
                    self.request_access(rec, s)
        if systems and not started:
            self.parts.append("Other systems can be requested once onboarding has started.")
        return {r["id"] for r in targets}

    def cue_people(self, *pats: re.Pattern) -> list[str]:
        """People named in clauses that carry one of the cues (a pronoun-only clause refers to the previous person)."""
        res, prev = [], []
        for a, b in split_clauses(self.text):
            low = self.low[a:b]
            ids = [i for i in self.people([m for m in self.mentions if a <= m["start"] < b])[0] if i != self.rid]
            if any(p.search(low) for p in pats):
                res += [i for i in (ids or (prev if PRONOUN.search(low) else [])) if i not in res]
            prev = ids or prev
        return res

    def last_day_for(self, eid: str, targets: list[str]) -> dt.date | None:
        if len(targets) == 1:
            return pick_last_day(self.text)
        mine = [m["start"] for m in self.mentions if m["ids"] == [eid]]
        theirs = [m["start"] for m in self.mentions if len(m["ids"]) == 1 and m["ids"][0] in targets and m["ids"] != [eid]]
        start = mine[0]
        end = min([p for p in theirs if p > start], default=len(self.text))
        day = pick_last_day(self.text[start:end])
        if day is None and len({d for _, d in find_dates(self.text)}) == 1:
            day = find_dates(self.text)[0][1]
        return day

    def offboarding(self, named: list[str], amb: list[dict]) -> set[str] | None:
        t = self.low
        if amb:
            self.ask_which(amb)
            return set(named) or {"?"}
        targets = self.cue_people(VOL_STRONG, VOL_WEAK) or (named if len(named) == 1 else [])
        if not targets and len(named) > 1:
            self.clarify("Who exactly is leaving, and what is their last working day?")
            return set(named)
        if len(targets) > 1:
            keep = [i for i in targets if not any(m["ids"] == [i] and REPORT_AFTER.search(self.text[m["end"]:]) for m in self.mentions)]
            targets = keep or targets
        if not targets:
            if SELF_REF.search(t) and re.search(r"\b(?:resign\w*|quit\w*|leaving|my last day|offboard me|my offboarding|notice|retir\w*)\b", t):
                msg = "You can't start your own offboarding; please tell your manager or HR, who will start it with your last day."
                (self.answer if "?" in t else self.refuse)(msg, ["POL-OFF-01"])
                return {self.rid}
            unknown = unknown_names(self.text)
            if unknown:
                self.clarify(f"I can't find {' '.join(unknown[:2])} in the directory. Could you check the name?")
                return {"?"}
            if VOL_STRONG.search(t) and not ("?" in t and re.match(r"\s*(?:how|what|when|who|which|why|do|does|is|are|can|will)\b", t)):
                self.clarify("Who is leaving? Please give me their full name and last working day.")
                return {"?"}
            return None
        risk = DATA_RISK.search(t)
        for eid in targets:
            r = self.lookup(eid)
            day = self.last_day_for(eid, targets)
            if day is None and r["end_date"] and re.search(r"\bcontract\b", t) and r["status"] == "active":
                day = dt.date.fromisoformat(r["end_date"])
            if r["status"] == "offboarding":
                if day is None or r["end_date"] == day.isoformat():
                    self.answer(f"{r['name']}'s offboarding is already scheduled with last day {r['end_date']}.")
                else:
                    self.escalate("hr", f"{r['name']} is already offboarding (last day {r['end_date']}); the requester wants a "
                                        "change that the helpdesk tools cannot make.")
                continue
            if r["status"] == "terminated":
                self.answer(f"{r['name']} has already left the company (end date {r['end_date']}); there is nothing to offboard.")
                continue
            if r["status"] != "active":
                self.escalate("hr", f"Offboarding requested for {r['name']}, whose status is {r['status']}.")
                continue
            if eid == self.rid:
                self.refuse("You can't start your own offboarding; please tell your manager or HR.", ["POL-OFF-01"])
                continue
            if self.rid != r["manager_id"] and self.me["department"] != "HR":
                self.refuse(f"Only {r['name']}'s manager or HR can start their offboarding.", ["POL-OFF-01"])
                continue
            if day is None:
                self.clarify(f"What is {r['name']}'s last working day (for example 2026-12-04)?")
                continue
            if day < TODAY:
                self.escalate("hr", f"Offboarding for {r['name']} with a last day in the past ({day}); access may still be live.")
                continue
            if day > TODAY + dt.timedelta(days=90):
                self.refuse(f"Offboarding can be scheduled at most 90 days ahead, and {day} is further out; please ask again "
                            "closer to the date.", ["POL-OFF-01"])
                continue
            res, err = self.ep.tool("start_offboarding", {"employee_id": eid, "last_day": day.isoformat()})
            if err:
                self.refuse(f"Offboarding for {r['name']} was rejected: {res['error']}.")
                continue
            self.done = True
            self.parts.append(f"Started offboarding for {r['name']} ({res['offboarding_id']}): access is removed at "
                              f"{res['access_removed_at']}, and equipment must be returned {res['equipment_return']}.")
        if risk:
            self.escalate("security", "Possible data theft or sabotage by a departing employee; Security should act at once (POL-OFF-02).")
        return set(targets)

    # ---- access requests
    def approver_text(self, s: str) -> str:
        a = SYSTEMS[s]["approver"]
        if a == "manager":
            return "the employee's manager"
        if a.startswith("owner:"):
            return f"the system owner, {DIRECTORY[a[6:]]['name']}"
        return "Security"

    def eligibility_line(self, s: str) -> str:
        sys = SYSTEMS[s]
        depts = "all departments" if sys["departments"] == "all" else ", ".join(sys["departments"])
        types = ", ".join(x.replace("_", "-") for x in sys["employment_types"])
        return f"{sys['name']} is open to {depts}, for {types} staff."

    def segments(self) -> list[tuple[int, int, bool]]:
        """Clauses; a clause where people and systems alternate ("Raj needs CRM and Tara needs VPN") is split
        further at commas and "and". The bool is the parent clause's request cue."""
        out = []
        for a, b in split_clauses(self.text):
            low = self.low[a:b]
            ents = [(m["start"], "p") for m in self.mentions if a <= m["start"] < b and m["ids"] != [self.rid]]
            ents += [(a + SYSTEM_RX[s].search(low).start(), "s") for s in self.systems_in(low)]
            kinds = [k for _, k in sorted(ents)]
            switches = sum(x != y for x, y in zip(kinds, kinds[1:]))
            grant = bool(GRANT.search(low))
            if kinds.count("p") > 1 and kinds.count("s") > 1 and switches > 1:
                pos = a
                for m in re.finditer(r",\s*|\s+and\s+", self.text[a:b]):
                    out.append((pos, a + m.start(), grant))
                    pos = a + m.end()
                out.append((pos, b, grant))
            else:
                out.append((a, b, grant))
        return [x for x in out if x[1] > x[0]]

    def build_pairs(self, exclude: set[str]) -> tuple[list[tuple[str, str]], bool, list[dict], list[str]]:
        pairs, missing, amb_all, it_issue = [], False, [], []
        prev_p, prev_s = [], []
        for a, b, parent_grant in self.segments():
            seg, low = self.text[a:b], self.low[a:b]
            ms = [m for m in self.mentions if a <= m["start"] < b]
            ids, amb = self.people(ms)
            self_named = self.rid in ids
            ids = [i for i in ids if i != self.rid and i not in exclude]
            S = self.systems_in(low)
            if REMOVAL.search(low) or NOT_REQUEST.search(low):
                prev_p, prev_s = ids or prev_p, S or prev_s
                continue
            selfish = self_named or SELF_STRONG.search(low) or (not ids and not amb and SELF_REF.search(low))
            if len(ids) + bool(selfish) > 1:
                keep = [i for i in ids if not any(
                    m["ids"] == [i] and (REPORT_AFTER.search(seg[m["end"] - a:]) or REPORT_BEFORE.search(seg[:m["start"] - a]))
                    for m in ms)]
                ids = keep if (keep or selfish) else ids
            P = ids + ([self.rid] if selfish else [])
            grant = parent_grant or GRANT.search(low)
            if amb and (S or ACCESS_WORDS.search(low)):
                amb_all += amb
                continue
            if S and not P:
                if exclude & set(prev_p) and not PRONOUN.search(low):
                    P = []
                else:
                    P = [p for p in prev_p if p not in exclude] or ([self.rid] if not exclude or SELF_REF.search(low) else [])
            if P and not S and INHERIT_SYS.search(low) and prev_s:
                S, grant = prev_s, True
            if P and S and grant:
                for p in P:
                    for s in S:
                        if (p, s) not in pairs:
                            pairs.append((p, s))
                        if IT_ISSUE.search(low):
                            it_issue.append(p)
            elif P and not S and (ACCESS_WORDS.search(low) or re.search(r"\b(?:set|sort|hook) (?:\w+ )?(?:up|out)\b", low)):
                missing = True
            prev_p, prev_s = P or prev_p, S or prev_s
        return pairs, missing, amb_all, it_issue

    def access(self, exclude: set[str]) -> bool:
        t = self.low
        lifecycle = bool(exclude)
        if not lifecycle and (PROCESS_Q.search(t) or (CLASS_WORDS.search(t) and not self.others() and not SELF_REF.search(t))):
            return False
        if not lifecycle and re.search(r"\beligib", t):
            return False
        if not lifecycle and SAME_AS.search(t):
            self.clarify("Which systems exactly do you need? I can't copy another person's access wholesale; tell me the "
                         "systems and I'll file a request for each one.")
            return True
        pairs, missing, amb, it_issue = self.build_pairs(exclude)
        if amb:
            self.ask_which(amb)
            return True
        if not pairs:
            if (missing or (VAGUE_ALL.search(t) and ASK_WORDS.search(t))) and not lifecycle:
                self.clarify("Which system do you need access to? For example CRM, TMS, BI dashboards, VPN or the code repository.")
                return True
            return False
        for eid, s in pairs:
            rec = self.lookup(eid)
            if s in rec["access"] and eid in it_issue:
                self.escalate("it", f"{rec['name']} already has {s} but reports a problem using it.")
                continue
            self.request_access(rec, s)
        return True

    def request_access(self, rec: dict, s: str) -> None:
        name, sysname = rec["name"], SYSTEMS[s]["name"]
        problems = []
        if self.rid not in (rec["id"], rec["manager_id"]):
            problems.append((f"only {name} or their direct manager can ask for access for them", "POL-ACC-01"))
        if rec["status"] == "pre_start":
            problems.append((f"{name} hasn't started yet; other systems can be requested once onboarding has started", "POL-ONB-01"))
        elif rec["status"] in ("offboarding", "terminated"):
            problems.append((f"{name} is leaving or has left (status {rec['status']})", "POL-OFF-01"))
        elif rec["status"] not in ("active", "onboarding"):
            problems.append((f"{name} has status {rec['status']}", "POL-OFF-02"))
        sys = SYSTEMS[s]
        if not problems and s in rec["access"]:
            self.answered = True
            self.parts.append(f"{name} already has {sysname}, so there's nothing to request.")
            return
        if (sys["departments"] != "all" and rec["department"] not in sys["departments"]) or rec["employment_type"] not in sys["employment_types"]:
            problems.append((f"{name} ({rec['employment_type'].replace('_', '-')}, {rec['department']}) is not eligible for "
                             f"{sysname}, and the helpdesk can't make exceptions", "POL-ACC-02"))
        if problems:
            pids = list(dict.fromkeys(p for _, p in problems))
            self.refuse(f"I can't file the {sysname} request for {name}: " + "; ".join(m for m, _ in problems) + ".", pids)
            return
        just = f"Requested by {self.me['name']}: {self.text}"
        res, err = self.ep.tool("create_access_request", {"employee_id": rec["id"], "system_id": s, "justification": just})
        if err:
            self.refuse(f"The {sysname} request for {name} was rejected: {res['error']}.")
            return
        self.done = True
        days = "about 1 business day" if sys["tier"] == "standard" else "up to 3 business days"
        self.parts.append(f"Filed {res['request_id']} for {name}: {sysname}, routed to {res['routed_to']} for approval "
                          f"({days}); access isn't granted until they sign off.")


def run_case(case: dict) -> Episode:
    return Router(case).run()
