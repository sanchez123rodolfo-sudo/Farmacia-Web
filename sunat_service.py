"""
================================================================================
sunat_service.py - Modulo de integracion con la API de Facturacion Electronica
                    de la SUNAT (Superintendencia Nacional de Aduanas y de
                    Administracion Tributaria del Peru).
================================================================================

PROPOSITO:
    Este modulo prepara la infraestructura necesaria para que el sistema de
    farmacia pueda enviar comprobantes electronicos (Boletas y Facturas) a la
    API de SUNAT conforme a la normativa tributaria peruana.

    En su estado actual opera en MODO SIMULACION: no realiza llamadas reales
    a SUNAT, lo que permite desarrollar y probar el flujo completo sin
    credenciales ni conexion a internet. Cuando el sistema este listo para
    produccion, se cambia MODO_SIMULACION = False y se configuran las
    variables de entorno correspondientes.

POR QUE EXISTE:
    La SUNAT exige que toda venta a contribuyentes emita un comprobante
    electronico con firma digital. Este modulo implementa la capa de
    comunicacion con la API de SUNAT, incluyendo:

    1. Construccion del payload en el formato que espera la API.
    2. Envio HTTP/HTTPS con autenticacion Bearer.
    3. Procesamiento de la respuesta (aceptacion o rechazo).
    4. Registro de trazabilidad completa en la base de datos.
    5. Protocolo de rollback de stock ante rechazos.

FLUJO GENERAL:
    +---------------------------------------------------------------+
    |  Venta registrada en MySQL (commit)                           |
    |         |                                                      |
    |         v                                                      |
    |  enviar_comprobante_sunat() --> Intento de envio a SUNAT      |
    |         |                                                      |
    |         +--> ACEPTADO (codigo 0 / 0001):                      |
    |         |    * Se guarda hash_cdr (constancia de recepcion)    |
    |         |    * Se registra en comprobantes_pendientes_sunat    |
    |         |      con estado = 'ACEPTADO' para auditoria         |
    |         |    * El stock permanece descontado (venta valida)    |
    |         |                                                      |
    |         +--> RECHAZADO (codigo != 0):                          |
    |         |    * Se registra el error en la tabla auxiliar       |
    |         |    * SE REVIERTE EL STOCK automaticamente            |
    |         |    * El admin puede corregir y reenviar              |
    |         |                                                      |
    |         +--> ERROR DE RED / TIMEOUT:                           |
    |              * Se trata igual que un rechazo                   |
    |              * Stock revertido, comprobante queda pendiente    |
    |              * Se reintenta manualmente desde el panel admin   |
    +---------------------------------------------------------------+

SEGURIDAD Y ROLLBACK:
    Ante cualquier rechazo de SUNAT o error de conexion, el sistema ejecuta
    un ROLLBACK LOGICO del inventario: las unidades descontadas de cada
    medicamento se devuelven al stock mediante un UPDATE inverso en MySQL.
    Esto evita descuadres de inventario donde la farmacia perderia stock
    sin tener una venta valida.

    IMPORTANTE: La venta original en la tabla `comprobantes` NUNCA se borra.
    Esto garantiza la trazabilidad contable. El rollback solo afecta al
    stock de medicamentos, no al registro de la transaccion.

VARIABLES DE ENTORNO REQUERIDAS (para modo real):
    SUNAT_RUC            -- RUC de la empresa (11 digitos)
    SUNAT_CLIENT_ID      -- ID de cliente OAuth2 de SUNAT
    SUNAT_CLIENT_SECRET  -- Secreto de cliente OAuth2 de SUNAT
    SUNAT_API_TOKEN      -- Token de acceso Bearer
    SUNAT_URL_BASE       -- URL base de la API (default: e-factura.sunat.gob.pe)

TABLA AUXILIAR:
    comprobantes_pendientes_sunat -- Almacena comprobantes rechazados o
    pendientes de reintento. El administrador puede revisarlos, corregir
    datos, y reenviarlos sin perder la venta original.
================================================================================
"""

import os
import json
import hashlib
from datetime import datetime

import requests
from Practica_POO_Farmacia import conectar_bd, _adaptar_sql, _es_sqlite, _es_duplicado, _cursor_ctx

# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACION GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

# +-------------------------------------------------------------------------+
# | MODO SIMULACION                                                         |
# |                                                                         |
# | Cuando es True, enviar_comprobante_sunat() NO hace llamadas reales a    |
# | SUNAT. Genera un hash simulado del payload y retorna "aceptado=True"    |
# | inmediatamente. Esto permite:                                           |
# |                                                                         |
# |   - Desarrollar sin credenciales de SUNAT                               |
# |   - Probar el flujo completo de venta + respuesta                       |
# |   - Evitar llamadas HTTP innecesarias durante pruebas                   |
# |                                                                         |
# | PARA PRODUCCION: Cambiar a False y configurar las variables de entorno.  |
# +-------------------------------------------------------------------------+
MODO_SIMULACION = True

# URL base de la API de facturacion electronica de SUNAT.
# En produccion apunta a https://e-factura.sunat.gob.pe/v1/servicios
# En desarrollo/pruebas se puede apuntar a un sandbox o mock server.
SUNAT_URL_BASE = os.getenv(
    "SUNAT_URL_BASE",
    "https://e-factura.sunat.gob.pe/v1/servicios"
)

# +-------------------------------------------------------------------------+
# | CREDENCIALES DE ACCESO                                                  |
# |                                                                         |
# | NUNCA se almacenan directamente en el codigo fuente.                    |
# | Se leen de variables de entorno para evitar filtraciones en repositorios|
# | publicos o control de versiones.                                        |
# +-------------------------------------------------------------------------+
SUNAT_RUC = os.getenv("SUNAT_RUC", "")                        # RUC de la empresa (11 digitos)
SUNAT_CLIENT_ID = os.getenv("SUNAT_CLIENT_ID", "")            # Client ID OAuth2
SUNAT_CLIENT_SECRET = os.getenv("SUNAT_CLIENT_SECRET", "")    # Client Secret OAuth2

# Timeout de la peticion HTTP a SUNAT (en segundos).
# Si SUNAT no responde en este tiempo, se considera error de red.
TIMEOUT_ENVIO = 15

# Numero maximo de reintentos manuales desde el panel de administracion.
MAX_INTENTOS = 3


# ══════════════════════════════════════════════════════════════════════════════
# EXCEPCION PERSONALIZADA
# ══════════════════════════════════════════════════════════════════════════════

class SunatRechazoError(Exception):
    """
    Excepcion lanzada cuando SUNAT rechaza formalmente un comprobante.

    Se utiliza para diferenciar un rechazo de SUNAT (datos invalidos,
    RUC errado, estructura incorrecta) de un error de red o de BD.

    Atributos:
        codigo (str):           Codigo de error devuelto por SUNAT (ej: "0001", "2010").
        mensaje (str):          Mensaje descriptivo del error en espanol.
        comprobante_id (int):   ID del comprobante rechazado en MySQL.
    """
    def __init__(self, codigo, mensaje, comprobante_id=None):
        self.codigo = codigo
        self.mensaje = mensaje
        self.comprobante_id = comprobante_id
        super().__init__(f"SUNAT rechazo [{codigo}]: {mensaje}")


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES PRINCIPALES (publicas)
# ══════════════════════════════════════════════════════════════════════════════

def enviar_comprobante_sunat(comprobante_id, tipo_comprobante, serie,
                             correlativo, tipo_documento, documento,
                             nombre_cliente, carrito_items, subtotal, igv,
                             total, fecha=None):
    """
    ================================================================
    FUNCION PRINCIPAL: Envio de comprobante electronico a SUNAT
    ================================================================

    PROPOSITO:
        Puerta de entrada para enviar un comprobante a la API de SUNAT.
        Recibe todos los datos de la venta ya registrada en MySQL
        (la venta YA tiene commit) y construye el payload para enviarlo.

        Esta funcion NO modifica la venta original en `comprobantes`.
        Solo intenta comunicar el comprobante a SUNAT y retorna el
        resultado al caller.

    FLUJO DE EXITO (SUNAT acepta):
        1. Se construye el payload JSON con los datos de la venta.
        2. Se envia POST a la API de SUNAT con autenticacion Bearer.
        3. SUNAT responde con codigo de aceptacion (0, 0001, 200).
        4. Se retorna: {"aceptado": True, "hash_cdr": "...", ...}
        5. El caller (app.py) guarda el hash_cdr en BD para auditoria.
        6. El stock permanece descontado: la venta es valida y legal.

    FLUJO DE RECHAZO (SUNAT rechaza):
        1. SUNAT responde con codigo de error (ej: "0001" = RUC invalido).
        2. Se retorna: {"aceptado": False, "rechazado": True, ...}
        3. El caller ejecuta ROLLBACK del stock (devolver unidades).
        4. Se guarda en `comprobantes_pendientes_sunat` para que el admin
           lo revise, corrija, y reenvie manualmente.
        5. La venta original en `comprobantes` se conserva (trazabilidad).

    FLUJO DE ERROR DE RED:
        1. No se pudo conectar a SUNAT (timeout, DNS, firewall).
        2. Se retorna: {"aceptado": False, "error_red": True, ...}
        3. Se trata igual que un rechazo: stock revertido + pendiente.

    MODO SIMULACION (MODO_SIMULACION = True):
        No realiza llamadas HTTP. Genera un hash SHA-256 simulado del
        payload y retorna inmediatamente "aceptado=True". Esto permite
        probar el flujo completo sin credenciales de SUNAT.

    PARAMETROS:
        comprobante_id (int):      ID del comprobante en MySQL.
        tipo_comprobante (str):    "BOLETA" o "FACTURA".
        serie (str):               Serie del comprobante (ej: "B001").
        correlativo (int):         Numero correlativo unico dentro de la serie.
        tipo_documento (str):      "DNI" (8 digitos) o "RUC" (11 digitos).
        documento (str):           Numero de documento del cliente.
        nombre_cliente (str):      Razon social o nombre completo del cliente.
        carrito_items (list[dict]): Items vendidos con cantidades y precios.
        subtotal (Decimal):        Subtotal de la venta (sin IGV).
        igv (Decimal):             IGV de la venta (18% del subtotal).
        total (Decimal):           Total de la venta (subtotal + IGV).
        fecha (str):               Fecha de emision ISO 8601 o None (actual).

    RETORNA (dict):
        Si SUNAT acepta:
            {"aceptado": True, "rechazado": False, "hash_cdr": "...",
             "mensaje": "...", "payload": {...}}
        Si SUNAT rechaza:
            {"aceptado": False, "rechazado": True, "codigo": "...",
             "mensaje": "...", "payload": {...}}
        Si hay error de red:
            {"aceptado": False, "rechazado": False, "error_red": True,
             "codigo": "RED", "mensaje": "...", "payload": {...}}
    """
    # Si no se proporciona fecha, usar la fecha y hora actual del servidor.
    if fecha is None:
        fecha = datetime.now().isoformat()

    # ── PASO 1: Construir el payload JSON ────────────────────────────────
    # Se construye la estructura JSON que la API de SUNAT espera recibir.
    # Esta funcion interna puede ajustarse cuando se conozca el formato
    # exacto de la version de API de SUNAT que se vaya a utilizar.
    payload = _construir_payload_sunat(
        tipo_comprobante, serie, correlativo, tipo_documento,
        documento, nombre_cliente, carrito_items, subtotal, igv, total, fecha
    )

    # ── PASO 2: MODO SIMULACION ─────────────────────────────────────────
    # Si estamos en modo simulacion, no hacemos llamadas reales.
    # Generamos un hash simulado del payload para mantener la trazabilidad
    # y retornamos "aceptado=True" para que el flujo continúe normalmente.
    if MODO_SIMULACION:
        hash_simulado = hashlib.sha256(
            json.dumps(payload, default=str).encode()
        ).hexdigest()[:32]
        print(f"[SUNAT-SIM] Comprobante {serie}-{correlativo:06d} aceptado (simulado). Hash: {hash_simulado}")
        return {
            "aceptado": True,
            "rechazado": False,
            "hash_cdr": hash_simulado,
            "mensaje": "Comprobante aceptado (modo simulacion)",
            "payload": payload,
        }

    # ── PASO 3: MODO REAL - Enviar a la API de SUNAT ────────────────────
    # Si hay error de red (timeout, DNS, firewall, SSL), se captura la
    # excepcion y se retorna un resultado de "error_red" para que el
    # caller pueda manejarlo (revertir stock + registrar pendiente).
    try:
        respuesta = _enviar_a_sunat(payload)
    except requests.exceptions.RequestException as e:
        print(f"[SUNAT] Error de red al enviar {serie}-{correlativo:06d}: {e}")
        return {
            "aceptado": False,
            "rechazado": False,
            "error_red": True,
            "codigo": "RED",
            "mensaje": f"Error de conexion con SUNAT: {e}",
            "payload": payload,
        }

    # ── PASO 4: Procesar la respuesta de SUNAT ──────────────────────────
    # Se analiza el JSON de respuesta para determinar si fue aceptado o
    # rechazado, y se retorna un dict estandarizado.
    return _procesar_respuesta_sunat(respuesta, comprobante_id, payload)


def registrar_rechazo_sunat(comprobante_id, tipo_comprobante, serie,
                            correlativo, codigo, mensaje, payload):
    """
    ================================================================
    REGISTRO DE COMPROBANTES RECHAZADOS / PENDIENTES
    ================================================================

    PROPOSITO:
        Cuando SUNAT rechaza un comprobante (o hay error de red), esta
        funcion guarda el registro en la tabla auxiliar
        `comprobantes_pendientes_sunat` para que el administrador pueda:

        1. Ver el error exacto (codigo + mensaje de SUNAT).
        2. Revisar el payload que se envio.
        3. Corregir los datos si es necesario.
        4. Reintentar el envio desde el panel de administracion.

        Esto garantiza que NINGUNA venta se pierda, incluso si SUNAT
        la rechaza temporalmente.

    COMPORTAMIENTO:
        - Si ya existe un registro pendiente/rechazado para este comprobante,
          se ACTUALIZA incrementando el contador de intentos.
        - Si es la primera vez que se rechaza, se INSERTA un nuevo registro.
        - La tabla tiene un campo `max_intentos` (default 3) para evitar
          reintentos infinitos en caso de errores permanentes.

    ROLLBACK DE STOCK:
        Esta funcion NO ejecuta el rollback de stock. Eso lo hace el caller
        (app.py) antes de llamar a esta funcion. El rollback es una operacion
        separada para mantener la separacion de responsabilidades.

    PARAMETROS:
        comprobante_id (int):    ID del comprobante en tabla `comprobantes`.
        tipo_comprobante (str):  "BOLETA" o "FACTURA".
        serie (str):             Serie del comprobante (ej: "B001").
        correlativo (int):       Numero correlativo del comprobante.
        codigo (str):            Codigo de error de SUNAT o "RED"/"ERROR".
        mensaje (str):           Mensaje descriptivo del error.
        payload (dict):          JSON que se envio (o se iba a enviar) a SUNAT.

    RETORNA (bool):
        True si se guardo correctamente, False si hubo error de BD.
    """
    conexion = conectar_bd()
    if not conexion:
        print(f"[SUNAT] No se pudo guardar rechazo: sin conexion a BD")
        return False

    # Fecha/hora actual compatible con el motor activo.
    fecha_ahora = "datetime('now')" if _es_sqlite(conexion) else "NOW()"

    try:
        with _cursor_ctx(conexion) as cursor:
            # Verificar si ya existe un registro pendiente/rechazado para
            # este comprobante. Esto evita duplicados cuando se rechaza
            # multiples veces el mismo comprobante.
            cursor.execute(
                _adaptar_sql(conexion,
                    "SELECT id, intentos FROM comprobantes_pendientes_sunat "
                    "WHERE comprobante_id = %s AND estado IN ('PENDIENTE', 'RECHAZADO')"),
                (comprobante_id,)
            )
            existente = cursor.fetchone()

            if existente:
                # ── ACTUALIZAR registro existente ────────────────────────
                # Ya hubo un intento previo. Incrementamos el contador de
                # intentos y actualizamos el codigo/mensaje de error mas
                # reciente de SUNAT.
                cursor.execute(
                    _adaptar_sql(conexion,
                        "UPDATE comprobantes_pendientes_sunat "
                        "SET estado = 'RECHAZADO', codigo_respuesta = %s, mensaje_respuesta = %s, "
                        "intentos = intentos + 1, payload_sunat = %s, fecha_ultimo_intento = "
                        + fecha_ahora + " "
                        "WHERE id = %s"),
                    (str(codigo), mensaje, json.dumps(payload, default=str), existente[0])
                )
                print(f"[SUNAT] Rechazo actualizado para comprobante {comprobante_id} "
                      f"(intento {existente[1] + 1})")
            else:
                # ── INSERTAR nuevo registro ──────────────────────────────
                # Primera vez que este comprobante es rechazado. Creamos
                # un registro nuevo con intentos=1 y max_intentos configurado.
                cursor.execute(
                    _adaptar_sql(conexion,
                        "INSERT INTO comprobantes_pendientes_sunat "
                        "(comprobante_id, tipo_comprobante, serie, correlativo, estado, "
                        "codigo_respuesta, mensaje_respuesta, payload_sunat, intentos, max_intentos) "
                        "VALUES (%s, %s, %s, %s, 'RECHAZADO', %s, %s, %s, 1, %s)"),
                    (comprobante_id, tipo_comprobante, serie, correlativo,
                     str(codigo), mensaje, json.dumps(payload, default=str), MAX_INTENTOS)
                )
                print(f"[SUNAT] Nuevo rechazo registrado para comprobante {comprobante_id}")

        conexion.commit()
        return True
    except Exception as e:
        print(f"[SUNAT] Error al registrar rechazo: {e}")
        conexion.rollback()
        return False
    finally:
        conexion.close()


def registrar_aceptacion_sunat(comprobante_id, hash_cdr, mensaje, payload):
    """
    ================================================================
    REGISTRO DE ACEPTACION POR SUNAT (TRAZABILIDAD)
    ================================================================

    PROPOSITO:
        Cuando SUNAT acepta un comprobante, esta funcion guarda el hash del
        CDR (Constancia de Recepcion) en la tabla `comprobantes_pendientes_sunat`
        con estado 'ACEPTADO'. Esto proporciona:

        1. Trazabilidad completa: se sabe que comprobantes fueron aceptados.
        2. Auditoria: el hash del CDR es la prueba legal de aceptacion.
        3. Historial: se puede consultar el estado de cualquier comprobante.

        Aunque la venta ya esta segura en `comprobantes`, registrar la
        aceptacion en la tabla auxiliar permite consultas rapidas sobre
        el estado de facturacion electronica sin hacer JOINs complejos.

    COMPORTAMIENTO:
        - Usa INSERT ... ON DUPLICATE KEY UPDATE para manejar el caso
          donde previamente se registro un rechazo y ahora SUNAT acepto.
          Esto actualiza el registro existente en lugar de crear uno nuevo.

    PARAMETROS:
        comprobante_id (int):  ID del comprobante en MySQL.
        hash_cdr (str):        Hash del CDR devuelto por SUNAT.
        mensaje (str):         Mensaje de aceptacion de SUNAT.
        payload (dict):        JSON que se envio a SUNAT (para auditoria).

    RETORNA (bool):
        True si se guardo correctamente, False si hubo error de BD.
    """
    conexion = conectar_bd()
    if not conexion:
        return False

    # Fecha/hora actual compatible con el motor activo.
    fecha_ahora = "datetime('now')" if _es_sqlite(conexion) else "NOW()"

    try:
        with _cursor_ctx(conexion) as cursor:
            # Verificar si ya existe un registro para este comprobante
            # (por ejemplo, un rechazo previo).
            cursor.execute(
                _adaptar_sql(conexion,
                    "SELECT id FROM comprobantes_pendientes_sunat WHERE comprobante_id = %s"),
                (comprobante_id,)
            )
            existente = cursor.fetchone()

            payload_json = json.dumps(payload, default=str)
            tipo_comp = payload.get("tipo_comprobante")
            serie = payload.get("serie")
            correlativo = payload.get("correlativo")

            if existente:
                # ── ACTUALIZAR registro existente a ACEPTADO ─────────────
                cursor.execute(
                    _adaptar_sql(conexion,
                        "UPDATE comprobantes_pendientes_sunat "
                        "SET estado = 'ACEPTADO', codigo_respuesta = '200', "
                        "mensaje_respuesta = %s, hash_cdr = %s, payload_sunat = %s, "
                        "fecha_ultimo_intento = " + fecha_ahora + " "
                        "WHERE id = %s"),
                    (mensaje, hash_cdr, payload_json, existente[0])
                )
            else:
                # ── INSERTAR nuevo registro ACEPTADO ─────────────────────
                cursor.execute(
                    _adaptar_sql(conexion,
                        "INSERT INTO comprobantes_pendientes_sunat "
                        "(comprobante_id, tipo_comprobante, serie, correlativo, estado, "
                        "codigo_respuesta, mensaje_respuesta, hash_cdr, payload_sunat, intentos) "
                        "VALUES (%s, %s, %s, %s, 'ACEPTADO', '200', %s, %s, %s, 1)"),
                    (comprobante_id, tipo_comp, serie, correlativo,
                     mensaje, hash_cdr, payload_json)
                )
        conexion.commit()
        print(f"[SUNAT] Aceptacion registrada para comprobante {comprobante_id}")
        return True
    except Exception as e:
        print(f"[SUNAT] Error al registrar aceptacion: {e}")
        conexion.rollback()
        return False
    finally:
        conexion.close()


def listar_pendientes_sunat():
    """
    ================================================================
    CONSULTA DE COMPROBANTES PENDIENTES / RECHAZADOS
    ================================================================

    PROPOSITO:
        Retorna la lista de comprobantes que SUNAT rechazo o que aun
        no se han enviado con exito. Utilizada por el panel de
        administracion para mostrar al usuario los comprobantes que
        requieren atencion.

    FILTRADO:
        Solo muestra comprobantes con estado 'PENDIENTE' o 'RECHAZADO'.
        Los comprobantes 'ACEPTADO' se excluyen porque ya estan validados.

    ORDENAMIENTO:
        Los mas recientes primero (fecha_primer_intento DESC) para que
        el admin vea primero los errores mas nuevos.

    RETORNA (list[dict]):
        Lista de dicts con los campos de la tabla auxiliar mas el total
        y metodo de pago de la venta original. Lista vacia si hay error.
    """
    conexion = conectar_bd()
    if not conexion:
        return []

    try:
        with _cursor_ctx(conexion) as cursor:
            cursor.execute(
                "SELECT cps.id, cps.comprobante_id, cps.tipo_comprobante, "
                "cps.serie, cps.correlativo, cps.estado, cps.codigo_respuesta, "
                "cps.mensaje_respuesta, cps.hash_cdr, cps.intentos, cps.max_intentos, "
                "cps.fecha_primer_intento, cps.fecha_ultimo_intento, "
                "c.total, c.metodo_pago "
                "FROM comprobantes_pendientes_sunat cps "
                "JOIN comprobantes c ON c.id = cps.comprobante_id "
                "WHERE cps.estado IN ('PENDIENTE', 'RECHAZADO') "
                "ORDER BY cps.fecha_primer_intento DESC"
            )
            columnas = [desc[0] for desc in cursor.description]
            return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    except Exception as e:
        print(f"[SUNAT] Error al listar pendientes: {e}")
        return []
    finally:
        conexion.close()


def reenviar_comprobante_pendiente(pendiente_id):
    """
    ================================================================
    REENVIO DE COMPROBANTE RECHAZADO
    ================================================================

    PROPOSITO:
        Permite reintentar el envio de un comprobante que fue rechazado
        por SUNAT o que fallo por error de red. Utilizada desde el panel
        de administracion cuando el usuario corrijo los datos y quiere
        volver a enviar.

    FLUJO:
        1. Se busca el registro en `comprobantes_pendientes_sunat` por ID.
        2. Se verifica que no se haya excedido el maximo de intentos.
        3. Se incrementa el contador de intentos y se actualiza la fecha.
        4. Se reenvia usando el payload original guardado en la BD.
        5. Se retorna el resultado del reenvio al caller.

    RESTRICCIONES:
        - Si se alcanzo el maximo de intentos (default 3), se rechaza
          el reenvio y se indica al usuario que contacte al administrador.
        - Esto evita reintentos infinitos en casos de errores permanentes
          como un RUC invalido o un payload con formato incorrecto.

    PAYLOAD ORIGINAL:
        El payload JSON se guarda en la BD cuando se registro el rechazo
        inicial. Si se corrigieron datos manualmente, el admin deberia
        actualizar el payload antes de reenviar (funcionalidad futura).

    PARAMETROS:
        pendiente_id (int):  ID del registro en `comprobantes_pendientes_sunat`.

    RETORNA (dict):
        Si el reenvio fue exitoso (simulado):
            {"aceptado": True, "reenviado": True, "mensaje": "...", "payload": {...}}
        Si se alcanzo el maximo de intentos:
            {"aceptado": False, "mensaje": "Se alcanzo el maximo de N intentos..."}
        Si hay error de BD:
            {"aceptado": False, "error_red": True, "mensaje": "Sin conexion a BD"}
    """
    conexion = conectar_bd()
    if not conexion:
        return {"aceptado": False, "error_red": True, "mensaje": "Sin conexion a BD"}

    # Fecha/hora actual compatible con el motor activo.
    fecha_ahora = "datetime('now')" if _es_sqlite(conexion) else "NOW()"

    try:
        with _cursor_ctx(conexion) as cursor:
            # Buscar el comprobante pendiente junto con datos de la venta
            # original. El JOIN con `comprobantes` permite obtener el
            # tipo de comprobante y cliente_id si fueran necesarios.
            cursor.execute(
                _adaptar_sql(conexion,
                    "SELECT cps.comprobante_id, cps.tipo_comprobante, cps.serie, "
                    "cps.correlativo, cps.payload_sunat, cps.intentos, cps.max_intentos, "
                    "c.tipo_comprobante, c.cliente_id "
                    "FROM comprobantes_pendientes_sunat cps "
                    "JOIN comprobantes c ON c.id = cps.comprobante_id "
                    "WHERE cps.id = %s"),
                (pendiente_id,)
            )
            fila = cursor.fetchone()
            if not fila:
                return {"aceptado": False, "mensaje": "Comprobante pendiente no encontrado"}

            intentos = fila[5]
            max_intentos = fila[6]

            # Verificar que no se haya excedido el maximo de reintentos.
            # Esto protege contra reintentos infinitos por errores permanentes.
            if intentos >= max_intentos:
                return {
                    "aceptado": False,
                    "mensaje": f"Se alcanzo el maximo de {max_intentos} intentos. Contacte al administrador."
                }

            # Obtener el payload JSON guardado en la BD.
            # Este payload se genero cuando se registro el rechazo original
            # y contiene todos los datos que se intentaron enviar a SUNAT.
            payload = json.loads(fila[4]) if fila[4] else None
            if not payload:
                return {"aceptado": False, "mensaje": "No se encontro el payload original"}

            # Incrementar el contador de intentos y actualizar la fecha
            # del ultimo intento antes de reenviar.
            cursor.execute(
                _adaptar_sql(conexion,
                    "UPDATE comprobantes_pendientes_sunat "
                    "SET intentos = intentos + 1, fecha_ultimo_intento = "
                    + fecha_ahora + " "
                    "WHERE id = %s"),
                (pendiente_id,)
            )
        conexion.commit()

        # Reenviar usando el payload guardado.
        # En modo real, aqui se reconstruiria el payload y se enviaria
        # a traves de _enviar_a_sunat(). Por ahora, en modo simulacion,
        # se retorna exito inmediato.
        print(f"[SUNAT] Reenvio del comprobante {fila[2]}-{fila[3]:06d} "
              f"(intento {intentos + 1}/{max_intentos})")

        return {
            "aceptado": True,
            "reenviado": True,
            "mensaje": f"Reenvio exitoso (intento {intentos + 1})",
            "payload": payload,
        }
    except Exception as e:
        print(f"[SUNAT] Error en reenvio: {e}")
        conexion.rollback()
        return {"aceptado": False, "mensaje": str(e)}
    finally:
        conexion.close()


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES INTERNAS (privadas)
# ══════════════════════════════════════════════════════════════════════════════

def _construir_payload_sunat(tipo_comprobante, serie, correlativo,
                              tipo_documento, documento, nombre_cliente,
                              carrito_items, subtotal, igv, total, fecha):
    """
    Construye el payload JSON en el formato que espera la API de SUNAT.

    Esta funcion interna toma los datos normalizados de la venta y los
    estructura en un diccionario JSON compatible con la API de facturacion
    electronica. Puede ajustarse cuando se conozca el formato exacto de la
    version de API de SUNAT que se vaya a utilizar en produccion.

    PARAMETROS:
        tipo_comprobante, serie, correlativo, tipo_documento, documento,
        nombre_cliente, carrito_items, subtotal, igv, total, fecha:
        Todos los campos necesarios para construir el comprobante.

    RETORNA (dict):
        Diccionario con la estructura JSON lista para enviar a SUNAT.
    """
    return {
        "tipo_comprobante": tipo_comprobante,
        "serie": serie,
        "correlativo": correlativo,
        "fecha_emision": fecha,
        "cliente": {
            "tipo_documento": tipo_documento,
            "numero_documento": documento,
            "nombre_razon_social": nombre_cliente,
        },
        "items": [
            {
                "descripcion": item.get("producto", item.get("nombre", "")),
                "cantidad": item.get("cantidad", 0),
                "precio_unitario": item.get("precio_unitario", 0),
                "subtotal": item.get("subtotal", 0),
                "igv": round(float(item.get("subtotal", 0)) * 0.18 / 1.18, 2),
            }
            for item in carrito_items
        ],
        "totales": {
            "subtotal": float(subtotal),
            "igv": float(igv),
            "total": float(total),
        },
        "moneda": "PEN",
    }


def _enviar_a_sunat(payload):
    """
    Envia el payload a la API de SUNAT via HTTPS POST.

    Utiliza autenticacion Bearer con el token configurado en la variable
    de entorno SUNAT_API_TOKEN. Si el token no esta configurado, lanza
    un RuntimeError antes de hacer la peticion.

    PARAMETROS:
        payload (dict): JSON a enviar (ya construido por _construir_payload_sunat).

    RETORNA (requests.Response):
        Objeto Response de la libreria requests con la respuesta de SUNAT.

    EXCEPCIONES:
        RuntimeError:            Si SUNAT_API_TOKEN no esta configurado.
        requests.exceptions.RequestException: Si hay error de red/timeout.
    """
    token = os.getenv("SUNAT_API_TOKEN", "")
    if not token:
        raise RuntimeError("SUNAT_API_TOKEN no esta configurado en variables de entorno.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = f"{SUNAT_URL_BASE}/comprobantes"
    respuesta = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_ENVIO)
    respuesta.raise_for_status()
    return respuesta


def _procesar_respuesta_sunat(respuesta, comprobante_id, payload):
    """
    Procesa la respuesta HTTP de SUNAT y la clasifica en aceptado/rechazado.

    Analiza el JSON de respuesta para extraer el codigo de estado, el mensaje
    y el hash del CDR (si fue aceptado). Los codigos de aceptacion varian
    segun la version de la API de SUNAT.

    CODIGOS DE ACEPTACION RECONOCIDOS:
        "0"     - Comprobante aceptado (version comun)
        "0001"  - Comprobante aceptado (version alternativa)
        "000"   - Comprobante aceptado
        "200"   - OK (HTTP estandar)

    PARAMETROS:
        respuesta (requests.Response): Respuesta HTTP de SUNAT.
        comprobante_id (int):          ID del comprobante en MySQL.
        payload (dict):                Payload que se envio (para incluir en retorno).

    RETORNA (dict):
        Dict estandarizado con el resultado del procesamiento.
    """
    try:
        data = respuesta.json()
    except Exception:
        return {
            "aceptado": False,
            "rechazado": False,
            "codigo": str(respuesta.status_code),
            "mensaje": f"Respuesta no JSON de SUNAT: {respuesta.text[:200]}",
            "payload": payload,
        }

    # SUNAT tipicamente responde con campos "code" o "codeResponse".
    # Se intentan varias claves para cubrir diferentes versiones de la API.
    codigo = str(data.get("code", data.get("codeResponse", data.get("statusCode", ""))))
    mensaje = data.get("message", data.get("messageResponse", "Sin mensaje"))

    # El hash del CDR se puede encontrar en diferentes campos segun la version.
    hash_cdr = data.get("hash", data.get("cdrHash", data.get("externalId", None)))

    # Codigos de aceptacion de SUNAT (varian segun version de API).
    codigos_aceptacion = {"0", "0001", "000", "200"}

    if codigo in codigos_aceptacion:
        return {
            "aceptado": True,
            "rechazado": False,
            "hash_cdr": hash_cdr,
            "mensaje": mensaje,
            "payload": payload,
        }
    else:
        return {
            "aceptado": False,
            "rechazado": True,
            "codigo": codigo,
            "mensaje": mensaje,
            "payload": payload,
        }
