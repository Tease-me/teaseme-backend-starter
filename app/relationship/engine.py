import math
from dataclasses import dataclass

def clamp(x, a, b): return max(a, min(b, x))

def sat_up(x: float, delta: float, k: float = 0.025) -> float:
    if delta <= 0: return x
    return x + (100 - x) * (1 - math.exp(-k * delta))

def sat_down(x: float, delta: float, k: float = 0.08) -> float:
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
    state: str
    can_ask_gf: bool

def compute_state(trust, closeness, attraction, safety, prev_state):
    if prev_state == "BROKEN":
        return "BROKEN"
    if safety < 35:
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

def update_relationship(trust, closeness, attraction, safety, prev_state, sig: Signals) -> RelOut:
    trust_pos = 8*sig.support + 6*sig.respect + 4*sig.apology
    trust_neg = 14*sig.rude + 18*sig.boundary_push

    close_pos = 7*sig.affection + 6*sig.support
    close_neg = 8*sig.rude

    attr_pos = 10*sig.flirt*sig.respect + 4*sig.affection
    attr_neg = 16*sig.boundary_push + 10*sig.rude

    safety_pos = 10*sig.respect + 6*sig.apology
    safety_neg = 22*sig.boundary_push + 14*sig.rude

    trust = sat_up(trust, trust_pos); trust = sat_down(trust, trust_neg)
    closeness = sat_up(closeness, close_pos); closeness = sat_down(closeness, close_neg)
    attraction = sat_up(attraction, attr_pos); attraction = sat_down(attraction, attr_neg)
    safety = sat_up(safety, safety_pos); safety = sat_down(safety, safety_neg)

    trust = clamp(trust, 0, 100)
    closeness = clamp(closeness, 0, 100)
    attraction = clamp(attraction, 0, 100)
    safety = clamp(safety, 0, 100)

    state = compute_state(trust, closeness, attraction, safety, prev_state)
    ask = can_ask_gf(trust, closeness, attraction, safety, state)

    def cap(x, max_val):
        return min(x, max_val)

    trust_pos  = cap(trust_pos, 5)
    close_pos  = cap(close_pos, 5)
    attr_pos   = cap(attr_pos, 4)
    safety_pos = cap(safety_pos, 3)

    trust_neg  = cap(trust_neg, 8)
    close_neg  = cap(close_neg, 6)
    attr_neg   = cap(attr_neg, 8)
    safety_neg = cap(safety_neg, 10)
    return RelOut(trust, closeness, attraction, safety, state, ask)