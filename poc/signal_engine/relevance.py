"""Service relevance: is the DELIVERABLE something Solvant does?

A procurement notice proves an organisation is buying *something*. It does not prove it is buying
AI, software, automation, CRM or integration work. This module decides that from direct evidence
about the deliverable, independently of buying intent.

Verdicts
  relevant       the deliverable is (or clearly includes) software / AI / workflow-automation / CRM /
                 integration / digital-system SERVICES Solvant could deliver or co-deliver
  product_only   buying a software product, licence, subscription or renewal with no service scope
                 (vendor / reseller territory; partnership at most)
  not_relevant   construction, cleaning, care or clinical services, physical equipment, hardware,
                 staffing, marketing, energy, etc., or no software evidence at all
  uncertain      evidence conflicts or the text cannot be understood reliably (e.g. non-English with
                 nothing recognisable); always sent to human review, never auto-promoted

Rules that matter
  * Generic words never establish relevance on their own: integrated, report(ing), automatic,
    automated, service, system, solution, platform, digital, management.
  * Ambiguous acronyms are resolved by context: CRM (cardiac rhythm management, certified reference
    material, radar models), API (active pharmaceutical ingredient), SMR (small modular reactor),
    ICA / SI in industrial control.
  * Hardware bought "for AI research" is hardware, not AI services.
  * TED titles start with an English CPV label ("Country – <CPV label> – <title>"); CPV codes are used
    when the source provides them. CPV alone never makes a notice relevant without text evidence,
    except IT-service CPV labels, which make it at most 'uncertain' → review.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from .models import Signal


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


# ----------------------------------------------------------------------------- positive evidence
# Each entry: (category, pattern). Patterns are deliberately specific; see module docstring.
POSITIVE = [
    ("ai", _rx(r"\bartificial[\s-]+intelligence\b|\bk(?:ü|ue)nstliche[nr]?\s+intelligenz\b|\bintelligence\s+artificielle\b|"
               r"\binteligencia\s+artificial\b|\bintelligenza\s+artificiale\b|\bkunstmatige\s+intelligentie\b|"
               r"\bsztuczn\w+\s+inteligencj\w+\b|\bintelig[êe]ncia\s+artificial\b|\binteligen[țt]\w*\s+artificial\w*\b|"
               r"\bteko[äa]ly\w*\b|\bartificiell\s+intelligens\b|\bkunstig\s+intelligens\b|\bum[ěe]l[áa]\s+inteligenc\w*\b|"
               r"\bmachine[\s-]+learning\b|\bmaschinelles\s+lernen\b|\bdeep[\s-]+learning\b|\bgenerative\s+ai\b|\bgen\s?ai\b|"
               r"\blarge\s+language\s+models?\b|\bllms?\b|\bnatural[\s-]+language\s+processing\b|\bimage[\s-]+recognition\b|"
               r"\b(?:ai|ki)[\s-]+(?:based|basierte?[nrs]?|gest(?:ü|ue)tzte?[nrs]?|powered|driven|enabled|solutions?|l(?:ö|oe)sung(?:en)?|"
               r"system|platform|plattform|assistants?|assistenten?|agents?|model(?:s|le)?)\b")),
    ("chatbot_assistant", _rx(r"\bchat[\s-]?bots?\b|\bvoice[\s-]?bots?\b|\bvirtual\s+(?:assistant|agent)s?\b|\bagent[\s-]+assist\w*\b|"
                              r"\bsprachassistent\w*\b|\bconversational\s+ai\b|\bcopilot\b")),
    ("process_automation", _rx(r"\b(?:business[\s-]+)?process(?:es)?\s+automation\b|\bworkflow\s+automation\b|\bautomate\s+(?:manual|business|our|the)?\s*(?:processes|workflows?|tasks)\b|"
                               r"\brobotic\s+process\s+automation\b|\brpa\b|\bintelligent\s+automation\b|\bpower\s+automate\b|\bpower\s+apps\b|"
                               r"\bpower\s+platform\b|\blow[\s-]?code\b|\bno[\s-]?code\b|\bn8n\b|\bzapier\b|\bmake\.com\b|"
                               r"\bautomatisierungs(?:plattform|l(?:ö|oe)sung)\w*\b|\bprozessautomatisierung\b|\bautomatisation\s+des\s+processus\b|"
                               r"\bautomatizaci[óo]n\s+de\s+procesos\b|\bautomatizzazione\s+dei\s+processi\b|\bprocesautomatisering\b|"
                               r"\bautomatyzacj\w+\s+proces\w*\b|\bautomatismos\s+desenvolvidos\b|\bautomatiser\w*\s+(?:des\s+)?processus\b|"
                               r"\bautomat\w+\s+(?:manual|manuelle?|manuali|manuales)\b")),
    ("crm_software", _rx(r"\bcrm[\s-]?(?:system\w*|systeem|software|softwarel(?:ö|oe)sung\w*|applicat\w*|applikation\w*|oplossing|"
                         r"solution|l(?:ö|oe)sung\w*|platform\w*|plattform|module|implementation|implementatie|tool|database|cloud)\b|"
                         r"\bcustomer[\s-]+relationship[\s-]+management\b|\bemployer[\s-]+relationship[\s-]+management\b|"
                         r"\bkundrelationshantering\b|\brelatiebeheer\b|\bkundenbeziehungsmanagement\b|\bgestion\s+de\s+la\s+relation\s+client\b|"
                         r"\bdynamics\s*365\b|\bmicrosoft\s+dynamics\b|\bsalesforce\b|\bhubspot\b|\bpipedrive\b|\bzoho\b|\bsap\s+sales\s+cloud\b|"
                         r"\b(?:maintenance|mantenimiento|wartung|onderhoud|support|weiterentwicklung)\s+(?:of\s+|del\s+|des\s+)?(?:the\s+|el\s+)?crm\b")),
    ("integration", _rx(r"\bsystems?\s+integration\s+(?:services|platform|layer)\b|\bintegration\s+platform\b|\bintegrationsplattform\b|"
                        r"\bdata[\s-]?integration\w*\b|\bdatenintegration\w*\b|\bapi\s+(?:integration|development|gateway|management)\b|"
                        r"\bapis?\s+(?:and|&|/)\s+(?:webhooks?|integrations?)\b|\besb\b|\benterprise\s+service\s+bus\b|\bszyn\w+\s+danych\b|"
                        r"\bmiddleware\b|\bipaas\b|\bintegrationer\b|\bintegrationsl(?:ö|oe)sung\w*\b|\binteroperab\w+\b|\binteroperacyjn\w+\b")),
    ("software_dev", _rx(r"\bsoftware\s+(?:development|implementation|solution|engineering|platform|system)s?\b|"
                         r"\b(?:application|app|web[\s-]?app(?:lication)?|portal)\s+development\b|\bbespoke\s+software\b|\bcustom\s+software\b|"
                         r"\bsoftwareentwicklung\b|\bentwicklung\s+(?:einer|der|von)\s+\w*(?:software|anwendung|plattform|applikation)\w*\b|"
                         r"\bd[ée]veloppement\s+(?:d['’]une?\s+)?(?:logiciel|application|plateforme)\w*\b|\bdesarrollo\s+de\s+(?:software|aplicaci\w+)\b|"
                         r"\bsviluppo\s+(?:software|applicativ\w+|di\s+una\s+piattaforma)\b|\bsoftwareontwikkeling\b|\bprogramvareutvikling\b|"
                         r"\bsolu[țt]i\w*\s+(?:software|informatic\w*|digital\w*)\b|\bplatform\w*\s+de\s+servicii\s+publice\s+digitale\b|"
                         r"\bdigital(?:e|en)?\s+(?:service[\s-]?plattform|serviceplattform|service\s+platform|public[\s-]+services?\s+platform)\b|"
                         r"\bcase[\s-]+management\s+(?:system|solution|software|platform)\b|\b(?:service)?[äa]rendehanteringssystem\b|"
                         r"\bcustomer\s+portal\b|\bklantportal\b|\bcms\b|\bcontent\s+management\s+system\b")),
    ("erp_software", _rx(r"\berp(?:[\s/-]?(?:crm|system\w*|software|solution|l(?:ö|oe)sung))?\b|\bsap\s+(?:erp|s/4\s?hana|analytics)\b|\bnetsuite\b|"
                         r"\baff(?:ä|a)rssystem\b|\bunit4\b")),
    ("document_processing", _rx(r"\bdocument\s+(?:processing|automation|capture|extraction|understanding)\b|\bdata\s+extraction\b|"
                                r"\bdatenextraktion\b|\bintelligent\s+document\w*\b|\bidp\b|\bocr\b|\btext\s+recognition\b")),
    ("digitalisation", _rx(r"\bdigitali[sz]ation\s+(?:strategy|programme|program|project)\b|\bdigitalisierungs(?:strategie|programm|projekt)\w*\b|"
                           r"\bdigital(?:e|en)?\s+transformation\w*\b|\btransformationsprogramm\w*\b|\bdezvoltar\w+\s+digital\w*\b|"
                           r"\bdigitaliser\w*\b|\bdigitalizaci[óo]n\b|\bdigitalizzazione\b|\bcyfryzacj\w+\b")),
    ("data_ai_platform", _rx(r"\bdata\s+(?:platform|warehouse|lake|landscape|landschap)\b|\bdatenplattform\b|\bbusiness\s+intelligence\b|"
                             r"\bpower\s+bi\b|\bdata[\s-]+quality\s+platform\b|\bdatenqualit(?:ä|ae)ts\w*\b|\bforecasting\s+system\b")),
]
POSITIVE.append(
    ("business_automation", _rx(r"\bautomat(?:e|es|ing|ion|ions|ise|ize)\s+(?:of\s+)?(?:\w+\s+){0,3}(?:invoic\w*|report\w*|crm|e-?mails?|onboarding|"
                                r"bookings?|appointments?|leads?|data\s+entry|spreadsheets?|workflows?|processes|admin\w*|bookkeeping|payroll|"
                                r"quotes?|orders?|accounts?\s+payable|documents?|tasks)\b|"
                                r"\b(?:invoic\w*|reporting|bookkeeping|onboarding|payroll|admin|finance|accounting|crm|marketing|sales|lead(?:\s+capture)?|booking|email|hr|document)\s+(?:and\s+\w+\s+)?automation\b|"
                                r"\bcrm\s+(?:consultants?|experts?|specialists?|developers?|agency|partners?|implementation|migration|set[\s-]?up)\b|"
                                r"\bconnect(?:ing)?\s+(?:our|my|the)?\s*\w*\s*(?:crm|systems?|apps?|tools?)\s+(?:to|with)\b|"
                                r"\bintegrat\w+\s+(?:\w+\s+){0,2}(?:with|into)\s+(?:our|the|existing|their)\b|"
                                r"\b(?:ai|business|workflow|process)\s+automation\b|"
                                r"\bautomation\s+(?:consultants?|agency|agencies|experts?|specialists?|developers?|partners?|builders?|freelancers?)\b|"
                                r"\b(?:zapier|make|n8n|power\s+automate)\s+(?:experts?|developers?|consultants?|specialists?|workflows?|scenarios?)\b")))

# Positive categories that, on their own, show the deliverable is a software/IT SERVICE.
SERVICE_STRONG = {"ai", "chatbot_assistant", "process_automation", "crm_software", "integration", "software_dev",
                  "document_processing", "business_automation"}

# ----------------------------------------------------------------------------- acronym traps
TRAPS = {
    "crm": _rx(r"\bcardiac\b|\brhythm\b|\belectrofisiolog\w*|\belectrophysiolog\w*|\bpacemaker\w*|\bdefibrillat\w*|\bmicroport\b|"
               r"\bcertified\s+reference\b|\breference\s+(?:material|substance|standard)s?\b|\bradar\b|\bsea\s+giraffe\b|"
               r"\bfungible\b|\bsanitari[oa]\b|\bconsumables?\b"),
    "api": _rx(r"\bactive\s+pharmaceutical\b|\bpharmaceutical\s+ingredient\b|\bpharma\w*\b"),
}
_CRM_BARE = _rx(r"\bcrm\b")
_API_BARE = _rx(r"\bapi\b")
_AI_BARE = _rx(r"\b(?:ai|ki)\b")
_AUTOMAT_GENERIC = _rx(r"\bautomat(?:ic|ically|ed|ique|ische[nrs]?|ico|ica|ismo|ismos)\b")

# ----------------------------------------------------------------------------- negative domains
NEGATIVE = [
    ("construction_works", _rx(r"\bbridge\b|\bfootbridge\b|\broof\w*\b|\bgutter\w*\b|\bwaterproofing\b|\brefurbishment\b|"
                               r"\bconstruction\s+work\w*\b|\bbuilding\s+works?\b|\bcivil\s+engineering\b|\bgeotechnical\b|\bdemolition\b|"
                               r"\bbauarbeiten\b|\bbauleistung\w*\b|\btravaux\b|\bobras\b|\blavori\b|\broboty\s+budowlane\b|\bnuclear\b|"
                               r"\breactor\b|\bpower[\s-]+station\b|\bwind\s+farm\b|\bhighways?\b|\broad\s?works\b")),
    ("cleaning_facilities", _rx(r"\bcleaning\b|\bjanitorial\b|\bhygiene\b|\blaundry\b|\bwash[\s-]?line\b|\bwaste\s+collection\b|"
                                r"\bgrounds\s+maintenance\b|\bcatering\b|\bsecurity\s+guard\w*\b|\bpest\s+control\b")),
    ("care_clinical", _rx(r"\bcare\s+(?:at\s+home|services?|homes?|provider)\b|\b(?:live-in|complex|urgent|social|residential|domiciliary)\s+care\b|"
                          r"\btreatment\b|\bnursing\b|\bclinical\b|\bpatients?\b|\bmedical\s+(?:services?|assessments?)\b|\bhealth\s+visiting\b|"
                          r"\btherap\w+\b|\bpsychosis\b|\bmental\s+health\s+service\w*\b|\bsmoking\s+cessation\b|\bpharmacy\b|\bdental\b|"
                          r"\bsight\s+testing\b|\bspectacles\b|\bscreening\s+programme\b|\bmri\b|\bprescribing\b|\brecovery\s+service\b|"
                          r"\bweight\s+management\b|\bcarers?\b|\bfostering\b|\bkinship\b|\bhomeless\w*\b|\bsupported\s+accommodation\b|"
                          r"\btenancy\s+support\b|\bmedical\s+services\b|\bmicrobiology\b|\bpathology\b|\bdiagnostic\s+(?:and\s+)?laborator\w*\b|"
                          r"\bpublic\s+health\s+nursing\b|\bdistress\s+brief\b")),
    ("hardware_equipment", _rx(r"\bturnstiles?\b|\broller\s+shutters?\b|\bautomatic\s+doors?\b|\btraffic\s+signals?\b|\bdisplay\s+equipment\b|"
                               r"\blasers?\b|\bmicroscop\w+\b|\brheometer\b|\blinear\s?motor\b|\belectric\s+motors?\b|\bradar\b|\bsatellit\w+\b|"
                               r"\bcubesat\b|\bgpu\b|\bserver\s+gpu\b|\bsupercomputer\b|\bsuper\s+computer\b|\bsensors?\b|\bkits?\b|\breagents?\b|"
                               r"\bconsumables?\b|\bapparatus\b|\banaly[sz]ers?\b|\b(?:electric|motor|fleet|utility|emergency|refuse|passenger|bus)\s+vehicles?\b|\bvehicle\s+(?:fleet|hire|lease|purchase|supply|maintenance)\b|\bbus\s+fleet\b|\bboilers?\b|\bgas\s+maintenance\b|"
                               r"\bmedical\s+(?:devices?|equipment|products)\b|\bimplants?\b|\bmotor\s+control\s+cent(?:re|er)s?\b|"
                               r"\binstrumentation\b|\bscada\b|\bplc\b|\bsemiconductor\b|\bprobing\b|\bautonomous\b|\btool\s+room\b|"
                               r"\brobot(?!ic\s+process|ics\s+process)\w*\b|\bquadruped\b|\bwarehouse\s+automation\b|\bconveyor\w*\b")),
    ("staffing", _rx(r"\btemporary\s+(?:and\s+interim\s+)?staff\w*\b|\binterim\s+staff\w*\b|\bagency\s+workers?\b|\brecruitment\s+services\b")),
    ("marketing_media", _rx(r"\badvertising\s+services\b|\bcampaign\s+(?:ideation|development|launch)\b|\bconversion\s+rate\s+optimi[sz]ation\b|"
                            r"\bmedia\s+buying\b")),
    ("research_brokerage", _rx(r"\bcompetence\s+brokers?\b|\bresearch\s+mobili[sz]ation\b")),
]
# Hardware purchase verbs: "supply/delivery of <hardware>", multilingual.
HARDWARE_SUPPLY = _rx(r"\b(?:supply|delivery|purchase|fornitura|lieferung|anschaffung|dostawa|levering|suministro|"
                      r"fourniture|leverans|anskaffelse)\b")

# ----------------------------------------------------------------------------- product vs services
PRODUCT_ONLY = _rx(r"\blicen[cs]es?\b|\blicen[cs]ing\b|\blizen[sz]\w*\b|\blicenc\w*\b|\blicen[țt]\w*\b|\bsubscriptions?\b|\bsubscrip[țt]ii\b|"
                   r"\babonnement\w*\b|\bpredplatn\w*\b|\brenewal\b|\breînnoire\b|\bverl(?:ä|a)ngerung\b|\bcommercially\s+available\b|"
                   r"\boff[\s-]the[\s-]shelf\b|\bcots\b|\bnyttjanderätt\b|\bsaas\b|\bsoftware\s+as\s+a\s+service\b|\butilizzo\s+continuativo\b")
SERVICES_SCOPE = _rx(r"\bimplement\w*\b|\binrichting\b|\beinf(?:ü|ue)hrung\b|\bintroduction\b|\bdevelop\w*\b|\bweiterentwicklung\b|\bentwicklung\b|"
                     r"\bontwikkel\w*\b|\beingef(?:ü|ue)hrt\b|\beinzuf(?:ü|ue)hrend\w*\b|\beinf(?:ü|ue)hren\b|\bwdro(?:ż|z)eni\w*\b|\bimplementa\w+\b|\bdezvoltar\w*\b|\bproiectar\w*\b|\bconfigur\w+\b|"
                     r"\bkonfigura\w+\b|\bintegra(?:tion|ting|te|rea|zione|ción|cja|tie|re)\b|\bintegrationer\b|\bmigra\w+\b|"
                     r"\bcustomi[sz]\w+\b|\bpersonaliz\w+\b|\bconsult\w*\b|\bberatung\b|\bconception\b|\bkonzeption\b|\bmise\s+en\s+place\b|"
                     r"\bsupport\s+(?:and|&)\s+(?:maintenance|development|enhancements?)\b|\benhancements?\b|\bmaintenance\s+of\s+(?:the\s+)?\w+\s+(?:crm|system|software)\b|"
                     r"\bmantenimiento\s+del\b|\bservicedesk\b|\bservice\s+desk\b|\bonderhoud\b|\bbeheer\b|\bbetrieb\b|\boperation\s+of\b|"
                     r"\bverksamhetsanpassning\b|\binf(?:ö|o)rande\b|\binstruire\b|\btraining\b|\bschulung\w*\b|\bpartner\b")

PRODUCT_TITLE = _rx(r"\b(?:tool|platform|software|licen[cs]es?|subscriptions?|package|plattform|plateforme|piattaforma|platforma)\s*$")

# ----------------------------------------------------------------------------- CPV
# TED titles: "Country – <English CPV label> – <original title>"
_TED_TITLE = re.compile(r"^[^–]+\s+–\s+(?P<cpv>[^–]+?)\s+–\s+(?P<rest>.+)$")
CPV_IT_SERVICE_LABEL = _rx(r"\bIT\s+services\b|\bsoftware(?:[\s-]related)?\s+(?:programming|development|implementation|support|maintenance|related)\b|"
                           r"\bsoftware[\s-]related\s+services\b|\bprogramming\s+services\b|\bsystems\s+and\s+technical\s+consultancy\b|"
                           r"\bcomputer[\s-]related\s+services\b|\bsoftware\s+development\s+services\b|\bsystem\s+integration\b|"
                           r"\bhelpdesk\s+and\s+support\b|\bdata\s+services\b|\bmaintenance\s+of\s+information\s+technology\s+software\b|"
                           r"\bsoftware\s+maintenance\b|\bweb[\s-]?site\s+operation\b|\bsoftware\s+supply\s+services\b")
CPV_SOFTWARE_PRODUCT_LABEL = _rx(r"\bsoftware\s+package\b|\binformation\s+systems\b")
# CPV code prefixes (when the source provides codes).
CPV_IT_SERVICE_CODES = ("72",)            # IT services
CPV_SOFTWARE_PRODUCT_CODES = ("48",)      # software packages
CPV_NON_IT_CODES = ("03", "09", "14", "15", "16", "18", "19", "22", "24", "31", "33", "34", "35", "37", "38", "39", "42", "43",
                    "44", "45", "50", "51", "55", "60", "63", "64", "65", "66", "70", "71", "75", "76", "77", "80", "85", "90", "92", "98")

_EN_STOP = _rx(r"\b(?:the|and|of|for|to|with|is|will|be|this|that|which|are|on|in|from|into|our|we|a|an|at|by|it|as|has|have|"
               r"can|need|needs|every|all|or|not|its|their|per|you|your|looking|seeking|provide|including|services?)\b")


@dataclass
class Relevance:
    verdict: str                                   # relevant / product_only / not_relevant / uncertain
    deliverable_type: str                          # software_services / software_product / hardware / works / care_or_clinical / other / unknown
    positive: list[str] = field(default_factory=list)   # "category: matched text"
    negative: list[str] = field(default_factory=list)
    traps: list[str] = field(default_factory=list)
    cpv_label: Optional[str] = None
    cpv_signal: str = "none"                       # it_services / software_product / non_it / none
    language: str = "unknown"                      # en / non_en / unknown
    uncertainty: list[str] = field(default_factory=list)
    strength: int = 0                              # number of distinct strong positive categories

    def to_dict(self) -> dict:
        return asdict(self)


def _cpv(sig: Signal) -> tuple[Optional[str], str, str]:
    """Return (cpv_label, cpv_signal, title_without_cpv_prefix)."""
    title = sig.title or ""
    label, signal = None, "none"
    m = _TED_TITLE.match(title) if sig.source == "ted" else None
    if m:
        label = m.group("cpv").strip()
        title = m.group("rest").strip()
        if CPV_IT_SERVICE_LABEL.search(label):
            signal = "it_services"
        elif CPV_SOFTWARE_PRODUCT_LABEL.search(label):
            signal = "software_product"
        else:
            signal = "non_it"
    codes = _codes((sig.raw_meta or {}).get("cpv"))
    if codes and signal == "none":
        if any(c.startswith(CPV_IT_SERVICE_CODES) for c in codes):
            signal = "it_services"
        elif any(c.startswith(CPV_SOFTWARE_PRODUCT_CODES) for c in codes):
            signal = "software_product"
        elif all(c.startswith(CPV_NON_IT_CODES) for c in codes):
            signal = "non_it"
    return label, signal, title


def _codes(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = [v]
    out = []
    for x in v:
        if isinstance(x, dict):
            x = x.get("id") or x.get("code") or ""
        s = re.sub(r"\D", "", str(x))
        if len(s) >= 2:
            out.append(s)
    return out


def _hits(rules: Iterable[tuple[str, re.Pattern[str]]], text: str) -> list[tuple[str, str]]:
    out = []
    for name, rx in rules:
        m = rx.search(text)
        if m:
            out.append((name, m.group(0)))
    return out


def assess(sig: Signal) -> Relevance:
    cpv_label, cpv_signal, title = _cpv(sig)
    body = sig.text or ""
    text = f"{title}\n{body}"

    traps = []
    pos = _hits(POSITIVE, text)
    # Resolve acronym traps: drop CRM / API evidence when the context says it is not software.
    if TRAPS["crm"].search(text) and _CRM_BARE.search(text):
        traps.append(f"CRM in non-software context ('{TRAPS['crm'].search(text).group(0)}')")
        pos = [(c, m) for c, m in pos if not (c == "crm_software" and "crm" in m.lower() and not re.search(
            r"dynamics|salesforce|hubspot|pipedrive|zoho|relationship|relatie|kundrelation", m, re.I))]
    if TRAPS["api"].search(text) and _API_BARE.search(text):
        traps.append("API in pharmaceutical context")
        pos = [(c, m) for c, m in pos if "api" not in m.lower()]
    neg = _hits(NEGATIVE, f"{cpv_label or ''}\n{text}")
    neg_title = _hits(NEGATIVE, title)
    pos_title = _hits(POSITIVE, title)

    strong = sorted({c for c, _ in pos if c in SERVICE_STRONG})
    weak_ai = bool(_AI_BARE.search(text))
    product = PRODUCT_ONLY.search(text)
    services = SERVICES_SCOPE.search(text)
    hardware_hits = [m for c, m in neg if c == "hardware_equipment"]

    en = len(_EN_STOP.findall(text))
    words = max(1, len(re.findall(r"\w+", text)))
    language = "en" if en / words > 0.06 else ("non_en" if words > 12 else "unknown")

    r = Relevance(verdict="not_relevant", deliverable_type="unknown",
                  positive=[f"{c}: {m}" for c, m in pos], negative=[f"{c}: {m}" for c, m in neg],
                  traps=traps, cpv_label=cpv_label, cpv_signal=cpv_signal, language=language, strength=len(strong))

    neg_cats = {c for c, _ in neg}
    neg_title_cats = {c for c, _ in neg_title}

    # 1. A non-software domain in the TITLE, without strong software evidence in the title, is decisive.
    if neg_title_cats and not {c for c, _ in pos_title} & SERVICE_STRONG:
        r.deliverable_type = _domain_type(neg_title_cats)
        r.verdict = "not_relevant"
        return r
    # 2. Hardware purchase (e.g. "GPU server for AI research"): the AI is the context, not the deliverable.
    if hardware_hits and (cpv_signal == "non_it" or HARDWARE_SUPPLY.search(text)) and not (
            {c for c, _ in pos_title} & SERVICE_STRONG and services):
        r.deliverable_type = "hardware"
        r.verdict = "not_relevant"
        return r
    # 3. Strong software/AI/automation evidence.
    if strong or ({c for c, _ in pos} & {"erp_software", "digitalisation", "data_ai_platform"}):
        if neg_cats & {"care_clinical", "construction_works", "cleaning_facilities"} and not pos_title:
            # e.g. a clinical service delivered "via digital tools": the clinical service is the deliverable
            r.deliverable_type = _domain_type(neg_cats)
            r.verdict = "not_relevant"
            r.uncertainty.append("software terms appear only as part of a non-software service")
            return r
        if (product or PRODUCT_TITLE.search(title)) and not services:
            r.deliverable_type = "software_product"
            r.verdict = "product_only"
            return r
        if cpv_signal == "software_product" and not services:
            r.deliverable_type = "software_product"
            r.verdict = "product_only"
            return r
        r.deliverable_type = "software_services"
        if strong:
            r.verdict = "relevant"
        else:
            # only ERP / digitalisation / data-platform evidence: real but less specific
            r.verdict = "relevant" if services else "uncertain"
            if not services:
                r.uncertainty.append("software domain present but no service scope stated")
        return r
    # 4. No strong evidence.
    if cpv_signal == "non_it" or traps:
        # The official (English) CPV label describes a non-IT deliverable, or the only "software" word was an
        # acronym trap: with no software evidence in the text, that is evidence against relevance.
        r.deliverable_type = _domain_type(neg_cats) if neg_cats else "other"
        r.verdict = "not_relevant"
        if cpv_label:
            r.negative.append(f"cpv_label: {cpv_label}")
        return r
    if neg_cats:
        r.deliverable_type = _domain_type(neg_cats)
        r.verdict = "not_relevant"
        return r
    if cpv_signal in ("it_services", "software_product"):
        if product and not services:
            r.deliverable_type = "software_product"
            r.verdict = "product_only"
            return r
        r.deliverable_type = "software_services" if cpv_signal == "it_services" else "software_product"
        r.verdict = "uncertain"
        r.uncertainty.append(f"IT CPV classification ('{cpv_label or 'code'}') but the deliverable is not described clearly"
                             + (" — non-English text" if language == "non_en" else ""))
        return r
    if weak_ai or _AUTOMAT_GENERIC.search(text):
        r.verdict = "uncertain" if language != "en" else "not_relevant"
        r.uncertainty.append("only generic 'AI'/'automatic' wording; no concrete software deliverable")
        return r
    if language == "non_en":
        r.verdict = "uncertain"
        r.uncertainty.append("non-English text with no recognisable software or non-software terms; technical requirement not understood reliably")
        return r
    r.deliverable_type = "other"
    r.verdict = "not_relevant"
    return r


def _domain_type(cats: set[str]) -> str:
    if "care_clinical" in cats:
        return "care_or_clinical"
    if "construction_works" in cats:
        return "works"
    if "hardware_equipment" in cats:
        return "hardware"
    return "other"
