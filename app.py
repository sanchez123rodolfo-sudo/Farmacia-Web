import os
import csv
import io
import json
import hmac
import traceback
from flask import Flask, request, jsonify, session, redirect, url_for, render_template, Response
from flask_cors import CORS
from decimal import Decimal, ROUND_HALF_UP
from Practica_POO_Farmacia import (
    conectar_bd,
    cargar_medicamentos_bd,
    buscar_cliente_bd,
    registrar_venta_carrito_bd,
    listar_medicamentos_bd,
    registrar_medicamento_bd,
    listar_presentaciones_bd,
    registrar_presentacion_bd,
    editar_presentacion_bd,
    desactivar_presentacion_bd,
    reabastecer_stock_bd,
    descontinuar_medicamento_por_id_bd,
    reporte_ganancias_bd,
    reporte_ganancias_filtrado_bd,
    consultar_alertas_bd,
    listar_ventas_bd,
    listar_clientes_bd,
    listar_productos_mas_vendidos_bd,
    importar_medicamentos_csv_bd,
    _adaptar_sql,
    Medicamento,
)
from sunat_service import (
    enviar_comprobante_sunat,
    registrar_rechazo_sunat,
    registrar_aceptacion_sunat,
    listar_pendientes_sunat,
    reenviar_comprobante_pendiente,
    SunatRechazoError,
)

# SEGURIDAD: static_folder apunta SOLO a la carpeta static/. Nunca usar '.'
# (la raíz del proyecto): expondría app.py, las credenciales de la BD y los
# comprobantes de los clientes a cualquiera sin iniciar sesión.
app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

# Clave para firmar la sesión del usuario. En producción cámbiala por una
# variable de entorno (FLASK_SECRET_KEY) con un valor seguro y único.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "clave-dev-secreta-farmacia-2026")

# ── Credenciales del administrador ──
# Se leen de variables de entorno. Las de abajo son SOLO valores de desarrollo:
# si el servidor arranca con ellas, se imprime una advertencia bien visible.
ADMIN_USER = os.getenv("FARMACIA_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("FARMACIA_ADMIN_PASSWORD", "admin123")


def medicamento_to_dict(med):
    return {
        "id": med.id,
        "nombre": med.nombre,
        "componente": med.componente,
        "laboratorio": med.laboratorio,
        "precio": float(med.precio),
        "stock": int(med.stock),
        "requiere_receta": bool(med.requiere_receta),
        "ventas_totales": float(med.ventas_totales),
        "codigo_barras": med.codigo_barras,
        # Presentaciones dinámicas cargadas desde la tabla `presentaciones`.
        # La venta por 'Unidad' (factor 1, precio unitario) es implícita.
        "presentaciones": [
            {
                "id": int(p["id"]),
                "nombre": p["nombre"],
                "factor": float(p["factor"]),
                "precio": float(p["precio"]),
            }
            for p in (getattr(med, "presentaciones", None) or [])
        ],
    }


def _flag_bool(valor):
    """Convierte un valor a booleano aceptando strings comunes ('true', '1', 'si', ...)."""
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "si", "sí", "yes", "on")
    return bool(valor)


@app.route("/api/medicamentos", methods=["GET"])
def api_medicamentos():
    try:
        medicamentos = cargar_medicamentos_bd()
        datos = [medicamento_to_dict(m) for m in medicamentos]
        return jsonify({"success": True, "medicamentos": datos}), 200
    except Exception as e:
        # Detalle real solo en consola; al cliente un mensaje genérico con 503.
        print(f"[api_medicamentos] {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503


@app.route("/api/cliente/<documento>", methods=["GET"])
def api_cliente(documento):
    """Busca un cliente por DNI/RUC en la tabla clientes (consulta parametrizada).
    404 = no existe | 503 = base de datos no disponible."""
    try:
        cliente = buscar_cliente_bd(documento)
        if not cliente:
            return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
        return jsonify({"success": True, "cliente": cliente}), 200
    except Exception as e:
        print(f"[api_cliente] {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503


@app.route("/api/ventas", methods=["POST"])
def api_ventas():
    data = request.get_json() or {}

    # ── DEBUG: imprimir el JSON completo que llega desde la web ──
    print("=" * 70)
    print("[api_ventas] JSON RECIBIDO DESDE LA WEB:")
    print(f"  tipo_comprobante  : {data.get('tipo_comprobante')}")
    print(f"  cliente           : {data.get('cliente')}")
    print(f"  carrito (items)   : {data.get('carrito')}")
    print(f"  metodo_pago       : {data.get('metodo_pago')}")
    print(f"  monto_pagado      : {data.get('monto_pagado')}")
    print(f"  numero_operacion  : {data.get('numero_operacion')}")
    print(f"  tipo_envio        : {data.get('tipo_envio_comprobante')}")
    print(f"  telefono_cliente  : {data.get('telefono_cliente')}")
    print(f"  correo_cliente    : {data.get('correo_cliente')}")
    print(f"  totales           : {data.get('totales')}")
    print(f"  tiene_receta      : {data.get('tiene_receta')}")
    print("=" * 70)

    # Validaciones básicas del payload
    tipo_comprobante = (data.get("tipo_comprobante") or "").upper()
    cliente = data.get("cliente", {})
    carrito_front = data.get("carrito", [])
    totales = data.get("totales")
    tiene_receta = _flag_bool(data.get("tiene_receta"))

    if tipo_comprobante not in ("FACTURA", "BOLETA", "NOTA_VENTA"):
        return jsonify({"success": False, "error": "tipo_comprobante debe ser 'FACTURA', 'BOLETA' o 'NOTA_VENTA'"}), 400

    # Tipo de envío del comprobante: físico o digital (con contacto para el envío).
    tipo_envio = (data.get("tipo_envio_comprobante") or "FISICO").upper()
    if tipo_envio not in ("FISICO", "DIGITAL"):
        return jsonify({"success": False, "error": "tipo_envio_comprobante debe ser 'FISICO' o 'DIGITAL'"}), 400

    telefono_cliente = (data.get("telefono_cliente") or "").strip() or None
    correo_cliente = (data.get("correo_cliente") or "").strip() or None
    if tipo_envio == "DIGITAL" and not telefono_cliente:
        return jsonify({
            "success": False,
            "error": "Para el comprobante digital se requiere 'telefono_cliente' (WhatsApp)."
        }), 400

    if not isinstance(cliente, dict) or not cliente.get("nombre"):
        return jsonify({"success": False, "error": "cliente debe contener 'nombre'"}), 400

    # Documento es opcional: se guarda como referencia si se proporciona.
    doc_cliente = str(cliente.get("documento") or "").strip() or None

    # Validación de documento según tipo de comprobante (solo si se proporciona)
    if doc_cliente:
        if not doc_cliente.isdigit():
            return jsonify({"success": False, "error": "El documento debe contener solo dígitos (DNI: 8, RUC: 11)."}), 400
        if tipo_comprobante == "FACTURA" and len(doc_cliente) != 11:
            return jsonify({"success": False, "error": "RUC inválido: debe tener 11 dígitos para FACTURA"}), 400
        if tipo_comprobante == "BOLETA" and len(doc_cliente) != 8:
            return jsonify({"success": False, "error": "DNI inválido: debe tener 8 dígitos para BOLETA"}), 400

    if not isinstance(carrito_front, list) or len(carrito_front) == 0:
        return jsonify({"success": False, "error": "carrito debe ser una lista no vacía"}), 400

    if not isinstance(totales, dict) or not all(k in totales for k in ("subtotal", "igv", "total")):
        return jsonify({"success": False, "error": "totales debe incluir 'subtotal', 'igv' y 'total'"}), 400

    # Validar items y recomputar totales
    carrito_interno = []
    subtotal_sum = Decimal("0.00")
    try:
        # Mapa autoritativo de medicamentos desde la BD
        # (cada objeto incluye sus presentaciones con factor y precio desde BD)
        meds_bd = {m.nombre.lower(): m for m in cargar_medicamentos_bd()}
        items_sin_receta = []

        for item in carrito_front:
            nombre = item.get("nombre") or item.get("producto")
            if not nombre:
                return jsonify({"success": False, "error": f"Cada item necesita 'nombre' o 'producto'. Item: {item}"}), 400

            # Validación de receta por ítem
            item_tiene_receta = _flag_bool(item.get("tiene_receta", tiene_receta))
            med_bd = meds_bd.get(str(nombre).lower())
            if med_bd and med_bd.requiere_receta and not item_tiene_receta:
                items_sin_receta.append(str(nombre))

            try:
                cantidad = int(item.get("cantidad", 0))
            except Exception:
                return jsonify({"success": False, "error": f"cantidad inválida para item {nombre}"}), 400

            if cantidad <= 0:
                return jsonify({"success": False, "error": f"cantidad debe ser > 0 para item {nombre}"}), 400

            # ── BLINDAJE DE PRECIOS Y FACTORES ──
            # El precio y el factor de conversión NUNCA se toman del frontend:
            # se leen de la BD. El frontend solo envía el id de la presentación
            # elegida; si no envía ninguna, se vende por unidad mínima (factor 1).
            # Un cliente malicioso podría enviar precio_unitario=0.01 o un factor
            # inventado; aquí se rechaza el producto desconocido y se impone el
            # precio y la equivalencia reales.
            if not med_bd:
                return jsonify({"success": False, "error": f"Producto desconocido o inactivo: {nombre}"}), 400

            presentacion_id = item.get("presentacion_id")
            presentacion_info = None
            if presentacion_id is not None:
                try:
                    presentacion_id = int(presentacion_id)
                except Exception:
                    return jsonify({"success": False, "error": f"presentacion_id inválido para item {nombre}"}), 400
                presentacion_info = next(
                    (p for p in (med_bd.presentaciones or []) if int(p["id"]) == presentacion_id),
                    None,
                )
                if not presentacion_info:
                    return jsonify({
                        "success": False,
                        "error": f"Presentación {presentacion_id} no válida o inactiva para '{med_bd.nombre}'"
                    }), 400

            if presentacion_info:
                precio = Decimal(str(presentacion_info["precio"]))
                factor = Decimal(str(presentacion_info["factor"]))
                unidades_a_descontar = int((Decimal(cantidad) * factor).quantize(Decimal("1")))
            else:
                precio = Decimal(str(med_bd.precio))
                unidades_a_descontar = cantidad

            if precio <= 0:
                return jsonify({"success": False, "error": f"El producto '{nombre}' tiene un precio inválido en la base de datos."}), 400

            subtotal = (precio * Decimal(cantidad)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            subtotal_sum += subtotal

            med_obj = Medicamento(
                nombre=med_bd.nombre, componente=med_bd.componente, laboratorio=med_bd.laboratorio,
                precio=float(precio), stock=0,
            )

            carrito_interno.append({
                "medicamento": med_obj,
                "cantidad": cantidad,
                "subtotal": subtotal,
                "presentacion": presentacion_info,   # None = venta por unidad mínima
                "unidades_a_descontar": unidades_a_descontar,
            })

        subtotal_sum = subtotal_sum.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_provided = Decimal(str(totales.get("total"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Verificar consistencia de totales (usar IGV 18%)
        subtotal_calc = (total_provided / Decimal("1.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        igv_calc = (total_provided - subtotal_calc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if subtotal_sum != total_provided:
            return jsonify({"success": False, "error": "Suma de subtotales de items no coincide con 'total' proporcionado"}), 400

        # Comparar totales proporcionados con cálculo del cliente
        if Decimal(str(totales.get("subtotal"))).quantize(Decimal("0.01")) != subtotal_calc:
            return jsonify({"success": False, "error": "El 'subtotal' proporcionado no coincide con el cálculo esperado (sin IGV)"}), 400
        if Decimal(str(totales.get("igv"))).quantize(Decimal("0.01")) != igv_calc:
            return jsonify({"success": False, "error": "El 'igv' proporcionado no coincide con el cálculo esperado"}), 400

        # Validación de receta médica por ítem (autoritativo contra la BD)
        if items_sin_receta:
            return jsonify({
                "success": False,
                "error": "La venta requiere receta médica. Confirma la receta para: "
                         + ", ".join(sorted(set(items_sin_receta)))
            }), 400

        # Llamamos a la función que registra la venta en la BD (maestro-detalle + control de stock)
        try:
            resultado = registrar_venta_carrito_bd(
                tipo_comprobante,
                doc_cliente,
                cliente.get("nombre"),
                carrito_interno,
                direccion=cliente.get("direccion") or None,
                metodo_pago=data.get("metodo_pago", "Efectivo"),
                monto_pagado=data.get("monto_pagado"),
                numero_operacion=data.get("numero_operacion"),
                tipo_envio_comprobante=tipo_envio,
                telefono_cliente=telefono_cliente,
                correo_cliente=correo_cliente,
            )
        except Exception as e:
            # Detalle real solo en consola; al cajero un mensaje accionable.
            print(f"Error al guardar venta: {type(e).__name__}: {e}")
            traceback.print_exc()
            return jsonify({"success": False, "error": "No se pudo registrar la venta por un error interno. Intente nuevamente."}), 500

        # Manejo de respuestas específicas desde la capa de BD
        if isinstance(resultado, dict) and resultado.get("stock_conflict"):
            # Conflicto de stock detectado en la transacción
            return jsonify({"success": False, "error": resultado.get("message", "Stock insuficiente")}), 409

        if resultado is None:
            # La capa de BD devolvió None: algo falló en la transacción (stock, conexión o SQL).
            print("Error al guardar venta: registrar_venta_carrito_bd devolvió None (revisa los prints de Practica_POO_Farmacia).")
            return jsonify({"success": False, "error": "No se pudo registrar la venta. Revisa el stock o la conexión a BD."}), 500

        # ================================================================
        # INTEGRACION SUNAT
        # ================================================================
        #
        # CONTEXTUALIZACION:
        #   En este punto la venta YA esta guardada en MySQL con commit.
        #   El stock ya fue descontado por registrar_venta_carrito_bd().
        #
        #   Ahora intentamos enviar el comprobante a la API de SUNAT
        #   para que sea validado legalmente. Los posibles resultados son:
        #
        #   1. SUNAT ACEPTA:
        #      - Se guarda el hash del CDR (constancia de recepcion) en BD.
        #      - El stock permanece descontado (venta valida y legal).
        #      - Se retorna exito al frontend.
        #
        #   2. SUNAT RECHAZA o ERROR DE RED:
        #      - Se registra el comprobante como PENDIENTE/RECHAZADO en
        #        la tabla auxiliar para que el admin lo revise.
        #      - SE REVIERTE EL STOCK automaticamente: las unidades
        #        descontadas de cada medicamento se devuelven al inventario.
        #        Esto evita descuadres de inventario donde la farmacia
        #        perderia stock sin tener una venta valida.
        #
        #   NOTA: La venta original en `comprobantes` NUNCA se borra.
        #   Esto garantiza la trazabilidad contable.
        # ================================================================
        sunat_resultado = None
        try:
            # ── PASO A: Preparar items para SUNAT ────────────────────────
            # Convertimos los items del carrito interno a una lista de dicts
            # simples, excluyendo los objetos Medicamento (que no son
            # serializables a JSON) y manteniendo solo los campos necesarios
            # para el comprobante electronico.
            items_sunat = []
            for item in carrito_interno:
                items_sunat.append({
                    "producto": item["medicamento"].nombre,
                    "nombre": item["medicamento"].nombre,
                    "cantidad": item["cantidad"],
                    "precio_unitario": float(item["medicamento"].precio),
                    "subtotal": float(item["subtotal"]),
                })

            # ── PASO B: Enviar comprobante a SUNAT ──────────────────────
            # Esta funcion puede retornar三种 resultados:
            # - {"aceptado": True, ...}   → SUNAT acepto el comprobante
            # - {"rechazado": True, ...}  → SUNAT rechazo (datos invalidos)
            # - {"error_red": True, ...}  → No se pudo conectar a SUNAT
            sunat_resultado = enviar_comprobante_sunat(
                comprobante_id=resultado["comprobante_id"],
                tipo_comprobante=tipo_comprobante,
                serie=resultado["serie"],
                correlativo=resultado["correlativo"],
                tipo_documento=resultado["_tipo_documento"],
                documento=resultado["_doc_cliente"],
                nombre_cliente=resultado["_nombre_cliente"],
                carrito_items=items_sunat,
                subtotal=resultado["_subtotal"],
                igv=resultado["_igv"],
                total=resultado["_total"],
            )
        except Exception as e_sunat:
            # Captura cualquier excepcion inesperada (no las de red, que ya
            # se manejan internamente). Se trata como un error de red.
            print(f"[SUNAT] Error inesperado al enviar comprobante: {e_sunat}")
            sunat_resultado = {"aceptado": False, "rechazado": False, "error_red": True, "mensaje": str(e_sunat)}

        # ── PASO C: Procesar resultado de SUNAT ─────────────────────────
        sunat_aceptado = False
        sunat_mensaje = ""

        if sunat_resultado and sunat_resultado.get("aceptado"):
            # ── CASO EXITOSO: SUNAT acepto el comprobante ───────────────
            sunat_aceptado = True
            sunat_mensaje = sunat_resultado.get("mensaje", "Comprobante aceptado")

            # Guardar el hash del CDR en BD para trazabilidad y auditoria.
            # El hash es la prueba legal de que SUNAT recibio y acepto
            # este comprobante electronico.
            registrar_aceptacion_sunat(
                comprobante_id=resultado["comprobante_id"],
                hash_cdr=sunat_resultado.get("hash_cdr", ""),
                mensaje=sunat_mensaje,
                payload=sunat_resultado.get("payload", {}),
            )
            print(f"[SUNAT] Comprobante {resultado['serie']}-{resultado['correlativo']:06d} ACEPTADO por SUNAT")
        else:
            # ── CASO DE RECHAZO / ERROR ─────────────────────────────────
            # SUNAT rechazo el comprobante O hubo error de red.
            # Ambos casos requieren: registrar pendiente + revertir stock.

            sunat_mensaje = sunat_resultado.get("mensaje", "Error desconocido de SUNAT") if sunat_resultado else "Sin respuesta de SUNAT"
            sunat_codigo = sunat_resultado.get("codigo", "ERROR") if sunat_resultado else "SIN_RESPUESTA"

            # Registrar en la tabla auxiliar para que el admin lo revise.
            # El admin puede corregir datos y reintentar desde el panel.
            registrar_rechazo_sunat(
                comprobante_id=resultado["comprobante_id"],
                tipo_comprobante=tipo_comprobante,
                serie=resultado["serie"],
                correlativo=resultado["correlativo"],
                codigo=sunat_codigo,
                mensaje=sunat_mensaje,
                payload=sunat_resultado.get("payload", {}) if sunat_resultado else {},
            )
            print(f"[SUNAT] Comprobante {resultado['serie']}-{resultado['correlativo']:06d} "
                  f"RECHAZADO/PENDIENTE: {sunat_mensaje}")

            # ── ROLLBACK DE STOCK ───────────────────────────────────────
            # La venta esta guardada pero SUNAT no la acepto.
            # Devolver las unidades al inventario para que no se pierdan.
            #
            # IMPORTANTE: Solo se revierte el stock (medicamentos), NO se
            # borra la venta de `comprobantes`. Esto garantiza la
            # trazabilidad contable: siempre se puede ver que hubo una
            # venta que SUNAT rechazo y quedo pendiente.
            try:
                conexion_revert = conectar_bd()
                if conexion_revert:
                    cur_rev = conexion_revert.cursor()
                    try:
                        for item in carrito_interno:
                            # UPDATE incrementa stock y decrementa ventas_totales,
                            # invirtiendo exactamente las unidades base que
                            # descontó registrar_venta_carrito_bd
                            # (cantidad x factor de la presentación vendida).
                            cur_rev.execute(
                                _adaptar_sql(conexion_revert,
                                    "UPDATE medicamentos SET stock = stock + %s, "
                                    "ventas_totales = ventas_totales - %s "
                                    "WHERE LOWER(nombre) = LOWER(%s)"),
                                (item["unidades_a_descontar"], float(item["subtotal"]), item["medicamento"].nombre)
                            )
                    finally:
                        cur_rev.close()
                    conexion_revert.commit()
                    print(f"[SUNAT] Stock revertido para {len(carrito_interno)} medicamentos")
                    conexion_revert.close()
            except Exception as e_rev:
                # Si falla el rollback de stock, es un error critico.
                # La venta quedo registrada pero el stock quedo descontado.
                # Se requiere intervencion manual del administrador.
                print(f"[SUNAT] Error CRITICO al revertir stock: {e_rev}")

        # Retornar exito al frontend (la venta siempre se registro).
        # El frontend mostrara si SUNAT acepto o no, y el admin puede
        # tomar acciones correctivas desde el panel si es necesario.
        return jsonify({
            "success": True,
            "serie": resultado.get("serie"),
            "correlativo": resultado.get("correlativo"),
            "sunat": {
                "aceptado": sunat_aceptado,
                "mensaje": sunat_mensaje,
            }
        }), 201

    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        # Error imprevisto: traceback completo en consola, mensaje genérico al
        # cliente (str(e) podría filtrar detalles internos de MySQL/rutas).
        print(f"Error al guardar venta: {type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": "Error interno del servidor al procesar la venta."}), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    """Pantalla de inicio de sesión. POST valida credenciales e inicia la sesión."""
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        usuario = (data.get("usuario") or "").strip()
        clave = data.get("clave") or ""

        # TODO: validar contra la tabla de usuarios en MySQL (actualmente credenciales fijas).
        # compare_digest evita ataques de análisis de tiempos al comparar secretos.
        if hmac.compare_digest(usuario, ADMIN_USER) and hmac.compare_digest(clave, ADMIN_PASS):
            session.clear()
            session["usuario"] = usuario
            return jsonify({"success": True}), 200

        return jsonify({"success": False, "error": "Usuario o contraseña incorrectos."}), 401

    # GET: si ya hay sesión, saltar directo al menú.
    if session.get("usuario"):
        return redirect(url_for("menu_principal"))
    return render_template("login.html")


@app.route("/")
def menu_principal():
    """Menú principal: aparece inmediatamente después de iniciar sesión."""
    if not session.get("usuario"):
        return redirect(url_for("login"))
    return render_template("menu.html", usuario=session.get("usuario"))


@app.route("/caja")
def caja():
    """Pantalla de Caja / Ventas (el POS). Requiere sesión."""
    if not session.get("usuario"):
        return redirect(url_for("login"))
    return app.send_static_file("index.html")


@app.route("/admin")
def admin():
    """Panel de Administrador (gestión de inventario). Requiere sesión."""
    if not session.get("usuario"):
        return redirect(url_for("login"))

    bd_error = False
    
    # 1. Intentamos listar medicamentos
    try:
        medicamentos = listar_medicamentos_bd()
    except Exception as e:
        print(f"[admin] Error al listar medicamentos: {e}")
        medicamentos = []
        bd_error = True

    # 2. Intentamos cargar alertas sin romper la página si falla
    try:
        alertas = consultar_alertas_bd()
    except Exception as e:
        print(f"[admin] Error al consultar alertas: {e}")
        alertas = {"stock_bajo": [], "por_vencer": []}

    # Si la lista de medicamentos cargó bien (aunque esté vacía []), la BD está sana
    if medicamentos is not None and not bd_error:
        bd_error = False

    meds_data = [
        {
            "id": m["id"],
            "nombre": m["nombre"],
            "precio": m["precio"],
            "stock": m["stock"],
            "presentaciones": m.get("presentaciones", []),
        }
        for m in (medicamentos or [])
    ]
    return render_template("admin.html", usuario=session.get("usuario"),
                           medicamentos=medicamentos, alertas=alertas, bd_error=bd_error,
                           meds_data_json=json.dumps(meds_data, ensure_ascii=False))


@app.route("/admin/registrar", methods=["GET", "POST"])
def admin_registrar():
    """Registra un nuevo medicamento en el sistema (Panel de Administrador)."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    # Si el frontend consulta la ruta al cargar la página sin enviar datos, no disparamos error 400
    data = request.get_json(silent=True) or request.form or {}
    if request.method == "GET" or not data:
        return jsonify({"success": True, "message": "Ruta lista para registros"}), 200

    nombre = (data.get("nombre") or "").strip()
    categoria = (data.get("categoria") or "").strip()
    componente = (data.get("componente") or "").strip()
    laboratorio = (data.get("laboratorio") or "").strip()
    codigo_barras = (data.get("codigo_barras") or "").strip() or None
    requiere_receta = _flag_bool(data.get("requiere_receta"))
    fecha_vencimiento = (data.get("fecha_vencimiento") or "").strip()

    if data.get("stock") in (None, ""):
        return jsonify({"success": False, "error": "El stock es obligatorio."}), 400
    try:
        precio = float(data.get("precio") or 0)
        stock = int(data.get("stock"))
    except Exception:
        return jsonify({"success": False, "error": "precio y stock deben ser numéricos."}), 400

    if not fecha_vencimiento:
        return jsonify({"success": False, "error": "La fecha de vencimiento es obligatoria."}), 400

    if not nombre:
        return jsonify({"success": False, "error": "El nombre del medicamento es obligatorio."}), 400
    if precio <= 0:
        return jsonify({"success": False, "error": "El precio debe ser mayor que 0."}), 400
    if stock < 0:
        return jsonify({"success": False, "error": "El stock no puede ser negativo."}), 400

    # ── Presentación principal (opcional) ──
    nombre_presentacion = (data.get("nombre_presentacion") or "").strip()
    factor_presentacion = None
    precio_presentacion = None
    if (nombre_presentacion
            or data.get("factor_presentacion") not in (None, "")
            or data.get("precio_presentacion") not in (None, "")):
        if not nombre_presentacion:
            return jsonify({"success": False, "error": "Si declaras factor o precio de presentación, el nombre es obligatorio."}), 400
        try:
            factor_presentacion = float(data.get("factor_presentacion") or 0)
            precio_presentacion = float(data.get("precio_presentacion") or 0)
        except Exception:
            return jsonify({"success": False, "error": "factor y precio deben ser numéricos."}), 400
        if factor_presentacion < 1:
            return jsonify({"success": False, "error": "El factor de la presentación debe ser 1 o más."}), 400
        if precio_presentacion <= 0:
            return jsonify({"success": False, "error": "El precio de la presentación debe ser mayor que 0."}), 400

    presentacion_data = None
    if nombre_presentacion:
        presentacion_data = {
            "nombre": nombre_presentacion,
            "factor": factor_presentacion,
            "precio": precio_presentacion,
        }

    ok, resultado = registrar_medicamento_bd(
        nombre, categoria, componente, laboratorio, precio, stock,
        requiere_receta, codigo_barras, fecha_vencimiento,
        presentacion=presentacion_data,
    )
    if not ok:
        return jsonify({"success": False, "error": resultado}), 400

    return jsonify({"success": True, "id": resultado, "nombre": nombre}), 201

@app.route("/admin/alertas", methods=["GET"])
def admin_alertas():
    """Devuelve las alertas de stock bajo y vencimiento próximo como JSON."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401
    try:
        alertas = consultar_alertas_bd()
    except Exception as e:
        print(f"[admin_alertas] {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503
    return jsonify({"success": True, "alertas": alertas}), 200


@app.route("/admin/plantilla-csv", methods=["GET"])
def admin_plantilla_csv():
    """Descarga una plantilla CSV con las columnas esperadas para importación masiva."""
    if not session.get("usuario"):
        return redirect(url_for("login"))

    cabecera = "nombre,stock,precio,categoria,componente,laboratorio,codigo_barras,requiere_receta,fecha_vencimiento,unidades_por_blister,precio_blister\n"
    ejemplo = (
        "Paracetamol 500mg,100,12.50,Analgésico,Paracetamol,Farmacias Perú,7751000000001,false,2027-06-30,10,45.00\n"
        "Amoxicilina 250mg,50,28.00,Antibiótico,Amoxicilina,Lab.Generico,,true,2026-12-15,1,28.00\n"
        "Vitamina C,200,18.50,Vitaminas,Ácido ascórbico,Farmacias Perú,,false,,12,55.00\n"
    )
    contenido = cabecera + ejemplo

    return Response(
        contenido,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantilla_medicamentos.csv"}
    )


@app.route("/admin/importar-csv", methods=["POST"])
def admin_importar_csv():
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    if "archivo" not in request.files:
        return jsonify({"success": False, "error": "No se subió ningún archivo"}), 400

    archivo = request.files["archivo"]
    if not archivo.filename.endswith(".csv"):
        return jsonify({"success": False, "error": "Formato no válido. Debe ser .csv"}), 400

    import csv
    import io

    stream = io.StringIO(archivo.stream.read().decode("utf-8-sig"), newline=None)
    lector = csv.DictReader(stream)

    insertados = 0
    duplicados = 0
    errores = []

    conexion = conectar_bd()
    if not conexion:
        return jsonify({"success": False, "error": "Error de conexión a la base de datos"}), 500

    try:
        cursor = conexion.cursor()
        for i, fila in enumerate(lector, start=2):
            try:
                nombre = (fila.get("nombre") or "").strip()
                precio = float(fila.get("precio") or 0)
                stock = int(fila.get("stock") or 0)

                if not nombre or precio <= 0 or stock < 0:
                    errores.append(f"Línea {i}: Datos inválidos o incompletos")
                    continue

                receta_val = str(fila.get("requiere_receta", "")).lower() in ("true", "1", "si", "yes")
                receta = 1 if receta_val else 0

                sql = _adaptar_sql(conexion, """
                    INSERT INTO medicamentos 
                    (nombre, codigo_barras, precio, stock, fecha_vencimiento, requiere_receta, categoria, laboratorio, componente_generico)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """)

                cursor.execute(sql, (
                    nombre,
                    (fila.get("codigo_barras") or "").strip() or None,
                    precio,
                    stock,
                    (fila.get("fecha_vencimiento") or "").strip() or None,
                    receta,
                    (fila.get("categoria") or "").strip() or None,
                    (fila.get("laboratorio") or "").strip() or None,
                    (fila.get("componente_generico") or "").strip() or None,
                ))
                insertados += 1

            except Exception as e:
                errores.append(f"Línea {i}: {str(e)}")

        conexion.commit()
    except Exception as e:
        conexion.rollback()
        return jsonify({"success": False, "error": f"Error de base de datos durante la importación: {e}"}), 500
    finally:
        conexion.close()

    return jsonify({
        "success": True,
        "insertados": insertados,
        "duplicados": duplicados,
        "errores": errores
    })

@app.route("/admin/reabastecer", methods=["POST"])
def admin_reabastecer():
    """Suma unidades al stock actual de un medicamento (Panel de Administrador)."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    data = request.get_json(silent=True) or request.form
    try:
        medicamento_id = int(data.get("medicamento_id") or 0)
        cantidad = int(data.get("cantidad") or 0)
    except Exception:
        return jsonify({"success": False, "error": "medicamento_id y cantidad deben ser numéricos."}), 400

    if medicamento_id <= 0:
        return jsonify({"success": False, "error": "Medicamento inválido."}), 400
    if cantidad <= 0:
        return jsonify({"success": False, "error": "La cantidad a reabastecer debe ser mayor que 0."}), 400

    ok, resultado = reabastecer_stock_bd(medicamento_id, cantidad)
    if not ok:
        return jsonify({"success": False, "error": resultado}), 400
    return jsonify({"success": True, "medicamento_id": medicamento_id, "nuevo_stock": resultado}), 200


@app.route("/admin/descontinuar", methods=["POST"])
def admin_descontinuar():
    """Da de baja (borrado lógico) un medicamento por su id."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    data = request.get_json(silent=True) or request.form
    try:
        medicamento_id = int(data.get("medicamento_id") or 0)
    except Exception:
        return jsonify({"success": False, "error": "medicamento_id debe ser numérico."}), 400

    if medicamento_id <= 0:
        return jsonify({"success": False, "error": "Medicamento inválido."}), 400

    ok, msg = descontinuar_medicamento_por_id_bd(medicamento_id)
    if not ok:
        return jsonify({"success": False, "error": msg}), 400
    return jsonify({"success": True, "medicamento_id": medicamento_id}), 200


@app.route("/admin/presentaciones/registrar", methods=["POST"])
def admin_presentacion_registrar():
    """Crea una nueva presentación de venta para un medicamento.
    Body: {medicamento_id, nombre, factor, precio}."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    data = request.get_json(silent=True) or request.form

    try:
        medicamento_id = int(data.get("medicamento_id") or 0)
    except Exception:
        return jsonify({"success": False, "error": "medicamento_id debe ser numérico."}), 400
    if medicamento_id <= 0:
        return jsonify({"success": False, "error": "Medicamento inválido."}), 400

    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"success": False, "error": "El nombre de la presentación es obligatorio."}), 400

    # Validación de tipos; los rangos (factor>=1, precio>0) los valida la capa BD.
    try:
        factor = float(data.get("factor") or 0)
        precio = float(data.get("precio") or 0)
    except Exception:
        return jsonify({"success": False, "error": "factor y precio deben ser numéricos."}), 400

    ok, resultado = registrar_presentacion_bd(medicamento_id, nombre, factor, precio)
    if not ok:
        return jsonify({"success": False, "error": resultado}), 400
    return jsonify({"success": True, "id": resultado, "nombre": nombre}), 201


@app.route("/admin/presentaciones/editar", methods=["POST"])
def admin_presentacion_editar():
    """Actualiza factor y/o precio de una presentación existente.
    Solo se modifican los campos enviados; el resto queda intacto.
    Body: {presentacion_id, factor?, precio?}."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    data = request.get_json(silent=True) or request.form

    try:
        presentacion_id = int(data.get("presentacion_id") or 0)
    except Exception:
        return jsonify({"success": False, "error": "presentacion_id debe ser numérico."}), 400
    if presentacion_id <= 0:
        return jsonify({"success": False, "error": "Presentación inválida."}), 400

    factor_valor = None
    precio_valor = None
    if data.get("factor") not in (None, ""):
        try:
            factor_valor = float(data.get("factor"))
        except Exception:
            return jsonify({"success": False, "error": "factor debe ser numérico."}), 400
    if data.get("precio") not in (None, ""):
        try:
            precio_valor = float(data.get("precio"))
        except Exception:
            return jsonify({"success": False, "error": "precio debe ser numérico."}), 400

    if factor_valor is None and precio_valor is None:
        return jsonify({"success": False, "error": "Envía al menos 'factor' o 'precio' para actualizar."}), 400

    ok, mensaje = editar_presentacion_bd(presentacion_id, factor_valor, precio_valor)
    if not ok:
        return jsonify({"success": False, "error": mensaje}), 400
    return jsonify({"success": True, "mensaje": mensaje}), 200


@app.route("/admin/presentaciones/desactivar", methods=["POST"])
def admin_presentacion_desactivar():
    """Desactiva una presentación (borrado lógico: activo=0).
    Las ventas históricas no se afectan (guardan copia de nombre y factor).
    Body: {presentacion_id}."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    data = request.get_json(silent=True) or request.form

    try:
        presentacion_id = int(data.get("presentacion_id") or 0)
    except Exception:
        return jsonify({"success": False, "error": "presentacion_id debe ser numérico."}), 400
    if presentacion_id <= 0:
        return jsonify({"success": False, "error": "Presentación inválida."}), 400

    ok, mensaje = desactivar_presentacion_bd(presentacion_id)
    if not ok:
        return jsonify({"success": False, "error": mensaje}), 400
    return jsonify({"success": True, "mensaje": mensaje}), 200


@app.route("/admin/reporte", methods=["GET"])
def admin_reporte():
    """Reporte de ganancias acumuladas, con filtros opcionales por mes y año.
    Parámetros de query:
      mes  — 1 a 12 (opcional, sin filtro si se omite)
      anio — año completo (opcional, sin filtro si se omite)
    """
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    mes_param = request.args.get("mes", "").strip()
    anio_param = request.args.get("anio", "").strip()

    mes = int(mes_param) if mes_param.isdigit() and 1 <= int(mes_param) <= 12 else None
    anio = int(anio_param) if anio_param.isdigit() and len(anio_param) == 4 else None

    try:
        reporte = reporte_ganancias_filtrado_bd(mes=mes, anio=anio)
    except Exception as e:
        print(f"[admin_reporte] {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503
    return jsonify({"success": True, "reporte": reporte}), 200


@app.route("/admin/ventas", methods=["GET"])
def admin_ventas():
    """Historial de ventas recientes (comprobante + cliente + items + estado SUNAT).
    Parámetro opcional: limite (default 50, máximo 200)."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    try:
        limite = int(request.args.get("limite", 50))
    except Exception:
        limite = 50
    limite = max(1, min(limite, 200))

    try:
        ventas = listar_ventas_bd(limite=limite)
    except Exception as e:
        print(f"[admin_ventas] {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503
    return jsonify({"success": True, "ventas": ventas}), 200


@app.route("/admin/clientes", methods=["GET"])
def admin_clientes():
    """Lista de clientes registrados con resumen de compras (JSON).
    Parámetro opcional: limite (default 200, máximo 500)."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    try:
        limite = int(request.args.get("limite", 200))
    except Exception:
        limite = 200
    limite = max(1, min(limite, 500))

    try:
        clientes = listar_clientes_bd(limite=limite)
    except Exception as e:
        print(f"[admin_clientes] {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503
    return jsonify({"success": True, "clientes": clientes}), 200


@app.route("/admin/productos-mas-vendidos", methods=["GET"])
def admin_productos_mas_vendidos():
    """Top de productos más vendidos (mayor rotación de salida).
    Parámetro opcional: limite (default 5, máximo 20)."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    try:
        limite = int(request.args.get("limite", 5))
    except Exception:
        limite = 5
    limite = max(1, min(limite, 20))

    try:
        ranking = listar_productos_mas_vendidos_bd(limite=limite)
    except Exception as e:
        print(f"[admin_productos_mas_vendidos] {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": "Servicio no disponible: no se pudo conectar a la base de datos."}), 503
    return jsonify({"success": True, "productos": ranking}), 200


# ── Endpoints para comprobantes pendientes/rechazados por SUNAT ──

@app.route("/admin/sunat/pendientes", methods=["GET"])
def admin_sunat_pendientes():
    """Lista comprobantes pendientes o rechazados por SUNAT."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    pendientes = listar_pendientes_sunat()
    return jsonify({"success": True, "pendientes": pendientes}), 200


@app.route("/admin/sunat/reenviar", methods=["POST"])
def admin_sunat_reenviar():
    """Reintenta el envío de un comprobante rechazado/pendiente."""
    if not session.get("usuario"):
        return jsonify({"success": False, "error": "No autorizado"}), 401

    data = request.get_json(silent=True) or {}
    pendiente_id = data.get("pendiente_id")
    if not pendiente_id:
        return jsonify({"success": False, "error": "Se requiere 'pendiente_id'."}), 400

    resultado = reenviar_comprobante_pendiente(pendiente_id)
    if resultado.get("aceptado"):
        return jsonify({"success": True, "mensaje": resultado.get("mensaje", "Reenvío exitoso")}), 200
    else:
        return jsonify({"success": False, "error": resultado.get("mensaje", "No se pudo reenviar")}), 400


@app.route("/logout")
def logout():
    """Cierra la sesión y vuelve al login."""
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    # El modo debug SOLO se activa con la variable de entorno FLASK_DEBUG=1.
    # Nunca en producción: el debugger de Werkzeug permite ejecutar código
    # Python desde el navegador.
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"

    # Advertencias de seguridad al arrancar con valores por defecto.
    if ADMIN_PASS == "admin123" or ADMIN_USER == "admin":
        print("=" * 70)
        print("⚠️  ADVERTENCIA DE SEGURIDAD: estás usando las credenciales por")
        print("⚠️  defecto (admin/admin123). Define antes de pasar a producción:")
        print("⚠️     set FARMACIA_ADMIN_USER=tu_usuario")
        print("⚠️     set FARMACIA_ADMIN_PASSWORD=una_clave_larga_y_unica")
        print("=" * 70)
    if app.secret_key == "clave-dev-secreta-farmacia-2026":
        print("⚠️  ADVERTENCIA: FLASK_SECRET_KEY no definida; se usa la clave de desarrollo.")

    # Ejecutar en localhost:5000
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
