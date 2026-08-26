import requests, json, threading, time
base='http://127.0.0.1:5000'

# Obtener primer medicamento con stock >= 2
r = requests.get(f'{base}/api/medicamentos')
meds = r.json().get('medicamentos', [])
med = None
for m in meds:
    if int(m.get('stock', 0)) >= 2:
        med = m
        break
if not med:
    print('No se encontró medicamento con stock >= 2 para la prueba.')
    raise SystemExit(1)

name = med['nombre']
price = float(med['precio'])
stock = int(med['stock'])
# ambas peticiones intentarán consumir todo el stock
qty = stock
print(f"Usando medicamento: {name} precio={price} stock={stock} qty_por_peticion={qty}")

def make_payload():
    total = round(price * qty, 2)
    subtotal_calc = round(total / 1.18, 2)
    igv = round(total - subtotal_calc, 2)
    return {
        'tipo_comprobante': 'BOLETA' if len('12345678')==8 else 'FACTURA',
        'cliente': {'documento': '12345678', 'nombre': 'Cliente Concurrente'},
        'medio_pago': 'EFECTIVO',
        'carrito': [ {'nombre': name, 'precio_unitario': price, 'cantidad': qty} ],
        'totales': {'subtotal': subtotal_calc, 'igv': igv, 'total': total}
    }

results = []
barrier = threading.Barrier(2)

def worker(idx):
    payload = make_payload()
    try:
        # esperar para sincronizar
        barrier.wait()
        t0 = time.time()
        resp = requests.post(f'{base}/api/ventas', json=payload)
        t1 = time.time()
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        results.append({'idx': idx, 'status': resp.status_code, 'body': body, 'time': t1-t0})
    except Exception as e:
        results.append({'idx': idx, 'error': str(e)})

threads = [threading.Thread(target=worker, args=(0,)), threading.Thread(target=worker, args=(1,))]
for t in threads: t.start()
for t in threads: t.join()

print('Resultados de las 2 peticiones simultáneas:')
print(json.dumps(results, ensure_ascii=False, indent=2))
