import requests, json, sys
base='http://127.0.0.1:5000'
print('Inicio test_venta_cerca_stock')
try:
    r = requests.get(f'{base}/api/medicamentos')
    r.raise_for_status()
    meds = r.json().get('medicamentos', [])
    if not meds:
        print('No hay medicamentos disponibles para la prueba')
        sys.exit(1)
    # elegir el primer medicamento con stock > 1
    m = None
    for cand in meds:
        stock = int(cand.get('stock') or 0)
        if stock > 1:
            m = cand
            break
    if m is None:
        print('No se encontró medicamento con stock > 1')
        sys.exit(1)
    nombre = m.get('nombre')
    precio = float(m.get('precio'))
    stock = int(m.get('stock'))
    qty = max(2, stock-1)
    print(f"Seleccionado: {nombre} precio={precio} stock={stock} qty_prueba={qty}")
    subtotal = round(precio * qty, 2)
    total = subtotal
    subtotal_calc = round(total / 1.18, 2)
    igv = round(total - subtotal_calc, 2)
    payload = {
        'tipo_comprobante': 'BOLETA' if len('12345678')==8 else 'FACTURA',
        'cliente': {'documento': '12345678', 'nombre': 'Cliente Prueba'},
        'medio_pago': 'EFECTIVO',
        'carrito': [ {'nombre': nombre, 'precio_unitario': precio, 'cantidad': qty} ],
        'totales': {'subtotal': subtotal_calc, 'igv': igv, 'total': total}
    }
    print('Payload:', json.dumps(payload, ensure_ascii=False))
    resp = requests.post(f'{base}/api/ventas', json=payload)
    print('POST status', resp.status_code)
    print(resp.text)
except Exception as e:
    print('Error en test:', e)
    sys.exit(2)
