import math
from dataclasses import dataclass

def clamp(x, a, b): return max(a, min(b, x))

def sat_up(x: float, delta: float, k: float = 0.015) -> float:
    if delta <= 0: return x
    return x + (100 - x) * (1 - math.exp(-k * delta))

def sat_down(x: float, delta: float, k: float = 0.03) -> float:
    if delta <= 0: return x
    return x - x * (1 - math.exp(-k * delta))

@dataclass
class Signals:
    support: float = 0.0
    affection: float = 0.0
    flirt: float = 0.0
    respect: float = 0.0
    rude: float = 0.0
    boundary_push: float = 0.0
    dislike: float = 0.0
    hate: float = 0.0
    apology: float = 0.0
    commitment_talk: float = 0.0
    accepted_exclusive: bool = False
    accepted_girlfriend: bool = False

@dataclass
class RelOut:
    trust: float
    closeness: float
    attraction: float
    safety: float

def compute_state(trust, closeness, attraction, safety, prev_state):
    if prev_state == "BROKEN":
        return "BROKEN"

    if prev_state == "STRAINED":
        if safety < 45:
            return "STRAINED"
    if safety < 30:
        return "STRAINED"
    if trust > 80 and closeness > 75 and attraction > 70 and safety > 75:
        return "DATING"
    if attraction > 55 and closeness > 45 and safety > 55:
        return "FLIRTING"
    if closeness > 35 and trust > 35:
        return "TALKING"
    return "STRANGERS"

def can_ask_gf(trust, closeness, attraction, safety, state):
    return state == "DATING" and safety >= 70 and trust >= 75 and closeness >= 70 and attraction >= 65

def update_relationship(trust, closeness, attraction, safety, sig: Signals) -> RelOut:
    trust_pos = 5*sig.support + 4*sig.respect + 3*sig.apology
    trust_neg = 9*sig.rude + 12*sig.boundary_push

    close_pos = 4*sig.affection + 4*sig.support
    close_neg = 5*sig.rude

    attr_pos = 5*sig.flirt*sig.respect + 1.5*sig.flirt + 2*sig.affection
    attr_neg = 10*sig.boundary_push + 6*sig.rude

    safety_pos = 6*sig.respect + 4*sig.apology
    safety_neg = 10*sig.boundary_push + 8*sig.rude

    def cap(x, max_val): return min(x, max_val)

    trust_pos  = cap(trust_pos, 2.0); trust_neg  = cap(trust_neg, 3.5)
    close_pos  = cap(close_pos, 2.0); close_neg  = cap(close_neg, 3.0)
    attr_pos   = cap(attr_pos, 1.8);  attr_neg   = cap(attr_neg, 3.5)
    safety_pos = cap(safety_pos, 1.5); safety_neg = cap(safety_neg, 3.5)

    trust = sat_up(trust, trust_pos); trust = sat_down(trust, trust_neg)
    closeness = sat_up(closeness, close_pos); closeness = sat_down(closeness, close_neg)
    attraction = sat_up(attraction, attr_pos); attraction = sat_down(attraction, attr_neg)
    safety = sat_up(safety, safety_pos); safety = sat_down(safety, safety_neg)

    trust = clamp(trust, 0, 100)
    closeness = clamp(closeness, 0, 100)
    attraction = clamp(attraction, 0, 100)
    safety = clamp(safety, 0, 100)

    return RelOut(trust, closeness, attraction, safety)