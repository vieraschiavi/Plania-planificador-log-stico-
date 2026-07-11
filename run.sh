#!/usr/bin/env bash
# Plania · runner end-to-end
# Uso:
#   ./run.sh            -> instala deps, genera la base demo y levanta la app
#   ./run.sh data       -> solo genera la base demo (data/erp_demo.db)
#   ./run.sh app        -> solo levanta el dashboard Streamlit
#   ./run.sh backend    -> levanta el backend de venta (licencias + MercadoPago)
#   ./run.sh test       -> corre los tests
set -e
cd "$(dirname "$0")"

install() { pip3 install -q -r requirements.txt; }
data()    { python3 data/generate_dataset.py --seed 42; }
app()     { streamlit run app/app.py; }
backend() { uvicorn backend_venta.app:app --reload --port 8100; }
test_()   { python3 -m pytest -q tests/; }

case "${1:-all}" in
  install) install ;;
  data)    data ;;
  app)     app ;;
  backend) backend ;;
  test)    test_ ;;
  all)     install; data; echo "Levantando Plania…"; app ;;
  *) echo "Opción inválida: $1"; exit 1 ;;
esac
