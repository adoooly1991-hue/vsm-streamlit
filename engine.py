# engine.py
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any, Tuple
import yaml, math

@dataclass
class ProcessStep:
    id: str
    name: str
    prev_id: Optional[str] = None
    next_id: Optional[str] = None
    process_type: str = "Manual"
    ct_sec: Optional[float] = None
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
    waiting_starved_pct: Optional[float] = None
    answers: Dict[str, Any] = field(default_factory=dict)

def load_templates(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)

def ct_effective(ct_sec: float, downtime_pct: float, co_time_min: float, co_freq_per_shift: float, available_time_sec: float) -> float:
    if not ct_sec: return 0.0
    dt_factor = 1.0 / max(1e-6, (1 - (downtime_pct or 0)/100.0))
    co_loss = 0.0
    if co_time_min and co_freq_per_shift and available_time_sec:
        co_loss = (co_time_min*60.0) * co_freq_per_shift / available_time_sec
    return ct_sec*dt_factor + co_loss

def infer_throughput(ct_bottleneck_sec: float) -> float:
    return 1.0 / ct_bottleneck_sec if ct_bottleneck_sec and ct_bottleneck_sec>0 else 0.0

def waiting_from_wip(wip_units: float, ct_bottleneck_sec: float) -> float:
    th = infer_throughput(ct_bottleneck_sec)
    return (wip_units or 0)/th if th>0 else 0.0

def compute_lead_time(steps: List[ProcessStep], available_time_sec: float) -> dict:
    eff = []
    for s in steps:
        e = ct_effective(s.ct_sec or 0, s.downtime_pct or 0, s.co_time_min or 0, s.co_freq_per_shift or 0, available_time_sec)
        eff.append(e if e>0 else (s.ct_sec or 0))
    ct_bottleneck = max(eff) if eff else 0.0
    per_step = {}
    total = 0.0
    for s, e in zip(steps, eff):
        wait = waiting_from_wip(s.wip_units_in or 0, ct_bottleneck)
        rework = ((s.rework_pct or 0)/100.0) * (s.ct_sec or 0)
        tot = e + wait + rework
        per_step[s.id] = {"ct_eff_sec": round(e,2), "waiting_sec": round(wait,2), "rework_sec": round(rework,2), "total_sec": round(tot,2)}
        total += tot
    return {"lead_time_sec": round(total,2), "ct_bottleneck_sec": round(ct_bottleneck,2), "by_step": per_step}

def score_wastes(step: ProcessStep, thresholds: dict) -> Dict[str, Any]:
    scores, conf = {}, {}
    # Defects
    if step.defect_pct is not None:
        scores["defects"] = min(5.0, round((step.defect_pct / max(1e-6, thresholds["defect_pct_high"])) * 5.0, 2)); conf["defects"]="High"
    else:
        scores["defects"]=0.0; conf["defects"]="Low"
    # Waiting
    if step.waiting_starved_pct is not None:
        scores["waiting"] = min(5.0, round((step.waiting_starved_pct/ (thresholds.get("waiting_ct_ratio_high",1.0)*100)) * 5.0, 2)); conf["waiting"]="Medium"
    else:
        scores["waiting"] = 2.5 if (step.wip_units_in or 0) > thresholds["wip_units_high"] else 0.0; conf["waiting"]="Low"
    # Inventory
    scores["inventory"] = 5.0 if (step.wip_units_in or 0) > thresholds["wip_units_high"] else 0.0
    conf["inventory"] = "High" if scores["inventory"]>0 else "Low"
    # Overproduction
    scores["overproduction"] = 3.5 if (step.push_pull or "").lower()=="push" else 0.0
    conf["overproduction"] = "Medium" if scores["overproduction"]>0 else "Low"
    # Transportation
    scores["transportation"] = 4.0 if (step.layout_moves or 0)>=2 or (step.distance_m or 0)>50 else 0.0
    conf["transportation"] = "Medium" if scores["transportation"]>0 else "Low"
    # Motion
    scores["motion"] = 4.0 if (step.walk_m_per_unit or 0) > (thresholds.get("walk_m_per_unit_high",20)) else 0.0
    conf["motion"] = "Medium" if scores["motion"]>0 else "Low"
    # Overprocessing
    scores["overprocessing"] = 3.0 if step.answers.get("redundant_checks") else 0.0
    conf["overprocessing"] = "Low" if scores["overprocessing"]>0 else "Low"
    # Talent
    scores["talent"] = 3.0 if step.answers.get("underutilized_talent") else 0.0
    conf["talent"] = "Low" if scores["talent"]>0 else "Low"
    return {"scores": scores, "confidence": conf}

def rpn_like(severity_0_5: float, recurrence_hint: float, detection_hint: float) -> float:
    sev = (severity_0_5/5.0)*10.0
    rec = min(10.0, recurrence_hint)
    det = min(10.0, detection_hint)
    return (sev + rec + det) / 30.0 * 100.0

def make_observation(step: ProcessStep, waste: str, w: Dict[str,Any], tpl: dict, thresholds: dict, ctx: dict) -> Dict[str, Any]:
    score = w["scores"].get(waste,0.0); conf = w["confidence"].get(waste,"Low")
    if score <= 0: return {}
    band = "high" if score>=3.5 else "medium"
    bank = tpl["waste_templates"].get(waste,{}).get(band,[])
    if not bank: return {}
    prev_name = ctx.get("prev_name","previous step")
    text_raw = bank[0].format(
        step_name=step.name, 
        prev_step=prev_name,
        defect_pct=step.defect_pct or 0.0,
        defect_target=thresholds["defect_pct_high"],
        wait_min=(ctx.get("waiting_sec",0)/60.0),
        ct_sec=step.ct_sec or 0,
        wip_units=step.wip_units_in or 0.0,
        layout_moves=step.layout_moves or 0,
        distance_m=step.distance_m or 0,
        walk_m_per_unit=step.walk_m_per_unit or 0
    )
    wrapper_key = "high_conf" if conf=="High" else ("med_conf" if conf=="Medium" else "low_conf")
    text = tpl["observation_wrappers"][wrapper_key].format(text=text_raw)

    recurrence = 7 if (step.downtime_pct or 0) > (thresholds.get("downtime_pct_high",10)) else 4
    detection = 3 if conf=="High" else (6 if conf=="Medium" else 8)
    rpn = rpn_like(score, recurrence, detection)
    return {
        "step_id": step.id,
        "step_name": step.name,
        "waste": waste,
        "score_0_5": score,
        "confidence": conf,
        "rpn_pct": round(rpn,1),
        "observation": text
    }
