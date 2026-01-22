import re
from dataclasses import dataclass
from typing import List, Optional


LEET_MAP = {
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's',
    '7': 't', '8': 'b', '@': 'a', '$': 's', '!': 'i',
    '+': 't', '(': 'c', ')': 'o', '|': 'l', '¡': 'i',
}


@dataclass
class Keyword:
    pattern: str
    category: str
    severity: str
    is_regex: bool = True


@dataclass
class KeywordMatch:
    pattern: str
    category: str
    severity: str
    matched_text: str


KEYWORDS = [
    Keyword(r"\b(child|kid|underage)\s*(porn|sex|naked|nude|pics|pictures|photos|vids|videos)\b", "CSAM", "CRITICAL"),
    Keyword("cheese pizza", "CSAM", "CRITICAL", is_regex=False),
    Keyword(r"\bpedo(phile|philia)?\b", "CSAM", "CRITICAL"),
    Keyword("jailbait", "CSAM", "CRITICAL", is_regex=False),
    Keyword(r"\bc\s*p\b", "CSAM", "HIGH"),
    Keyword(r"\bloli(con|ta)?\b", "CSAM", "HIGH"),
    Keyword(r"\bshota(con)?\b", "CSAM", "HIGH"),
    Keyword(r"\bcunnys?\b", "CSAM", "HIGH"),
    Keyword(r"\bhebe(phile|philia)?\b", "CSAM", "HIGH"),
    Keyword(r"\b(young|little|small)\s*(boy|girl|kid|child)\b", "CSAM", "MEDIUM"),
    Keyword(r"\bunder\s*age\b", "CSAM", "MEDIUM"),
    Keyword(r"\b(pre)?teen\b", "CSAM", "MEDIUM"),
    Keyword("minor", "CSAM", "MEDIUM", is_regex=False),
    Keyword(r"\b(send|show)\s*(me|us)?\s*(pics|pictures|photos|nudes)\b.*\b(young|little|teen|school)\b", "CSAM", "HIGH"),
    Keyword(r"\b(how\s*old|what.*age|are\s*you\s*\d+)\b.*\b(sexy|hot|cute|pretty)\b", "CSAM", "MEDIUM"),
    Keyword(r"\bdon'?t\s*tell\s*(your\s*)?(mom|dad|parents|anyone)\b", "CSAM", "MEDIUM"),
    Keyword(r"\b(our|this\s*is)\s*(little\s*)?(secret)\b", "CSAM", "MEDIUM"),
    Keyword(r"\b(are\s*you|you're?|u\s*r?)\s*\d{1,2}\s*(years?\s*old|yo|y\.?o\.?)?\b", "CSAM", "MEDIUM"),
    Keyword(r"\bi'?m\s*\d{1,2}\s*(years?\s*old|yo|y\.?o\.?)?\b", "CSAM", "MEDIUM"),
    
    Keyword("bestiality", "BESTIALITY", "CRITICAL", is_regex=False),
    Keyword("zoophilia", "BESTIALITY", "CRITICAL", is_regex=False),
    Keyword("zoophile", "BESTIALITY", "CRITICAL", is_regex=False),
    Keyword(r"\bzoophil", "BESTIALITY", "CRITICAL"),
    Keyword(r"\bk9\s*(sex|fuck|love|lover)\b", "BESTIALITY", "CRITICAL"),
    Keyword(r"\bzoo\s*(porn|sex|content|stuff|vids?|videos?|pics?)\b", "BESTIALITY", "CRITICAL"),
    Keyword(r"\bartof\s*zoo\b", "BESTIALITY", "CRITICAL"),
    Keyword(r"\b(feral|beast)\s*(porn|sex|fuck)\b", "BESTIALITY", "HIGH"),
    Keyword(r"\b(dog|horse|animal|pet|canine|k9|mare|stallion)\s*(sex|fuck|cock|dick|knot|mate|mounting)\b", "BESTIALITY", "HIGH"),
    Keyword(r"\b(dog|horse|animal)\s*lover\b.*\b(sex|fuck|mate)\b", "BESTIALITY", "HIGH"),
    Keyword(r"\bknott?(ing|ed)\b.*\b(dog|k9|canine)\b", "BESTIALITY", "MEDIUM"),
    Keyword(r"\b(red\s*rocket)\b", "BESTIALITY", "MEDIUM"),
    
    Keyword(r"\b(buy|sell|score|get|grab|cop|pick\s*up)\s*(meth|coke|cocaine|heroin|fentanyl|mdma|ecstasy|molly|ice|crystal|crack|oxy|xanax|percs|lean|dope)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(buy|sell|score|get|need|want)\b.{0,30}\b(meth|coke|cocaine|heroin|fentanyl|mdma|ecstasy|molly|crack|oxy|xanax|percs|dope)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(snow|blow|white|charlie|yayo|nose\s*candy)\b.{0,20}\b(buy|sell|score|get|gram|line)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(h|horse|smack|black\s*tar|china\s*white)\b.{0,20}\b(buy|sell|score|needle|shoot|inject)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(tina|t|glass|ice|crystal)\b.{0,20}\b(buy|sell|score|smoke|pipe)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(bars|xans|benzos|footballs)\b.{0,20}\b(buy|sell|score|pop)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(perc|roxy|oxy|blues|30s|thirties)\b.{0,20}\b(buy|sell|get|pop)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(fent|fenny|fetty)\b", "DRUGS", "MEDIUM"),
    Keyword(r"\b(plug|connect|dealer|trap|trapping|pushing|slinging|re-?up)\b", "DRUGS", "MEDIUM"),
    Keyword(r"\b(gram|grams|g|oz|ounce|pound|lb|zip|ball|8ball|eight\s*ball|quarter|half|qp)\s*(of)?\s*(coke|meth|weed|dope|blow|snow|ice|crystal|white|h|boy)?\b", "DRUGS", "MEDIUM"),
    Keyword(r"\$\d+\s*(a|per|for)\s*(g|gram|oz|ounce|zip|ball|pound|line)", "DRUGS", "HIGH"),
    Keyword(r"\b(where\s*(can|to)\s*(i|we)\s*(get|buy|score|find|cop))\b.*\b(meth|coke|heroin|molly|pills|xans|percs|blow|snow|h|white)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(got|have|holding|selling)\s*(any|some)?\s*(meth|coke|heroin|molly|pills|xans|percs|ice|crystal|blow|snow|white)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(hit\s*(me|my)\s*(up|dm|line)|dm\s*me|text\s*me|hmu)\b.*\b(plug|supply|stuff|product|pack|work)\b", "DRUGS", "MEDIUM"),
    Keyword(r"\b(ship|mail|deliver|drop\s*off)\s*(the)?\s*(pack|product|stuff|order|work)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(girl|white\s*girl|soft|hard|yay|yeyo)\b.{0,15}\b(price|cost|much|buy|sell)\b", "DRUGS", "MEDIUM"),
    Keyword(r"\b(boy|d|dope|dog\s*food)\b.{0,15}\b(price|cost|much|buy|sell|shoot|nod)\b", "DRUGS", "MEDIUM"),
]


def normalize_text(text: str) -> str:
    text = text.lower()
    
    normalized = []
    for char in text:
        normalized.append(LEET_MAP.get(char, char))
    text = ''.join(normalized)
    
    text = re.sub(r'(?<=\w)[.\s_\-*]+(?=\w)', '', text)
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)
    
    return text


def compile_patterns(keywords: List[Keyword]) -> List[tuple]:
    compiled = []
    for kw in keywords:
        if kw.is_regex:
            try:
                pattern = re.compile(kw.pattern, re.IGNORECASE)
            except re.error:
                continue
        else:
            escaped = re.escape(kw.pattern.lower())
            pattern = re.compile(rf'\b{escaped}\b', re.IGNORECASE)
        
        compiled.append((pattern, kw))
    
    return compiled


_COMPILED_PATTERNS = None

def get_compiled_patterns() -> List[tuple]:
    global _COMPILED_PATTERNS
    if _COMPILED_PATTERNS is None:
        _COMPILED_PATTERNS = compile_patterns(KEYWORDS)
    return _COMPILED_PATTERNS


def check_keywords(message: str) -> Optional[KeywordMatch]:
    normalized = normalize_text(message)
    original_lower = message.lower()
    
    compiled = get_compiled_patterns()
    
    matches = []
    for pattern, kw in compiled:
        match = pattern.search(normalized) or pattern.search(original_lower)
        if match:
            matches.append(KeywordMatch(
                pattern=kw.pattern,
                category=kw.category,
                severity=kw.severity,
                matched_text=match.group(0)
            ))
    
    if not matches:
        return None
    
    severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    matches.sort(key=lambda m: severity_order.get(m.severity, 99))
    
    return matches[0]
