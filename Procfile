web: streamlit run app/app.py --server.port ${PORT:-8501} --server.address 0.0.0.0 --server.headless true --browser.gatherUsageStats false
backend: uvicorn backend_venta.app:app --host 0.0.0.0 --port ${PORT:-8100}
