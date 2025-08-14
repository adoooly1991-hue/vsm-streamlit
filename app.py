# app.py
import streamlit as st, pandas as pd
from engine import ProcessStep, load_templates, compute_lead_time, score_wastes, make_observation
from report import export_observations_pptx, export_observations_pdf

st.set_page_config(page_title="VSM Observation Engine (Form)", layout="wide")
st.title("VSM Observation Engine — Manual Entry (No CSV)")
st.caption("Enter up to 10 process touchpoints. The engine computes wastes and auto-writes observations.")

with st.sidebar:
    st.header("Global Settings")
    spacing_mode = st.selectbox('Spacing on map uses', ['Effective CT', 'WIP'], index=0)
    n_steps = st.number_input("Number of process steps", min_value=1, max_value=10, value=3, step=1)
    available_time_hr = st.number_input("Available time per shift (hours)", min_value=0.5, max_value=24.0, value=8.0, step=0.5)
    templates = load_templates("templates.yaml")

st.header("Process Data (matches your OE template fields)")
steps = []
for i in range(int(n_steps)):
    with st.expander(f"Process {i+1}", expanded=(i==0)):
        id_val = f"P{i+1}"
        name = st.text_input(f"{id_val} Name", value=f"Process {i+1}")
        c1, c2, c3 = st.columns(3)
        n_touch = c1.number_input(f"{id_val} N.Touch points", min_value=0, value=13, step=1)
        ct_min = c2.number_input(f"{id_val} Cycle time (min)", min_value=0.0, value=70.0, step=1.0)
        ptype = c3.selectbox(f"{id_val} Process type", ["Manual","Semi-auto","Auto"], index=0)
        c4, c5, c6 = st.columns(3)
        downtime = c4.number_input(f"{id_val} Unplanned downtime (%)", min_value=0.0, value=7.0, step=0.5)
        defects = c5.number_input(f"{id_val} % defects", min_value=0.0, value=5.0, step=0.5)
        safety = c6.number_input(f"{id_val} N.safety issues", min_value=0, value=0, step=1)
        c7, c8, c9 = st.columns(3)
        rework = c7.number_input(f"{id_val} % rework rate", min_value=0.0, value=13.0, step=0.5)
        wip = c8.number_input(f"{id_val} WIP (units)", min_value=0.0, value=400.0, step=1.0)
        push_pull = c9.selectbox(f"{id_val} Push / Pull", ["Pull","Push"], index=0)
        c10, c11, c12 = st.columns(3)
        chg_freq = c10.number_input(f"{id_val} Changeover frequency (per shift)", min_value=0.0, value=5.0, step=0.5)
        chg_time = c11.number_input(f"{id_val} Changeover time (min)", min_value=0.0, value=50.0, step=1.0)
        operators = c12.number_input(f"{id_val} N.operators", min_value=0, value=8, step=1)

        c13, c14, c15 = st.columns(3)
        distance_m = c13.number_input(f"{id_val} Distance (m)", min_value=0.0, value=30.0, step=1.0)
        layout_moves = c14.number_input(f"{id_val} Layout moves (#)", min_value=0, value=1, step=1)
        walk_m = c15.number_input(f"{id_val} Walk (m/unit)", min_value=0.0, value=10.0, step=1.0)

        waiting_starved = st.number_input(f"{id_val} Waiting/starved time (% of available)", min_value=0.0, value=5.0, step=0.5)

        step = ProcessStep(
            id=id_val,
            name=name,
            prev_id=f"P{i}" if i>0 else None,
            next_id=f"P{i+2}" if i<int(n_steps)-1 else None,
            process_type=ptype,
            ct_sec=ct_min*60.0,
            wip_units_in=wip,
            defect_pct=defects,
            rework_pct=rework,
            downtime_pct=downtime,
            safety_incidents=safety,
            push_pull=push_pull,
            co_freq_per_shift=chg_freq,
            co_time_min=chg_time,
            operators=operators,
            distance_m=distance_m,
            layout_moves=layout_moves,
            walk_m_per_unit=walk_m,
            waiting_starved_pct=waiting_starved
        )
        steps.append(step)

st.header("Compute & Generate")
if st.button("Generate observations"):
    # Lead time
    result = compute_lead_time(steps, available_time_sec=available_time_hr*3600.0)
    st.success(f"Lead time (sec): {result['lead_time_sec']} | Bottleneck CT (sec): {result['ct_bottleneck_sec']}")

    # Observations
    import pandas as pd
    obs_rows = []
    id_to_name = {s.id: s.name for s in steps}
    for idx, s in enumerate(steps):
        w = score_wastes(s, templates["thresholds"])
        ctx = {"prev_name": id_to_name.get(steps[idx-1].id) if idx>0 else None,
               "waiting_sec": result["by_step"].get(s.id,{}).get("waiting_sec",0.0)}
        for waste in ["defects","waiting","inventory","overproduction","transportation","motion","overprocessing","talent"]:
            row = make_observation(s, waste, w, templates, templates["thresholds"], ctx)
            if row: obs_rows.append(row)
    obs = pd.DataFrame(obs_rows)
    if obs.empty:
        st.warning("No observations generated. Adjust values or thresholds.")
    else:
        obs = obs.sort_values(["rpn_pct","score_0_5"], ascending=False).reset_index(drop=True)
        st.dataframe(obs)


        # Compute effective CT per step for spacing (same logic as lead-time calc)
        ct_eff_map = {sid: result["by_step"].get(sid,{}).get("ct_eff_sec", 0.0) for sid in result["by_step"].keys()}

        # Export buttons
        from report import export_observations_pptx, export_observations_pdf
        
if st.button("Export PPTX"):
    # Build per-step top-2 wastes map for the Current State Map slide (auto-assigned)
    perstep_top2 = {}
    from engine import score_wastes
    for s in steps:
        w = score_wastes(s, templates["thresholds"])
        # sort wastes by score desc and pick top 2
        ranked = sorted(list(w["scores"].items()), key=lambda kv: kv[1], reverse=True)
        top2 = [(name, score) for name, score in ranked if score > 0][:2]
        perstep_top2[s.id] = top2

    # Compute effective CT per step for spacing (same logic as lead-time calc)
    ct_eff_map = {sid: result["by_step"].get(sid, {}).get("ct_eff_sec", 0.0) for sid in result["by_step"].keys()}

    path = export_observations_pptx(
        obs,
        "observations_manual.pptx",
        steps=steps,
        perstep_top2=perstep_top2,
        spacing_mode=spacing_mode,
        ct_eff_map=ct_eff_map
    )
    st.success(f"PPTX exported: {path}")
    with open(path, "rb") as f:
        st.download_button("Download PPTX", f, file_name="observations_manual.pptx")

        if st.button("Export PDF"):
            path = export_observations_pdf(obs, "observations_manual.pdf")
            with open(path, "rb") as f:
                st.download_button("Download PDF", f, file_name="observations_manual.pdf", mime="application/pdf")
else:
    st.info("Fill the forms above, then click 'Generate observations'.")

st.markdown("---")
st.caption("Fields mirror the OE template data boxes so you don't need CSV uploads.")
