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
    Keyword(r"\b(young|little|small)\s*(boy|girl|kid|child)\b", "CSAM", "HIGH"),
    Keyword(r"\bunder\s*age\b", "CSAM", "HIGH"),
    Keyword(r"\b(pre)?teen\b", "CSAM", "HIGH"),
    Keyword("minor", "CSAM", "MEDIUM", is_regex=False),  
    Keyword(r"\b(child|kid|underage)\s*(porn|sex|naked)\b", "CSAM", "CRITICAL"),
    
    Keyword(r"\b(dog|horse|animal)\s*(sex|fuck|cock|dick)\b", "BESTIALITY", "HIGH"),
    Keyword("bestiality", "BESTIALITY", "CRITICAL", is_regex=False), 
    Keyword("zoophilia", "BESTIALITY", "CRITICAL", is_regex=False), 
    Keyword(r"\bzoophil", "BESTIALITY", "CRITICAL"),
    Keyword(r"\bk9\s*(sex|fuck|love)\b", "BESTIALITY", "CRITICAL"),
    
    Keyword(r"\b(buy|sell|score|get|grab|cop|pick\s*up)\s*(meth|coke|cocaine|heroin|fentanyl|mdma|ecstasy|molly|ice|crystal|crack|oxy|xanax|percs|lean|dope)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(buy|sell|score|get|need|want)\b.{0,20}\b(meth|coke|cocaine|heroin|fentanyl|mdma|ecstasy|molly|crack|oxy|xanax|percs|dope)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(plug|connect|dealer|trap|trapping|pushing|slinging)\b", "DRUGS", "MEDIUM"),
    Keyword(r"\b(gram|grams|g|oz|ounce|pound|lb|zip|ball|8ball|eight\s*ball|quarter|half|qp)\s*(of)?\s*(coke|meth|weed|dope|blow|snow|ice|crystal)?\b", "DRUGS", "MEDIUM"),
    Keyword(r"\$\d+\s*(a|per|for)\s*(g|gram|oz|ounce|zip|ball|pound)", "DRUGS", "HIGH"),
    Keyword(r"\b(where\s*(can|to)\s*(i|we)\s*(get|buy|score|find))\b.*\b(meth|coke|heroin|molly|pills|xans|percs)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(got|have|holding|selling)\s*(any|some)?\s*(meth|coke|heroin|molly|pills|xans|percs|ice|crystal)\b", "DRUGS", "HIGH"),
    Keyword(r"\b(hit\s*(me|my)\s*(up|dm|line)|dm\s*me|text\s*me)\b.*\b(plug|supply|stuff|product|pack)\b", "DRUGS", "MEDIUM"),
    Keyword(r"\b(ship|mail|deliver|drop\s*off)\s*(the)?\s*(pack|product|stuff|order)\b", "DRUGS", "HIGH"),
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
