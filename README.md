# Automated VSM (v3)

**What’s new**
- PPTX exports with **Material & Information lanes**, arrows, and **Pull (Kanban) icons**.
- Waste scores now include a **confidence** level.
- PDF export with **template-style** process data boxes.

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Cloud
- Main file: `app.py`
- Python 3.10+

## CSV schema
See `sample_data.csv`. One row per process step.
