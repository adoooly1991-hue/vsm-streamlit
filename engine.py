# engine.py
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import math, yaml
from copy import deepcopy

@dataclass
class ProcessStep:
    id: str
    name: str
    process_type: str = "Manual"
    ct_sec: Optional[float] = None
    units_per_period: Optional[float] = None
    wip_units_in: Optional[float] = None
    defect_pct: Optional[float] = None
    rework_pct: Optional[float] = None
    downtime_pct: Optional[float] = None
    safety_incidents: Optional[int] = None
    push_pull: Optional[str] = None
    co_freq_per_shift: Optional[float] = None
    co_time_min: Optional[float] = None
    operators: Optional[int] = None
    distance_m: Optional[float] = None
    layout_moves: Optional[int] = None
    walk_m_per_unit: Optional[float] = None
    approval_delays_min: Optional[float] = None
    waiting_starved_pct: Optional[float] = None
    answers: Dict[str, Any] = field(default_factory=dict)

@dataclass
class WasteScores:
    step_id: str
    scores: Dict[str, float]
    confidence: Dict[str, str]

class VSMMath:
    @staticmethod
    def infer_throughput(ct_bottleneck_sec: float) -> float:
        if not ct_bottleneck_sec or ct_bottleneck_sec <= 0:
            return 0.0
        return 1.0 / ct_bottleneck_sec

    @staticmethod
    def waiting_time_from_wip(wip_units: float, ct_bottleneck_sec: float) -> float:
        th = VSMMath.infer_throughput(ct_bottleneck_sec)
        if th <= 0 or not wip_units:
            return 0.0
        return wip_units / th

    @staticmethod
    def ct_effective(ct_sec: float, downtime_pct: float, co_time_min: float, co_freq_per_shift: float, available_time_sec: float) -> float:
        if not ct_sec:
            return 0.0
        dt_factor = 1.0
        if downtime_pct is not None:
            dt_factor = 1.0 / max(1e-6, (1 - downtime_pct/100.0))
        co_loss = 0.0
        if co_time_min and co_freq_per_shift and available_time_sec:
            co_loss = (co_time_min*60.0) * co_freq_per_shift / available_time_sec
        return ct_sec * dt_factor + co_loss

def load_rules(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

def score_wastes(step: ProcessStep, rules: dict) -> WasteScores:
    scores = {}
    conf = {}
    wastes = rules.get("wastes", {})
    for waste_name, cfg in wastes.items():
        qlist = cfg.get("questions", [])
        total_weight = sum([q.get("weight",1) for q in qlist])
        true_weight = 0
        measured_flags = 0
        answered_flags = 0
        for q in qlist:
            qid = q["id"]
            weight = q.get("weight", 1)
            val = step.answers.get(qid, None)
            if val is None:
                # Attempt auto-infer from metrics
                if waste_name == "defects" and step.defect_pct and step.defect_pct >= 3:
                    val = True
                    measured_flags += 1
                elif waste_name == "waiting" and step.waiting_starved_pct and step.waiting_starved_pct >= 10:
                    val = True
                    measured_flags += 1
            else:
                answered_flags += 1
            if bool(val):
                true_weight += weight
        score_val = min(5.0, round(true_weight * (5.0 / max(1,total_weight)), 2))
        scores[waste_name] = score_val
        if measured_flags > 0 and answered_flags == 0:
            conf[waste_name] = "High"
        elif measured_flags > 0 and answered_flags > 0:
            conf[waste_name] = "Medium"
        else:
            conf[waste_name] = "Low"
    return WasteScores(step_id=step.id, scores=scores, confidence=conf)

def compute_lead_time(steps: List[ProcessStep], available_time_sec: float) -> dict:
    if not steps:
        return {"lead_time_sec": 0, "by_step": {}}
    ct_eff_list = []
    for s in steps:
        ct_eff = VSMMath.ct_effective(s.ct_sec or 0, s.downtime_pct or 0, s.co_time_min or 0, s.co_freq_per_shift or 0, available_time_sec)
        ct_eff_list.append(ct_eff if ct_eff>0 else (s.ct_sec or 0))
    ct_bottleneck = max(ct_eff_list) if ct_eff_list else 0.0
    lead_time = 0.0
    by_step = {}
    for s, ct_eff in zip(steps, ct_eff_list):
        waiting = VSMMath.waiting_time_from_wip(s.wip_units_in or 0.0, ct_bottleneck)
        rework_time = (s.rework_pct or 0)/100.0 * (s.ct_sec or 0)
        total_step_time = ct_eff + waiting + rework_time
        by_step[s.id] = {"ct_eff_sec": ct_eff, "waiting_sec": waiting, "rework_sec": rework_time, "total_sec": total_step_time}
        lead_time += total_step_time
    return {"lead_time_sec": round(lead_time,2), "by_step": by_step, "ct_bottleneck_sec": ct_bottleneck}
