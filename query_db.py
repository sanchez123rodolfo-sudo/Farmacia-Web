from Practica_POO_Farmacia import conectar_bd
import json
from decimal import Decimal
from datetime import datetime


def rows_to_dicts(cursor, rows):
    cols = [c[0] for c in cursor.description]
    result = []
    for row in rows:
        d = dict(zip(cols, row))
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
        result.append(d)
    return result


def main():
    conn = conectar_bd()
    if not conn:
        print("No se pudo conectar a la base de datos.")
        return

    try:
        with conn.cursor() as cursor:
            # 1) Obtener el comprobante más reciente
            cursor.execute("SELECT * FROM comprobantes ORDER BY id DESC LIMIT 1;")
            comprobantes = rows_to_dicts(cursor, cursor.fetchall())

            salida = {"comprobante": None, "detalle": [], "medicamentos": []}

            if comprobantes:
                comprobante = comprobantes[0]
                salida["comprobante"] = comprobante

                # 2) Detalle del comprobante
                cursor.execute("SELECT * FROM detalle_comprobantes WHERE comprobante_id = %s", (comprobante['id'],))
                detalle = rows_to_dicts(cursor, cursor.fetchall())
                salida["detalle"] = detalle

                # 3) Listar medicamentos afectados y su stock actual
                medicamento_ids = list({d['medicamento_id'] for d in detalle})
                if medicamento_ids:
                    format_ids = ','.join(['%s'] * len(medicamento_ids))
                    sql = f"SELECT id, nombre, stock, ventas_totales FROM medicamentos WHERE id IN ({format_ids})"
                    cursor.execute(sql, medicamento_ids)
                    meds = rows_to_dicts(cursor, cursor.fetchall())
                    salida["medicamentos"] = meds

            print(json.dumps(salida, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error ejecutando consultas: {e}")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
