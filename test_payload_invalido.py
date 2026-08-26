import requests, json
base='http://127.0.0.1:5000'
payload = {
  'tipo_comprobante': 'BOLETA',
  'cliente': {'documento': '12345678', 'nombre': 'Prueba Error'},
  'medio_pago': 'EFECTIVO',
  'carrito': []
}
print('Payload enviado:', json.dumps(payload, ensure_ascii=False))
resp = requests.post(f'{base}/api/ventas', json=payload)
print('Status:', resp.status_code)
try:
    print('Body:', resp.json())
except Exception:
    print('Body text:', resp.text)
