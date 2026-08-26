import json

try:
    with open("caja.json", "r") as archivo:
        datos_actuales = json.load(archivo)
except FileNotFoundError:
    print("⚠️ No se encontró 'caja.json'. Creando un archivo de caja nuevo...")
    datos_actuales = {"ganancia_total": 0.0}

ganancia_anterior = datos_actuales["ganancia_total"]
print(f"💰 Ganancia acumulada actual en la caja: ${ganancia_anterior}")

#Procesar nueva venta
monto_nuevo = float(input("¿Cuanto dinero ingresó en este turno?: "))
nuevo_total = ganancia_anterior + monto_nuevo

datos_actuales["ganancia_total"] = nuevo_total

with open("caja.json", "w") as archivo:
    json.dump(datos_actuales, archivo, indent=4)

print(f"✅ ¡Caja actualizada! El nuevo total guardado es: ${nuevo_total}")
