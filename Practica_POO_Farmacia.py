import json
from datetime import datetime
import pymysql
import os
import sys
from contextlib import contextmanager
import requests
import traceback
import sqlite3
from decimal import Decimal, ROUND_HALF_UP  # 👈 ¡NUEVO: Para cálculos de dinero exactos!

# psycopg2 (PostgreSQL) se importa de forma perezosa (lazy). Si no está
# instalado o no se usa DATABASE_URL, el arranque no debe romperse: el
# resto del sistema sigue funcionando con MySQL y/o SQLite.
try:
    import psycopg2
except ImportError:
    psycopg2 = None

# Forzar un manejo de texto UTF-8 en consolas Windows (cp1252) y en Render,
# para que los emojis/acentos de los prints no rompan el arranque.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Excepción personalizada para conflictos de stock en transacciones concurrentes
class StockConflictError(Exception):
    pass

# =========================================================
# DOCUMENTACIÓN RÁPIDA DEL PROYECTO
# =========================================================
# 1) Conexión a MySQL: conectar_bd()
# 2) Modelo de datos: clase Medicamento
# 3) Gestión de comprobantes: generar_archivo_comprobante_carrito()
# 4) Registro de ventas y transacciones: registrar_venta_carrito_bd()
# 5) Gestión de carrito: agregar_al_carrito(), mostrar_carrito(), calcular_total_carrito(), registrar_venta_carrito_bd()
# 6) Flujo principal del cliente y del administrador: realizar_venta_cliente()
#    y el menú del ciclo principal.
# =========================================================



print("1. Iniciando script...")


def _obtener_url_database():
    """Devuelve la URI de PostgreSQL desde DATABASE_URL o None.

    Traduce el prefijo antiguo de Heroku/Render (`postgres://`) al formato
    moderno que psycopg2 espera (`postgresql://`)."""
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _dividir_sentencias_sql(sql):
    """Divide un script SQL en sentencias individuales.
    Quita los comentarios de línea (`-- ...`) y descarta trozos vacíos.
    psycopg2 no ejecuta varios statements de una vez, por eso se dividen."""
    lineas_limpias = []
    for linea in sql.splitlines():
        idx = linea.find("--")
        if idx != -1:
            linea = linea[:idx]
        lineas_limpias.append(linea)
    texto = "\n".join(lineas_limpias)
    return [parte.strip() for parte in texto.split(";") if parte.strip()]


def _cargar_schema_sqlite(conexion):
    """Carga/verifica el schema en una base SQLite (no-op si no existe el archivo)."""
    schema_file = "schema_sqlite.sql" if os.path.exists("schema_sqlite.sql") else "schema.sql"
    if os.path.exists(schema_file):
        with open(schema_file, "r", encoding="utf-8") as f:
            conexion.executescript(f.read())
        conexion.commit()
        print(f"⚡ Tablas cargadas/verificadas desde {schema_file}")


def _cargar_schema_postgres(conexion):
    """Crea las tablas en PostgreSQL desde schema_postgres.sql (si existe).
    Es idempotente (CREATE TABLE IF NOT EXISTS) y tolerante a que el schema
    ya exista en Supabase/Render."""
    schema_file = "schema_postgres.sql"
    if not os.path.exists(schema_file):
        return
    with open(schema_file, "r", encoding="utf-8") as f:
        sql = f.read()
    cursor = conexion.cursor()
    try:
        for bloque in _dividir_sentencias_sql(sql):
            if bloque:
                cursor.execute(bloque)
    finally:
        cursor.close()
    conexion.commit()
    print(f"⚡ Tablas cargadas/verificadas desde {schema_file}")


def conectar_bd():
    """Conecta a la base de datos priorizando el motor correcto:
      1. PostgreSQL (psycopg2) si DATABASE_URL está definida (Render/Supabase).
      2. MySQL local (pymysql).
      3. SQLite local como RESPALDO final (solo si los anteriores fallan).

      Devolverá el objeto de conexión del primer motor que funcione, o None si
      todos fallan. SQLite ya no es el destino por defecto de la nube.

      IMPORTANTE: si DATABASE_URL está definida (Render/Supabase), solo se usa
      PostgreSQL. MySQL/SQLite únicamente se intentan cuando DATABASE_URL NO
      existe (entorno local de desarrollo)."""
    # ── 1. POSTGRESQL (uso EXCLUSIVO si DATABASE_URL existe) ──────────
    database_url = _obtener_url_database()
    if database_url:
        if psycopg2 is None:
            print("⚠️ DATABASE_URL está definida pero psycopg2 no está instalado. "
                  "Ejecuta: pip install psycopg2-binary")
            return None
        # Supabase/Render suelen exigir SSL. Si la URI no trae sslmode,
        # reintentamos automáticamente con sslmode=require.
        ultimo_error = None
        urls_a_probar = [database_url]
        if "sslmode" not in database_url.lower():
            separador = "&" if "?" in database_url else "?"
            urls_a_probar.append(f"{database_url}{separador}sslmode=require")
        for url in urls_a_probar:
            try:
                conexion = psycopg2.connect(url, connect_timeout=5)
                conexion.autocommit = False
                _cargar_schema_postgres(conexion)
                print("⚡ ¡CONEXIÓN EXITOSA A POSTGRESQL (RENDER/SUPABASE)!")
                return conexion
            except Exception as e_pg:
                ultimo_error = e_pg
                print(f"⚠️ PostgreSQL no disponible ({e_pg}).")
        # DATABASE_URL existe pero no se pudo conectar a PostgreSQL:
        # NO caer a MySQL/SQLite; informar del error de conexión.
        return None

    # ── 2. MYSQL LOCAL (solo si DATABASE_URL NO está definida) ────────
    try:
        conexion = pymysql.connect(
            host="127.0.0.1",
            port=3306,
            user="root",
            password="",
            database="farmacia_db",
            connect_timeout=2
        )
        print("⚡ ¡CONEXIÓN EXITOSA A MYSQL LOCAL!")
        return conexion
    except Exception as e_mysql:
        print(f"⚠️ MySQL no disponible ({e_mysql}). Probando SQLite (respaldo)...")

    # ── 3. SQLITE (RESPALDO FINAL, entorno local) ─────────────────────
    try:
        conexion = sqlite3.connect("farmacia.db")
        conexion.row_factory = sqlite3.Row
        _cargar_schema_sqlite(conexion)
        print("⚡ ¡CONEXIÓN EXITOSA A SQLITE (RESPALDO) LOCAL!")
        return conexion
    except Exception as e_sqlite:
        print(f"❌ Error al conectar a SQLite: {e_sqlite}")
        return None


def _es_sqlite(conexion):
    """Determina dinámicamente si la conexión es de SQLite."""
    return isinstance(conexion, sqlite3.Connection)


def _es_postgres(conexion):
    """Determina dinámicamente si la conexión es de PostgreSQL."""
    if psycopg2 is None:
        return False
    return isinstance(conexion, psycopg2.extensions.connection)


def _adaptar_sql(conexion, sql):
    """Adapta los placeholders de una sentencia SQL al motor activo.
    MySQL y PostgreSQL usan %s; solo SQLite usa ?."""
    if _es_sqlite(conexion):
        return sql.replace("%s", "?")
    return sql


@contextmanager
def _cursor_ctx(conexion):
    """Context manager de cursor compatible con MySQL (pymysql) y SQLite.
    sqlite3.Cursor no implementa el protocolo context manager directamente,
    por eso se crea este wrapper: yield el cursor y lo cierra al salir."""
    cursor = conexion.cursor()
    try:
        yield cursor
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def _adaptar_parametros(conexion, params):
    """Convierte los tipos no soportados por el motor en tipos nativos.
    MySQL (pymysql) admite Decimal, pero SQLite NO. Convertimos Decimal a
    float al pasar parámetros SQLite para evitar sqlite3.ProgrammingError."""
    if not _es_sqlite(conexion):
        return params
    if isinstance(params, (tuple, list)):
        return tuple(
            float(p) if isinstance(p, Decimal) else p
            for p in params
        )
    if isinstance(params, Decimal):
        return float(params)
    return params


def _es_duplicado(conexion, e):
    """Determina si una excepción de integridad corresponde a una fila duplicada.
    Funciona para MySQL (pymysql.err.IntegrityError código 1062), SQLite
    (sqlite3.IntegrityError 'UNIQUE constraint failed') y PostgreSQL
    (psycopg2.errors.UniqueViolation, SQLSTATE 23505)."""
    if _es_sqlite(conexion):
        mensaje = str(e).lower()
        return "unique" in mensaje or "constraint" in mensaje or "duplicate" in mensaje
    if _es_postgres(conexion):
        try:
            if str(getattr(e, "pgcode", "")) == "23505":
                return True
        except Exception:
            pass
        mensaje = str(e).lower()
        return "unique" in mensaje or "duplicate key" in mensaje or "duplicate_key" in mensaje.replace(" ", "_")
    try:
        import pymysql.err
        if isinstance(e, pymysql.err.IntegrityError):
            return bool(e.args) and e.args[0] == 1062
    except Exception:
        pass
    return False


def _upsert_cliente(conexion, cursor, tipo_doc, doc_cliente, nombre_cliente, direccion):
    """Inserta o actualiza un cliente de forma compatible con MySQL y SQLite.
    Devuelve el cliente_id. El número de documento es la clave única.

    IMPORTANTE (SQLite): cuando un INSERT falla por UNIQUE, la transacción
    queda "abortada" y hay que hacer rollback antes de seguir. Por eso aquí
    primero comprobamos si el cliente ya existe y solo insertamos si no:
    así evitamos disparar excepciones de integridad a mitad de transacción."""
    if _es_sqlite(conexion):
        cursor.execute(
            "SELECT id FROM clientes WHERE numero_documento = ?",
            (doc_cliente,)
        )
        fila = cursor.fetchone()
        if fila:
            cliente_id = fila[0]
            cursor.execute(
                "UPDATE clientes SET nombre_razon_social = ?, "
                "direccion = CASE WHEN ? IS NOT NULL AND ? != '' THEN ? ELSE direccion END "
                "WHERE id = ?",
                (nombre_cliente, direccion, direccion, direccion, cliente_id)
            )
            return cliente_id
        cursor.execute(
            "INSERT INTO clientes (tipo_documento, numero_documento, nombre_razon_social, direccion) "
            "VALUES (?, ?, ?, ?)",
            (tipo_doc, doc_cliente, nombre_cliente, direccion)
        )
        return cursor.lastrowid
    elif _es_postgres(conexion):
        # PostgreSQL: ON CONFLICT ... DO UPDATE ... RETURNING id.
        # Devuelve el id ya sea que inserte o actualice (upsert en un paso).
        cursor.execute(
            "INSERT INTO clientes (tipo_documento, numero_documento, nombre_razon_social, direccion) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (numero_documento) DO UPDATE SET "
            "nombre_razon_social = EXCLUDED.nombre_razon_social, "
            "direccion = CASE WHEN EXCLUDED.direccion IS NOT NULL AND EXCLUDED.direccion != '' "
            "THEN EXCLUDED.direccion ELSE clientes.direccion END "
            "RETURNING id",
            (tipo_doc, doc_cliente, nombre_cliente, direccion)
        )
        fila = cursor.fetchone()
        return fila[0]
    else:
        # MySQL: upsert nativo.
        cursor.execute(
            "INSERT INTO clientes (tipo_documento, numero_documento, nombre_razon_social, direccion) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), "
            "nombre_razon_social=VALUES(nombre_razon_social), "
            "direccion = IF(VALUES(direccion) IS NOT NULL AND VALUES(direccion) != '', "
            "VALUES(direccion), direccion)",
            (tipo_doc, doc_cliente, nombre_cliente, direccion)
        )
        return cursor.lastrowid

# Probar conexión inicial
mi_conexion = conectar_bd()
if mi_conexion:
    mi_conexion.close()
    print("⚡ ¡CONEXIÓN INICIAL PROBADA EXITOSAMENTE!")


def buscar_cliente_bd(documento):
    """Busca un cliente por DNI/RUC en la BD.
    Devuelve un dict con sus datos, o None si NO existe.
    Lanza excepción si hay fallo de conexión/SQL, para no confundir
    'el cliente no existe' con 'la base de datos está caída'."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    cursor = conexion.cursor()
    try:
        # Consulta parametrizada para evitar inyección SQL.
        cursor.execute(
            _adaptar_sql(conexion,
                "SELECT numero_documento, tipo_documento, nombre_razon_social, direccion "
                "FROM clientes WHERE numero_documento = %s"),
            (str(documento),)
        )
        fila = cursor.fetchone()
        if not fila:
            return None
        return {
            "documento": fila[0],
            "tipo_documento": fila[1],
            "nombre": fila[2],
            "direccion": fila[3],
        }
    except Exception as e:
        print(f"❌ Error al buscar cliente: {e}")
        raise
    finally:
        cursor.close()
        conexion.close()


class Medicamento:
    def __init__(self, nombre, componente, laboratorio, precio, stock, requiere_receta=False, ventas_totales=0.0, codigo_barras=None, fecha_vencimiento=None, unidades_por_blister=1, precio_blister=None, id=None, presentaciones=None):
        self.nombre = nombre
        self.componente = componente
        self.laboratorio = laboratorio
        self.precio = precio                  # precio por unidad mínima (tableta/ml/und)
        self.stock = stock                    # SIEMPRE en unidades mínimas
        self.requiere_receta = requiere_receta
        self.ventas_totales = ventas_totales
        self.codigo_barras = codigo_barras
        self.fecha_vencimiento = fecha_vencimiento
        # ── DEPRECATED: reemplazados por la tabla `presentaciones` ──
        # Se mantienen solo para compatibilidad con el panel admin y CSV.
        self.unidades_por_blister = unidades_por_blister or 1
        self.precio_blister = precio_blister
        # Identificador en BD (para vincular presentaciones).
        self.id = id
        # Presentaciones dinámicas: lista de dicts
        # [{"id": int, "nombre": str, "factor": float, "precio": float}, ...]
        # La venta por 'Unidad' es implícita: factor 1 y precio = self.precio.
        self.presentaciones = presentaciones or []
        
    def reabastecer_stock(self, cantidad):
        if cantidad > 0:
            self.stock += cantidad
            
    def descontar_stock(self, cantidad):
        """Solo reduce su cantidad, no interactúa con el cliente"""
        if cantidad <= self.stock:
            self.stock -= cantidad
            return True
        return False

    def mostrar_info(self):
        alerta = "⚠️ ¡Requiere Receta Médica!" if self.requiere_receta else "✅ Venta Libre"
        print(f"💊 {self.nombre} ({self.componente}) | Lab: {self.laboratorio} | Precio: s/.{self.precio:.2f} | Stock: {self.stock} | [{alerta}]")


# =========================================================
# GESTIÓN DEL CARRITO DE COMPRA
# =========================================================
# Estructura del carrito:
# - carrito: lista de diccionarios con claves:
#   * medicamento: objeto Medicamento
#   * cantidad: entero de unidades
#   * subtotal: Decimal redondeado a 2 decimales
# Funciones principales:
# - agregar_al_carrito: agrega o actualiza items
# - mostrar_carrito: imprime el contenido y devuelve total
# - calcular_total_carrito: suma subtotales y devuelve valor final
# - registrar_venta_carrito_bd: registra la venta completa en BD con detalle y actualiza stock
# =========================================================

def agregar_al_carrito(carrito, medicamento, cantidad, subtotal):
    """Agrega o actualiza un producto dentro del carrito."""
    # carrito: lista que vive en memoria RAM durante la venta actual.
    # Cada elemento del carrito es un diccionario con medicamento, cantidad y subtotal.
    for item in carrito:
        # Revisamos si ya hay el mismo medicamento en el carrito.
        # Comparamos nombres en minúsculas para evitar diferencias de mayúsculas.
        if item["medicamento"].nombre.lower() == medicamento.nombre.lower():
            # Si ya existía, sumamos la nueva cantidad a la cantidad anterior.
            item["cantidad"] += cantidad
            # También sumamos el subtotal nuevo al subtotal anterior.
            item["subtotal"] = (item["subtotal"] + subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            # Devolvemos el item actualizado y salimos de la función.
            return item

    # Si no encontramos el medicamento en el carrito, lo agregamos como nuevo item.
    carrito.append({
        "medicamento": medicamento,  # referencia al objeto Medicamento en memoria RAM.
        "cantidad": cantidad,        # unidades que el cliente quiere comprar de ese producto.
        "subtotal": subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)  # precio total de ese item.
    })
    # Devolvemos el último elemento agregado al carrito.
    return carrito[-1]


def mostrar_carrito(carrito):
    """Muestra el contenido del carrito y su total."""
    # Si la lista carrito está vacía, no hay nada que mostrar.
    if not carrito:#Si carrito es Folse se convierte en True y entra al if
        print("🛒 Tu carrito está vacío.")
        # Devuelve 0.00 para que el resto del código pueda usarlo sin error.
        return Decimal("0.00")

    print("\n--- 🛒 CONTENIDO DEL CARRITO ---")
    total_carrito = Decimal("0.00")  # acumulador del total en memoria RAM.
    for i, item in enumerate(carrito, 1):
        medicamento = item["medicamento"]  # objeto Medicamento almacenado en el item.
        subtotal = item["subtotal"]        # subtotal calculado para ese item.
        total_carrito += subtotal           # sumamos cada subtotal al total general.
        print(f"[{i}] {medicamento.nombre} | Cantidad: {item['cantidad']} | Subtotal: s/.{subtotal:.2f}")

    print(f"💵 TOTAL DEL CARRITO: s/.{total_carrito:.2f}")
    # Devuelve el total redondeado a dos decimales.
    return total_carrito.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_total_carrito(carrito):
    """Calcula el total del carrito."""
    total = Decimal("0.00")  # acumulador del total en memoria RAM.
    for item in carrito:
        # Sumamos cada subtotal guardado en el carrito.
        total += item["subtotal"]
    # Devuelve el total con redondeo financiero estándar.
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =========================================================
# CAMBIO CLAVE 1: GENERACIÓN DE COMPROBANTES FÍSICOS
# =========================================================
# Aquí se crea el archivo .txt en la carpeta comprobantes
# usando la ruta absoluta del script para que siempre quede
# guardado correctamente en el equipo.
# =========================================================
def generar_archivo_comprobante_carrito(tipo_comprobante, serie, correlativo, doc_cliente, carrito, total):
    """Genera un comprobante físico para una venta con varios productos del carrito."""
    # Importamos aquí localmente para que la función sea más fácil de reutilizar.
    import os
    from datetime import datetime

    # Fecha y hora actuales para mostrar en el comprobante.
    ahora = datetime.now()
    fecha_texto = ahora.strftime("%Y-%m-%d %H:%M:%S")
    # El nombre del archivo incluye el tipo de comprobante y el número correlativo.
    nombre_base = f"{tipo_comprobante.lower()}_{serie}_{correlativo:06d}.txt"

    # Ubicamos la carpeta 'comprobantes' junto al archivo del script.
    directorio_script = os.path.dirname(os.path.abspath(__file__))#Ubicamos la ruta absoluta del script actual
    carp_comprobantes = os.path.join(directorio_script, "comprobantes")#Ubicamos la carpeta comprobantes dentro de la ruta del script

    # Si la carpeta no existe, la creamos en disco.
    if not os.path.exists(carp_comprobantes):
        os.makedirs(carp_comprobantes)

    # Ruta completa del archivo a escribir.
    ruta_completa = os.path.join(carp_comprobantes, nombre_base)

    # Calculamos el subtotal y el IGV a partir del total.
    subtotal = (total / Decimal("1.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    igv = (total - subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Construimos el detalle de cada item en el comprobante.
    detalle = []
    for item in carrito:
        medicamento = item["medicamento"]
        detalle.append(
            f"Producto: {medicamento.nombre} | Cantidad: {item['cantidad']} | Subtotal: s/.{item['subtotal']:.2f}"
        )

    # Formateamos el contenido completo del comprobante como texto.
    contenido = f"""
=========================================
        FARMACIA INTERACTIVA S.A.C.       
        RUC: 20123456789                  
      {tipo_comprobante} ELECTRÓNICA: {serie}-{correlativo:06d}       
=========================================
Fecha/Hora  : {fecha_texto}
Doc. Cliente: {doc_cliente}
-----------------------------------------
DETALLE DE LA COMPRA:
{chr(10).join(detalle)}
-----------------------------------------
OP. GRAVADA : s/.{subtotal:.2f}
IGV (18%)   : s/.{igv:.2f}
TOTAL PAGAR : s/.{total:.2f}
=========================================
"""

    try:
        # Abrimos el archivo en modo escritura de texto y escribimos el comprobante.
        with open(ruta_completa, "w", encoding="utf-8") as archivo:
            archivo.write(contenido)
        print(f"🎟️ ¡ÉXITO! Archivo físico generado correctamente en:")
        print(f"📁 {ruta_completa}")
    except Exception as e:
        # Si falla la escritura, mostramos el error al usuario.
        print(f"❌ ERROR AL ESCRIBIR EL COMPROBANTE EN DISCO: {e}")

def pedir_numero(mensaje, tipo=int):
    while True:
        try:
            return tipo(input(mensaje))
        except ValueError:
            print("❌ Entrada inválida. Por favor, ingresa un número válido.")


def guardar_medicamento_bd(medicamento):
    # Intenta establecer conexión con la base de datos activa.
    conexion = conectar_bd()
    if conexion:
        cursor = conexion.cursor()
        try:
            # Preparamos la sentencia SQL para insertar o actualizar el medicamento.
            # Si el nombre choca con una clave única, actualizamos los valores existentes.
            datos = (
                medicamento.nombre,
                medicamento.componente,
                medicamento.laboratorio,
                medicamento.precio,
                medicamento.stock,
                medicamento.requiere_receta,
                medicamento.ventas_totales,
                medicamento.unidades_por_blister,
                medicamento.precio_blister,
            )
            if _es_postgres(conexion):
                sql = """
                    INSERT INTO medicamentos (nombre, componente, laboratorio, precio, stock, requiere_receta, ventas_totales, activo, unidades_por_blister, precio_blister)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                    ON CONFLICT (nombre) DO UPDATE SET
                        stock = EXCLUDED.stock,
                        precio = EXCLUDED.precio,
                        requiere_receta = EXCLUDED.requiere_receta,
                        ventas_totales = EXCLUDED.ventas_totales,
                        unidades_por_blister = EXCLUDED.unidades_por_blister,
                        precio_blister = EXCLUDED.precio_blister
                    """
            elif _es_sqlite(conexion):
                # SQLite: la columna `activo` se mantiene, pero éste upsert
                # no es usado por la web; se emula con INSERT OR REPLACE.
                sql = """
                    INSERT INTO medicamentos (nombre, componente, laboratorio, precio, stock, requiere_receta, ventas_totales, activo, unidades_por_blister, precio_blister)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT (nombre) DO UPDATE SET
                        stock = excluded.stock,
                        precio = excluded.precio,
                        requiere_receta = excluded.requiere_receta,
                        ventas_totales = excluded.ventas_totales,
                        unidades_por_blister = excluded.unidades_por_blister,
                        precio_blister = excluded.precio_blister
                    """
                cursor.execute(sql, datos)
            else:
                sql = """
                    INSERT INTO medicamentos (nombre, componente, laboratorio, precio, stock, requiere_receta, ventas_totales, activo, unidades_por_blister, precio_blister)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        stock = VALUES(stock),
                        precio = VALUES(precio),
                        requiere_receta = VALUES(requiere_receta),
                        ventas_totales = VALUES(ventas_totales),
                        unidades_por_blister = VALUES(unidades_por_blister),
                        precio_blister = VALUES(precio_blister)
                    """
                cursor.execute(_adaptar_sql(conexion, sql), datos)
            # Guardamos los cambios en la base de datos.
            conexion.commit()
            print(f"💾 '{medicamento.nombre}' guardado en BD correctamente.")
        except Exception as e:
            # Si ocurre cualquier error durante la operación, lo mostramos.
            print(f"❌ Error al guardar en la BD: {e}")
        finally:
            # Cerramos siempre la conexión para liberar recursos.
            cursor.close()
            conexion.close()


def descontinuar_medicamento_bd(nombre_medicamento):
    """Realiza el borrado lógico en la base de datos cambiando activo = 0"""
    conexion = conectar_bd()
    if conexion:
        cursor = conexion.cursor()
        try:
            sql = "UPDATE medicamentos SET activo = 0 WHERE LOWER(nombre) = LOWER(%s)"
            cursor.execute(_adaptar_sql(conexion, sql), (nombre_medicamento,))
            conexion.commit()
            print(f"🗑️ '{nombre_medicamento}' marcado como inactivo (borrado lógico) en MySQL.")
        except Exception as e:
            print(f"❌ Error al descontinuar en la BD: {e}")
        finally:
            cursor.close()
            conexion.close()

# =========================================================
# PANEL DE ADMINISTRADOR: FUNCIONES PARA MYSQL
# =========================================================
def listar_medicamentos_bd():
    """Devuelve la lista de medicamentos activos (con su id) para el Panel de Administrador.
    Lanza excepción si la BD no está disponible."""
    conexion = conectar_bd()
    medicamentos = []
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cursor = conexion.cursor()
        try:
            cursor.execute(
                _adaptar_sql(conexion,
                    "SELECT id, nombre, categoria, codigo_barras, componente, laboratorio, precio, stock, "
                    "requiere_receta, ventas_totales, fecha_vencimiento, unidades_por_blister, precio_blister "
                    "FROM medicamentos WHERE activo = 1 ORDER BY nombre")
            )
            for fila in cursor.fetchall():
                medicamentos.append({
                    "id": fila[0],
                    "nombre": fila[1],
                    "categoria": fila[2],
                    "codigo_barras": fila[3],
                    "componente": fila[4],
                    "laboratorio": fila[5],
                    "precio": float(fila[6]),
                    "stock": int(fila[7]),
                    "requiere_receta": bool(fila[8]),
                    "ventas_totales": float(fila[9]),
                    "fecha_vencimiento": fila[10],
                    "unidades_por_blister": int(fila[11]) if fila[11] else 1,
                    "precio_blister": float(fila[12]) if fila[12] else None,
                })

            # Presentaciones activas agrupadas por medicamento (una sola consulta).
            # Si la migración agregar_presentaciones.sql aún no se ejecutó,
            # se entrega lista vacía sin romper el panel.
            try:
                cursor.execute(
                    _adaptar_sql(conexion,
                        "SELECT id, medicamento_id, nombre, factor, precio "
                        "FROM presentaciones WHERE activo = 1 ORDER BY factor")
                )
                pres_por_med = {}
                for p in cursor.fetchall():
                    pres_por_med.setdefault(int(p[1]), []).append({
                        "id": int(p[0]),
                        "nombre": str(p[2]),
                        "factor": float(p[3]),
                        "precio": float(p[4]),
                    })
                for med in medicamentos:
                    med["presentaciones"] = pres_por_med.get(med["id"], [])
            except Exception as e_pres:
                print(f"⚠️ Tabla 'presentaciones' no disponible (¿falta migración?): {e_pres}")
                for med in medicamentos:
                    med["presentaciones"] = []
        finally:
            cursor.close()
    except Exception as e:
        print(f"❌ Error al listar medicamentos: {e}")
        raise
    finally:
        conexion.close()
    return medicamentos


# =========================================================
# PRESENTACIONES DINÁMICAS (factores de conversión)
# El stock siempre se mide en unidades mínimas; cada presentación
# declara cuántas unidades base contiene (factor).
# =========================================================
def listar_presentaciones_bd(medicamento_id=None, solo_activas=True):
    """Lista presentaciones: de todos los medicamentos o filtradas por uno.
    Devuelve lista de dicts. Lanza excepción si la BD no está disponible."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cursor = conexion.cursor()
        try:
            sql = ("SELECT id, medicamento_id, nombre, factor, precio, activo "
                   "FROM presentaciones")
            condiciones = []
            params = []
            if medicamento_id is not None:
                condiciones.append("medicamento_id = %s")
                params.append(int(medicamento_id))
            if solo_activas:
                condiciones.append("activo = 1")
            if condiciones:
                sql += " WHERE " + " AND ".join(condiciones)
            sql += " ORDER BY factor"
            cursor.execute(_adaptar_sql(conexion, sql), tuple(params))
            return [
                {
                    "id": int(f[0]),
                    "medicamento_id": int(f[1]),
                    "nombre": str(f[2]),
                    "factor": float(f[3]),
                    "precio": float(f[4]),
                    "activo": bool(f[5]),
                }
                for f in cursor.fetchall()
            ]
        finally:
            cursor.close()
    except Exception as e:
        print(f"❌ Error al listar presentaciones: {e}")
        raise
    finally:
        conexion.close()


def registrar_presentacion_bd(medicamento_id, nombre, factor, precio):
    """Crea una nueva forma de venta para un medicamento.
    Devuelve (True, nuevo_id) en éxito o (False, mensaje_error)."""
    # ── Validaciones antes de tocar la BD ──
    try:
        medicamento_id = int(medicamento_id)
    except (TypeError, ValueError):
        return False, "medicamento_id debe ser numérico."

    nombre = (nombre or "").strip()
    if not nombre:
        return False, "El nombre de la presentación es obligatorio."
    if len(nombre) > 50:
        return False, "El nombre no puede exceder los 50 caracteres."

    try:
        factor_dec = Decimal(str(factor))
    except Exception:
        return False, "El factor debe ser numérico."
    if factor_dec < 1:
        return False, "El factor debe ser 1 o más (unidades base que contiene)."

    try:
        precio_dec = Decimal(str(precio))
    except Exception:
        return False, "El precio debe ser numérico."
    if precio_dec <= 0:
        return False, "El precio debe ser mayor que 0."

    conexion = conectar_bd()
    if not conexion:
        return False, "No se pudo conectar a la base de datos."
    cursor = conexion.cursor()
    try:
        # El medicamento debe existir y estar activo.
        cursor.execute(_adaptar_sql(conexion, "SELECT activo FROM medicamentos WHERE id = %s"), (medicamento_id,))
        fila_med = cursor.fetchone()
        if not fila_med:
            return False, f"No existe el medicamento con id {medicamento_id}."
        if not fila_med[0]:
            return False, "El medicamento está descontinuado: no admite nuevas presentaciones."

        if _es_postgres(conexion):
            cursor.execute(
                "INSERT INTO presentaciones (medicamento_id, nombre, factor, precio) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (medicamento_id, nombre, float(factor_dec), float(precio_dec))
            )
            nuevo_id = cursor.fetchone()[0]
        else:
            cursor.execute(
                _adaptar_sql(conexion,
                    "INSERT INTO presentaciones (medicamento_id, nombre, factor, precio) "
                    "VALUES (%s, %s, %s, %s)"),
                (medicamento_id, nombre, float(factor_dec), float(precio_dec))
            )
            nuevo_id = cursor.lastrowid
        cursor.close()
        conexion.commit()
        print(f"✅ Presentación '{nombre}' (x{factor_dec}) registrada para medicamento id={medicamento_id}.")
        return True, nuevo_id
    except Exception as e_dup:
        # Clave UNIQUE (medicamento_id, nombre): no repetir nombres por producto.
        if _es_duplicado(conexion, e_dup):
            return False, f"Ya existe una presentación llamada '{nombre}' para este medicamento."
        print(f"❌ Error de integridad al registrar presentación: {e_dup}")
        return False, "Error de integridad en la base de datos."
    finally:
        conexion.close()


def editar_presentacion_bd(presentacion_id, factor=None, precio=None):
    """Actualiza el factor y/o el precio de una presentación existente.
    Solo envía los campos que quieras cambiar; el resto queda intacto.
    Devuelve (True, mensaje) o (False, mensaje_error)."""
    try:
        presentacion_id = int(presentacion_id)
    except (TypeError, ValueError):
        return False, "presentacion_id debe ser numérico."

    campos_sql = []
    params = []

    if factor is not None:
        try:
            factor_dec = Decimal(str(factor))
        except Exception:
            return False, "El factor debe ser numérico."
        if factor_dec < 1:
            return False, "El factor debe ser 1 o más."
        campos_sql.append("factor = %s")
        params.append(float(factor_dec))

    if precio is not None:
        try:
            precio_dec = Decimal(str(precio))
        except Exception:
            return False, "El precio debe ser numérico."
        if precio_dec <= 0:
            return False, "El precio debe ser mayor que 0."
        campos_sql.append("precio = %s")
        params.append(float(precio_dec))

    if not campos_sql:
        return False, "No hay nada que actualizar: envía factor y/o precio."

    params.append(presentacion_id)
    conexion = conectar_bd()
    if not conexion:
        return False, "No se pudo conectar a la base de datos."
    cursor = conexion.cursor()
    try:
        # Verificar existencia ANTES de actualizar. MySQL reporta rowcount=0
        # cuando el UPDATE no cambia valores reales (aunque la fila exista),
        # por lo que NO se debe usar rowcount para detectar "no existe":
        # guardar un precio sin modificarlo disparaba el falso error
        # "No existe la presentación con id N".
        cursor.execute(_adaptar_sql(conexion, "SELECT id FROM presentaciones WHERE id = %s"), (presentacion_id,))
        if cursor.fetchone() is None:
            cursor.close()
            return False, f"No existe la presentación con id {presentacion_id}."

        cursor.execute(
            _adaptar_sql(conexion,
                f"UPDATE presentaciones SET {', '.join(campos_sql)} WHERE id = %s"),
            tuple(params)
        )
        cursor.close()
        conexion.commit()
        print(f"✅ Presentación id={presentacion_id} actualizada.")
        return True, "Presentación actualizada correctamente."
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al editar presentación: {e}")
        return False, f"Error al editar la presentación: {e}"
    finally:
        conexion.close()


def desactivar_presentacion_bd(presentacion_id):
    """Desactiva una presentación (borrado lógico, activo = 0).
    NO se borra físicamente para preservar la auditoría: detalle_comprobantes
    guarda copia del nombre y factor usados en cada venta histórica.
    Devuelve (True, mensaje) o (False, mensaje_error)."""
    try:
        presentacion_id = int(presentacion_id)
    except (TypeError, ValueError):
        return False, "presentacion_id debe ser numérico."

    conexion = conectar_bd()
    if not conexion:
        return False, "No se pudo conectar a la base de datos."
    cursor = conexion.cursor()
    try:
        # Verificar existencia antes de desactivar (no depender de rowcount:
        # si la presentación ya está inactiva, MySQL reporta 0 filas).
        cursor.execute(_adaptar_sql(conexion, "SELECT id FROM presentaciones WHERE id = %s"), (presentacion_id,))
        if cursor.fetchone() is None:
            cursor.close()
            return False, f"No existe la presentación con id {presentacion_id}."

        cursor.execute(_adaptar_sql(conexion, "UPDATE presentaciones SET activo = 0 WHERE id = %s"), (presentacion_id,))
        cursor.close()
        conexion.commit()
        print(f"✅ Presentación id={presentacion_id} desactivada (borrado lógico).")
        return True, "Presentación desactivada correctamente."
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al desactivar presentación: {e}")
        return False, f"Error al desactivar la presentación: {e}"
    finally:
        conexion.close()


def registrar_medicamento_bd(nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras=None, fecha_vencimiento=None, unidades_por_blister=1, precio_blister=None, presentacion=None):
    """Inserta un nuevo medicamento en MySQL y, si se indica, su presentación
    principal, TODO dentro de una misma transacción.

    presentacion: dict opcional {'nombre': str, 'factor': numero, 'precio': numero}.
    Devuelve (True, nuevo_id) en éxito o (False, mensaje_error).
    Si falla cualquiera de los INSERT, se hace rollback: no queda nada a medias."""
    conexion = conectar_bd()
    if not conexion:
        return False, "No se pudo conectar a la base de datos."

    categoria = (categoria or "").strip() or "Sin categoría"
    componente = (componente or "").strip() or "No especificado"
    laboratorio = (laboratorio or "").strip() or "No especificado"

    cursor = conexion.cursor()
    try:
        if _es_postgres(conexion):
            cursor.execute(
                "INSERT INTO medicamentos (nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras, ventas_totales, activo, fecha_vencimiento, unidades_por_blister, precio_blister) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 1, %s, %s, %s) RETURNING id",
                (nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras, fecha_vencimiento, unidades_por_blister, precio_blister)
            )
            nuevo_id = cursor.fetchone()[0]
        else:
            cursor.execute(
                _adaptar_sql(conexion,
                    "INSERT INTO medicamentos (nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras, ventas_totales, activo, fecha_vencimiento, unidades_por_blister, precio_blister) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 1, %s, %s, %s)"),
                (nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras, fecha_vencimiento, unidades_por_blister, precio_blister)
            )
            nuevo_id = cursor.lastrowid

        if presentacion:
            p_nombre = (presentacion.get("nombre") or "").strip()
            p_factor = Decimal(str(presentacion.get("factor") or 0))
            p_precio = Decimal(str(presentacion.get("precio") or 0))

            if not p_nombre:
                raise ValueError("El nombre de la presentación es obligatorio.")
            if len(p_nombre) > 50:
                raise ValueError("El nombre de la presentación no puede exceder los 50 caracteres.")
            if p_factor < 1:
                raise ValueError("El factor de la presentación debe ser 1 o más.")
            if p_precio <= 0:
                raise ValueError("El precio de la presentación debe ser mayor que 0.")

            cursor.execute(
                _adaptar_sql(conexion,
                    "INSERT INTO presentaciones (medicamento_id, nombre, factor, precio) "
                    "VALUES (%s, %s, %s, %s)"),
                (nuevo_id, p_nombre, float(p_factor), float(p_precio))
            )

        # Un único commit: medicamento + presentación se guardan juntos.
        cursor.close()
        conexion.commit()
        return True, nuevo_id
    except ValueError as e:
        conexion.rollback()
        return False, str(e)
    except Exception as e_int:
        conexion.rollback()
        if _es_duplicado(conexion, e_int):
            # Entrada duplicada: mensaje amigable (no filtra detalles del motor).
            return False, "Ya existe un medicamento con ese nombre o una presentación con ese nombre para él."
        print(f"❌ Error SQL al registrar medicamento: {e_int}")
        return False, "Error de base de datos al registrar el medicamento."
    finally:
        conexion.close()


def importar_medicamentos_csv_bd(rows):
    """Inserta múltiples medicamentos en una sola transacción.
    rows: lista de dicts con al menos 'nombre', 'stock', 'precio'.
          Campos opcionales: 'categoria', 'componente', 'laboratorio',
          'codigo_barras', 'requiere_receta', 'fecha_vencimiento'.
    Devuelve (insertados, duplicados, errores).
    """
    conexion = conectar_bd()
    if not conexion:
        return 0, 0, ["No se pudo conectar a la base de datos."]

    insertados = 0
    duplicados = 0
    errores = []

    try:
        # SQLite y PostgreSQL inician la transacción implícitamente con la
        # primera sentencia de escritura; `begin()` solo aplica a MySQL.
        if _es_sqlite(conexion) or _es_postgres(conexion):
            pass
        else:
            conexion.begin()
        cursor = conexion.cursor()
        try:
            for i, row in enumerate(rows, start=1):
                nombre = (row.get("nombre") or "").strip()
                if not nombre:
                    errores.append(f"Fila {i}: nombre vacío, omitida.")
                    continue

                try:
                    stock = int(row.get("stock", 0))
                except (TypeError, ValueError):
                    errores.append(f"Fila {i}: stock inválido ('{row.get('stock')}'), omitida.")
                    continue

                if stock < 0:
                    errores.append(f"Fila {i}: el stock no puede ser negativo ('{row.get('stock')}'), omitida.")
                    continue

                try:
                    precio = float(row.get("precio", 0))
                except (TypeError, ValueError):
                    errores.append(f"Fila {i}: precio inválido ('{row.get('precio')}'), omitida.")
                    continue

                if precio <= 0:
                    errores.append(f"Fila {i}: precio debe ser > 0 ('{row.get('precio')}'), omitida.")
                    continue

                categoria = (row.get("categoria") or "").strip() or "Sin categoría"
                componente = (row.get("componente") or "").strip() or "No especificado"
                laboratorio = (row.get("laboratorio") or "").strip() or "No especificado"
                codigo_barras = (row.get("codigo_barras") or "").strip() or None
                requiere_receta = str(row.get("requiere_receta", "")).strip().lower() in ("true", "1", "si", "sí", "yes")
                fecha_vencimiento = (row.get("fecha_vencimiento") or "").strip() or None

                try:
                    unidades_por_blister = int(row.get("unidades_por_blister", 1) or 1)
                except (TypeError, ValueError):
                    unidades_por_blister = 1

                try:
                    precio_blister_val = row.get("precio_blister")
                    precio_blister = float(precio_blister_val) if precio_blister_val and str(precio_blister_val).strip() else None
                except (TypeError, ValueError):
                    precio_blister = None

                # Verificar duplicado por nombre
                cursor.execute(_adaptar_sql(conexion, "SELECT id FROM medicamentos WHERE LOWER(nombre) = LOWER(%s)"), (nombre,))
                if cursor.fetchone():
                    duplicados += 1
                    continue

                cursor.execute(
                    _adaptar_sql(conexion,
                        "INSERT INTO medicamentos "
                        "(nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras, ventas_totales, activo, fecha_vencimiento, unidades_por_blister, precio_blister) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 1, %s, %s, %s)"),
                    (nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, codigo_barras, fecha_vencimiento, unidades_por_blister, precio_blister)
                )
                insertados += 1
        finally:
            cursor.close()

        conexion.commit()
        print(f"📥 Importación CSV completada → insertados: {insertados}, duplicados: {duplicados}, errores: {len(errores)}")
        return insertados, duplicados, errores
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error en importación CSV: {type(e).__name__}: {e}")
        # Mensaje genérico al llamador: el detalle real queda solo en consola.
        return 0, 0, ["Error de base de datos durante la importación."]
    finally:
        conexion.close()


def reabastecer_stock_bd(medicamento_id, cantidad):
    """Suma unidades al stock actual de forma segura.
    Devuelve (True, nuevo_stock) en éxito o (False, mensaje_error)."""
    conexion = conectar_bd()
    if not conexion:
        return False, "No se pudo conectar a la base de datos."
    cursor = conexion.cursor()
    try:
        cursor.execute(
            _adaptar_sql(conexion,
                "UPDATE medicamentos SET stock = stock + %s WHERE id = %s AND activo = 1"),
            (cantidad, medicamento_id)
        )
        if cursor.rowcount == 0:
            cursor.close()
            return False, "Medicamento no encontrado o inactivo."
        cursor.execute(_adaptar_sql(conexion, "SELECT stock FROM medicamentos WHERE id = %s"), (medicamento_id,))
        nuevo_stock = cursor.fetchone()[0]
        cursor.close()
        conexion.commit()
        return True, nuevo_stock
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al reabastecer stock: {type(e).__name__}: {e}")
        return False, "Error de base de datos al reabastecer el stock."
    finally:
        conexion.close()


def descontinuar_medicamento_por_id_bd(medicamento_id):
    """Borrado lógico: marca activo = 0 para ocultarlo de las ventas activas.
    Devuelve (True, mensaje) o (False, mensaje_error)."""
    conexion = conectar_bd()
    if not conexion:
        return False, "No se pudo conectar a la base de datos."
    cursor = conexion.cursor()
    try:
        cursor.execute(
            _adaptar_sql(conexion,
                "UPDATE medicamentos SET activo = 0 WHERE id = %s AND activo = 1"),
            (medicamento_id,)
        )
        if cursor.rowcount == 0:
            cursor.close()
            return False, "Medicamento no encontrado o ya estaba dado de baja."
        cursor.close()
        conexion.commit()
        return True, "Medicamento dado de baja correctamente."
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al descontinuar medicamento: {type(e).__name__}: {e}")
        return False, "Error de base de datos al dar de baja el medicamento."
    finally:
        conexion.close()


def consultar_alertas_bd():
    """Devuelve dict con dos listas: stock_bajo y por_vencer.
    stock_bajo  → medicamentos con stock <= 5.
    por_vencer  → medicamentos cuya fecha_vencimiento está a 30 días o menos.
    Lanza excepción si la BD no está disponible (el llamador decide cómo
    informarlo; NUNCA se disfraza un fallo de 'no hay alertas')."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    cursor = conexion.cursor()
    try:
        # Medicamentos con stock bajo (≤ 5 unidades)
        cursor.execute(
            _adaptar_sql(conexion,
                "SELECT id, nombre, stock, fecha_vencimiento "
                "FROM medicamentos WHERE activo = 1 AND stock <= 5 ORDER BY stock ASC")
        )
        stock_bajo = [
            {"id": f[0], "nombre": f[1], "stock": int(f[2]), "fecha_vencimiento": f[3]}
            for f in cursor.fetchall()
        ]

        # Medicamentos por vencer (≤ 30 días desde hoy).
        # DATEDIFF / CURDATE / DATE_ADD son específicos de MySQL; SQLite usa
        # julianday() y date('now'). Generamos la consulta según el motor.
        if _es_sqlite(conexion):
            cursor.execute(
                "SELECT id, nombre, stock, fecha_vencimiento, "
                "CAST(julianday(fecha_vencimiento) - julianday('now') AS INTEGER) AS dias "
                "FROM medicamentos WHERE activo = 1 AND fecha_vencimiento IS NOT NULL "
                "AND fecha_vencimiento <= date('now', '+30 day') "
                "ORDER BY fecha_vencimiento ASC"
            )
        elif _es_postgres(conexion):
            cursor.execute(
                "SELECT id, nombre, stock, fecha_vencimiento, "
                "(fecha_vencimiento - CURRENT_DATE) AS dias "
                "FROM medicamentos WHERE activo = 1 AND fecha_vencimiento IS NOT NULL "
                "AND fecha_vencimiento <= CURRENT_DATE + INTERVAL '30 days' "
                "ORDER BY fecha_vencimiento ASC"
            )
        else:
            cursor.execute(
                "SELECT id, nombre, stock, fecha_vencimiento, DATEDIFF(fecha_vencimiento, CURDATE()) "
                "FROM medicamentos WHERE activo = 1 AND fecha_vencimiento IS NOT NULL "
                "AND fecha_vencimiento <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) "
                "ORDER BY fecha_vencimiento ASC"
            )
        por_vencer = [
            {"id": f[0], "nombre": f[1], "stock": int(f[2]), "fecha_vencimiento": str(f[3]),
             "dias_restantes": int(f[4])}
            for f in cursor.fetchall()
        ]
        cursor.close()

        print(f"🔔 Alertas: {len(stock_bajo)} con stock bajo, {len(por_vencer)} por vencer")
        return {"stock_bajo": stock_bajo, "por_vencer": por_vencer}
    except Exception as e:
        print(f"❌ Error al consultar alertas: {e}")
        raise
    finally:
        conexion.close()


def reporte_ganancias_bd():
    """Calcula los ingresos acumulados desde la tabla comprobantes.
    Devuelve un dict o None si hay error de conexión."""
    conexion = conectar_bd()
    if not conexion:
        return None
    cursor = conexion.cursor()
    try:
        cursor.execute(
            _adaptar_sql(conexion,
                "SELECT COALESCE(SUM(total), 0), COALESCE(SUM(igv), 0), COUNT(*) "
                "FROM comprobantes")
        )
        fila = cursor.fetchone()
        cursor.close()
        return {
            "total_ingresos": float(fila[0]),
            "total_igv": float(fila[1]),
            "cantidad_ventas": int(fila[2]),
        }
    except Exception as e:
        print(f"❌ Error al calcular reporte de ganancias: {e}")
        return None
    finally:
        conexion.close()


def reporte_ganancias_filtrado_bd(mes=None, anio=None):
    """Calcula ingresos filtrados por mes y/o año desde la tabla comprobantes.
    mes: 1-12 (None = todos los meses)
    anio: año completo (None = todos los años)
    Lanza excepción si la BD no está disponible (el endpoint responde 503)."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    cursor = conexion.cursor()
    try:
        condiciones = []
        params = []
        if _es_sqlite(conexion):
            # SQLite: strftime para extraer mes/año de la fecha.
            if anio:
                condiciones.append("CAST(strftime('%Y', fecha) AS INTEGER) = ?")
                params.append(int(anio))
            if mes:
                condiciones.append("CAST(strftime('%m', fecha) AS INTEGER) = ?")
                params.append(int(mes))
        elif _es_postgres(conexion):
            # PostgreSQL: EXTRACT para extraer mes/año de la fecha.
            if anio:
                condiciones.append("EXTRACT(YEAR FROM fecha) = %s")
                params.append(int(anio))
            if mes:
                condiciones.append("EXTRACT(MONTH FROM fecha) = %s")
                params.append(int(mes))
        else:
            # MySQL: YEAR()/MONTH() nativos.
            if anio:
                condiciones.append("YEAR(fecha) = %s")
                params.append(int(anio))
            if mes:
                condiciones.append("MONTH(fecha) = %s")
                params.append(int(mes))

        where = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""

        cursor.execute(
            _adaptar_sql(conexion,
                f"SELECT COALESCE(SUM(total), 0), COALESCE(SUM(igv), 0), COUNT(*) "
                f"FROM comprobantes{where}"),
            tuple(params)
        )
        fila = cursor.fetchone()

        # Desglose por método de pago
        cursor.execute(
            _adaptar_sql(conexion,
                f"SELECT metodo_pago, COALESCE(SUM(total), 0), COUNT(*) "
                f"FROM comprobantes{where} "
                f"GROUP BY metodo_pago ORDER BY SUM(total) DESC"),
            tuple(params)
        )
        por_metodo = cursor.fetchall()
        cursor.close()
        metodos_pago = [
            {"metodo": r[0] or "Sin especificar", "total": float(r[1]), "cantidad": int(r[2])}
            for r in por_metodo
        ]

        return {
            "total_ingresos": float(fila[0]),
            "total_igv": float(fila[1]),
            "cantidad_ventas": int(fila[2]),
            "metodos_pago": metodos_pago,
            "filtros": {"mes": mes, "anio": anio},
        }
    except Exception as e:
        print(f"❌ Error al calcular reporte de ganancias filtrado: {e}")
        raise
    finally:
        conexion.close()
def listar_ventas_bd(limite=50):
    """Devuelve las últimas ventas (comprobantes) para el Historial del panel admin.
    Cada venta incluye la cabecera del comprobante, datos del cliente
    y el detalle de productos (items).
    limite: cantidad máxima de comprobantes a retornar.
    Lanza excepción si la BD no está disponible (el endpoint responde 503;
    un fallo de conexión NUNCA se muestra como 'no hay ventas')."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    cursor = conexion.cursor()
    try:
        # Cabecera de comprobantes + datos del cliente.
        # Solo usa tablas base del sistema: comprobantes y clientes.
        cursor.execute(
            _adaptar_sql(conexion,
                "SELECT c.id, c.tipo_comprobante, c.serie, c.correlativo, c.fecha, "
                "cl.nombre_razon_social, cl.numero_documento, "
                "c.subtotal, c.igv, c.total, c.metodo_pago "
                "FROM comprobantes c "
                "LEFT JOIN clientes cl ON cl.id = c.cliente_id "
                "ORDER BY c.fecha DESC, c.id DESC LIMIT %s"),
            (int(limite),)
        )
        filas = cursor.fetchall()

        # Detalle de productos agrupado por comprobante (una sola consulta).
        detalles = {}
        ids = [f[0] for f in filas]
        if ids:
            placeholders = ", ".join(["%s"] * len(ids))
            cursor.execute(
                _adaptar_sql(conexion,
                    "SELECT dc.comprobante_id, m.nombre, dc.cantidad, dc.precio_unitario, dc.subtotal_linea "
                    "FROM detalle_comprobantes dc "
                    "JOIN medicamentos m ON m.id = dc.medicamento_id "
                    f"WHERE dc.comprobante_id IN ({placeholders})"),
                tuple(ids)
            )
            for d in cursor.fetchall():
                detalles.setdefault(d[0], []).append({
                    "producto": d[1],
                    "cantidad": int(d[2]),
                    "precio_unitario": float(d[3]),
                    "subtotal": float(d[4]),
                })
        cursor.close()

        ventas = [
            {
                "id": f[0],
                "tipo_comprobante": f[1],
                "serie": f[2],
                "correlativo": int(f[3]),
                "fecha": str(f[4]) if f[4] else None,
                "cliente": f[5] or "Cliente varios",
                "documento": f[6] or "—",
                "subtotal": float(f[7]),
                "igv": float(f[8]),
                "total": float(f[9]),
                "metodo_pago": f[10] or "—",
                "items": detalles.get(f[0], []),
            }
            for f in filas
        ]
        print(f"🧾 Historial: {len(ventas)} comprobantes listados")
        return ventas
    except Exception as e:
        print(f"❌ Error al listar ventas: {e}")
        raise
    finally:
        conexion.close()


def listar_productos_mas_vendidos_bd(limite=5):
    """Devuelve los medicamentos con mayor rotación de ventas (Top N),
    ordenados por cantidad total vendida (y por monto/ingreso como
    criterio de desempate). Se usa exclusivamente para el panel
    "Productos Más Vendidos" de la pestaña Comprobantes.
    limite: cantidad máxima de productos a retornar (default 5).
    Lanza excepción si la BD no está disponible."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    cursor = conexion.cursor()
    try:
        cursor.execute(
            _adaptar_sql(conexion,
                "SELECT dc.medicamento_id, m.nombre, "
                "SUM(dc.cantidad) AS unidades, SUM(dc.subtotal_linea) AS monto "
                "FROM detalle_comprobantes dc "
                "JOIN medicamentos m ON m.id = dc.medicamento_id "
                "GROUP BY dc.medicamento_id, m.nombre "
                "ORDER BY unidades DESC, monto DESC, m.nombre ASC "
                "LIMIT %s"),
            (int(limite),)
        )
        filas = cursor.fetchall()
        cursor.close()
        ranking = [
            {
                "nombre": f[1],
                "unidades": int(f[2]) if f[2] is not None else 0,
                "monto": float(f[3]) if f[3] is not None else 0.0,
            }
            for f in filas
        ]
        print(f"🏆 Top {len(ranking)} productos más vendidos")
        return ranking
    except Exception as e:
        print(f"❌ Error al listar productos más vendidos: {e}")
        raise
    finally:
        conexion.close()


def listar_clientes_bd(limite=200):
    """Devuelve los clientes registrados con un resumen de sus compras.
    Usa LEFT JOIN para incluir tambien clientes que nunca han comprado.
    limite: cantidad maxima de clientes a retornar.
    Lanza excepción si la BD no está disponible (el endpoint responde 503)."""
    conexion = conectar_bd()
    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    cursor = conexion.cursor()
    try:
        cursor.execute(
            _adaptar_sql(conexion,
                "SELECT cl.id, cl.tipo_documento, cl.numero_documento, cl.nombre_razon_social, "
                "cl.direccion, COUNT(c.id) AS num_compras, COALESCE(SUM(c.total), 0) AS total_comprado "
                "FROM clientes cl "
                "LEFT JOIN comprobantes c ON c.cliente_id = cl.id "
                "GROUP BY cl.id, cl.tipo_documento, cl.numero_documento, "
                "cl.nombre_razon_social, cl.direccion "
                "ORDER BY num_compras DESC, cl.nombre_razon_social ASC LIMIT %s"),
            (int(limite),)
        )
        clientes = [
            {
                "id": f[0],
                "tipo_documento": f[1] or "—",
                "documento": f[2] or "—",
                "nombre": f[3] or "Cliente varios",
                "direccion": f[4] or "—",
                "num_compras": int(f[5]),
                "total_comprado": float(f[6]),
            }
            for f in cursor.fetchall()
        ]
        cursor.close()
        print(f"👥 Clientes: {len(clientes)} listados")
        return clientes
    except Exception as e:
        print(f"❌ Error al listar clientes: {e}")
        raise
    finally:
        conexion.close()


# CAMBIO CLAVE 2: REGISTRO DE VENTA EN BASE DE DATOS
# =========================================================
# Este bloque guarda la venta, el comprobante y el detalle
# en una transacción segura para evitar inconsistencias.
# =========================================================
def registrar_venta_carrito_bd(tipo_comprobante, doc_cliente, nombre_cliente, carrito, direccion=None, metodo_pago="Efectivo", monto_pagado=None, numero_operacion=None, tipo_envio_comprobante="FISICO", telefono_cliente=None, correo_cliente=None):
    """Registra una venta completa con varios productos en un solo comprobante."""
    # Validación estricta del método de pago antes de tocar la BD.
    METODOS_VALIDOS = ("Efectivo", "Yape", "Plin", "Tarjeta")
    metodo_pago = (metodo_pago or "").strip()
    if metodo_pago not in METODOS_VALIDOS:
        raise ValueError(f"metodo_pago inválido '{metodo_pago}'. Debe ser 'Efectivo', 'Yape', 'Plin' o 'Tarjeta'.")
    numero_operacion = (numero_operacion or "").strip() or None
    if metodo_pago in ("Yape", "Plin", "Tarjeta") and not numero_operacion:
        raise ValueError("numero_operacion es obligatorio para pagos con 'Yape', 'Plin' o 'Tarjeta'.")

    # Monto pagado: si no se envía, se asume el total del carrito.
    total_carrito = sum((item["subtotal"] for item in carrito), Decimal("0.00"))
    total_carrito = total_carrito.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if monto_pagado is None:
        monto_pagado = total_carrito
    else:
        monto_pagado = Decimal(str(monto_pagado)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if monto_pagado < total_carrito:
            raise ValueError("monto_pagado no puede ser menor que el total de la venta.")

    # Conecta a la base de datos (MySQL local o SQLite en la nube).
    conexion = conectar_bd()
    if not conexion:
        # Si no hay conexión, devolvemos None para indicar fallo.
        return None

    # DEBUG: verificar a qué motor real se está conectando (sin tocar atributos
    # que solo existen en MySQL, como host/db/user, que SQLite no tiene).
    print(f"DEBUG: Motor activo = {'SQLite' if _es_sqlite(conexion) else 'MySQL'}")

    try:
        # Transacción atómica.
        # - SQLite: por defecto abre la transacción con la primera sentencia de
        #   escritura (isolation_level='' ) y commit/rollback la cierran.
        # - MySQL: pymysql inicia la transacción automáticamente; begin() no
        #   está disponible en sqlite3.Connection, por eso NO lo llamamos.
        cursor = conexion.cursor()
        try:
            # ── Documento del cliente (opcional para NOTA_VENTA) ──
            # Si no se proporciona documento, se usa un placeholder genérico
            # para satisfacer la restricción NOT NULL de la tabla clientes.
            doc_cliente = (doc_cliente or "").strip()
            if doc_cliente:
                tipo_doc = "RUC" if len(doc_cliente) == 11 else "DNI"
            else:
                tipo_doc = "DNI"
                doc_cliente = "00000000"  # placeholder para ventas sin documento

            # Fijamos el factor del IGV peruano.
            divisor_igv = Decimal("1.18")

            # Elegimos la serie según el tipo de comprobante.
            if tipo_comprobante == "FACTURA":
                serie = "F001"
            elif tipo_comprobante == "NOTA_VENTA":
                serie = "NV01"
            else:
                serie = "B001"

            # Calculamos el subtotal base antes del IGV y el IGV como la diferencia.
            subtotal = (total_carrito / divisor_igv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            igv = (total_carrito - subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # ── Correlativo a prueba de carreras ──
            # Dos cajas simultáneas pueden calcular el mismo MAX+1. Con el
            # índice UNIQUE (serie, correlativo), la venta perdedora recibe
            # un error de integridad (1062 en MySQL, UNIQUE constraint en
            # SQLite/PostgreSQL) y REINTENTA con el siguiente número libre,
            # sin abortar ni duplicar comprobantes.
            #
            # IMPORTANTE SQLite/PostgreSQL: un INSERT fallido por UNIQUE deja
            # la transacción "abortada"; hay que hacer rollback antes de seguir.
            # Por eso, dentro de cada reintento se hace rollback (deshace el
            # cliente insertado) y se vuelve a ejecutar el upsert del cliente
            # junto con el nuevo correlativo, dentro de la misma transacción.
            intentos_correlativo = 0
            comprobante_id = None
            while True:
                try:
                    # Inserta/actualiza el cliente (upsert compatible con los motores).
                    cliente_id = _upsert_cliente(conexion, cursor, tipo_doc, doc_cliente, nombre_cliente, direccion)

                    # Obtenemos el siguiente número correlativo para la serie.
                    cursor.execute(
                        _adaptar_sql(conexion,
                            "SELECT COALESCE(MAX(correlativo), 0) + 1 FROM comprobantes WHERE serie = %s"),
                        (serie,)
                    )
                    correlativo = cursor.fetchone()[0]

                    # Insertamos el comprobante principal.
                    # _adaptar_parametros convierte Decimal a float para SQLite.
                    datos_venta = (tipo_comprobante, serie, correlativo, cliente_id, subtotal, igv, total_carrito, metodo_pago, monto_pagado, numero_operacion)
                    if _es_postgres(conexion):
                        # PostgreSQL: cursor.lastrowid no es confiable; se usa
                        # RETURNING id para obtener el id real insertado.
                        cursor.execute(
                            "INSERT INTO comprobantes (tipo_comprobante, serie, correlativo, cliente_id, subtotal, igv, total, metodo_pago, monto_pagado, numero_operacion) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            _adaptar_parametros(conexion, datos_venta)
                        )
                        comprobante_id = cursor.fetchone()[0]
                    else:
                        cursor.execute(
                            _adaptar_sql(conexion,
                                "INSERT INTO comprobantes (tipo_comprobante, serie, correlativo, cliente_id, subtotal, igv, total, metodo_pago, monto_pagado, numero_operacion) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);"),
                            _adaptar_parametros(conexion, datos_venta)
                        )
                        comprobante_id = cursor.lastrowid
                    break
                except Exception as e_dup:
                    es_duplicado = _es_duplicado(conexion, e_dup)
                    if not es_duplicado or intentos_correlativo >= 5:
                        raise  # no es colisión de correlativo, o se agotaron los intentos
                    intentos_correlativo += 1
                    print(f"⚠️ Correlativo {serie}-{correlativo} en conflicto por venta simultánea; reintentando ({intentos_correlativo}/5)...")
                    # SQLite/PostgreSQL: rollback para salir del estado "aborted"
                    # de la transacción antes de reintentar. Esto deshace el
                    # INSERT del cliente, que se volverá a hacer en el siguiente
                    # ciclo. MySQL no requiere rollback: MAX+1 ya produce el
                    # siguiente número libre sin perder el cliente.
                    if _es_sqlite(conexion) or _es_postgres(conexion):
                        conexion.rollback()
                    else:
                        pass

            # Recorremos cada item que está en el carrito en memoria.
            for item in carrito:
                medicamento = item["medicamento"]
                presentacion = item.get("presentacion")  # dict o None (= venta por unidad)

                # Buscamos el id y el precio por unidad mínima del medicamento.
                # Se incluye 'precio': es la fuente autoritativa del cobro;
                # NUNCA se confía en el precio que traiga el objeto del frontend.
                cursor.execute(
                    _adaptar_sql(conexion, "SELECT id, precio FROM medicamentos WHERE LOWER(nombre) = LOWER(%s)"),
                    (medicamento.nombre,)
                )
                resultado = cursor.fetchone()
                if not resultado:
                    raise ValueError(f"No se encontró el medicamento {medicamento.nombre} en la base de datos.")
                medicamento_id = resultado[0]
                precio_bd = Decimal(str(resultado[1]))

                # ── LÓGICA GENÉRICA DE PRESENTACIONES ────────────────────
                # Si el item declara una presentación, se revalida contra la
                # BD dentro de la transacción: debe existir, estar activa y
                # pertenecer a este medicamento. El factor y el precio SIEMPRE
                # salen de la BD, jamás del frontend.
                presentacion_id = None
                if presentacion:
                    cursor.execute(
                        _adaptar_sql(conexion,
                            "SELECT id, nombre, factor, precio "
                            "FROM presentaciones WHERE id = %s AND medicamento_id = %s AND activo = 1"),
                        (presentacion.get("id"), medicamento_id)
                    )
                    fila_pres = cursor.fetchone()
                    if not fila_pres:
                        raise ValueError(
                            f"Presentación inválida o inactiva '{presentacion.get('nombre')}' "
                            f"para '{medicamento.nombre}'. Venta abortada."
                        )
                    presentacion_id = int(fila_pres[0])
                    precio_a_cobrar = Decimal(str(fila_pres[3]))
                    factor = Decimal(str(fila_pres[2]))
                else:
                    # Venta por unidad mínima: factor de conversión 1.
                    precio_a_cobrar = precio_bd
                    factor = Decimal("1")

                # Cálculo automático de inventario: la cantidad vendida se
                # multiplica por el factor y se descuentan EXACTAS unidades
                # base del stock (ej: 2 cajas x 30 und = -60 tabletas).
                unidades_a_descontar = int((Decimal(str(item["cantidad"])) * factor).quantize(Decimal("1")))

                # Recalcular subtotal con el precio correcto según presentación.
                subtotal_real = (precio_a_cobrar * Decimal(str(item["cantidad"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                # Inserta el detalle del comprobante en la tabla detalle_comprobantes,
                # guardando la presentación vendida para auditoría e inventario.
                cursor.execute(
                    _adaptar_sql(conexion,
                        "INSERT INTO detalle_comprobantes "
                        "(comprobante_id, medicamento_id, cantidad, precio_unitario, subtotal_linea, "
                        "presentacion_id, presentacion_nombre, factor) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s);"),
                    _adaptar_parametros(conexion, (
                        comprobante_id, medicamento_id, item["cantidad"], float(precio_a_cobrar), subtotal_real,
                        presentacion_id,
                        presentacion.get("nombre") if presentacion else "Unidad",
                        float(factor),
                    ))
                )
                # Actualiza el stock y las ventas_totales de ese medicamento.
                # El WHERE incluye validación de stock suficiente para evitar stock negativo.
                cursor.execute(
                    _adaptar_sql(conexion,
                        "UPDATE medicamentos SET stock = stock - %s, ventas_totales = ventas_totales + %s WHERE id = %s AND stock >= %s;"),
                    _adaptar_parametros(conexion, (unidades_a_descontar, subtotal_real, medicamento_id, unidades_a_descontar))
                )
                if cursor.rowcount == 0:
                    raise StockConflictError(
                        f"Stock insuficiente o modificado concurrentemente para '{medicamento.nombre}' (id={medicamento_id}). Venta abortada."
                    )
        finally:
            # Cerramos el cursor pase lo que pase (éxito o excepción).
            cursor.close()

        # Si todo fue bien, guardamos los cambios en MySQL.
        print(f"[registrar_venta_carrito_bd] ANTES DEL COMMIT - metodo_pago={metodo_pago}, monto_pagado={monto_pagado}, numero_operacion={numero_operacion}")
        conexion.commit()
        print(f"[registrar_venta_carrito_bd] COMMIT EJECUTADO EXITOSAMENTE")
        print(f"✅ Venta registrada en MySQL con éxito | {tipo_comprobante}: {serie}-{correlativo:06d}")
        return {
            "comprobante_id": comprobante_id,
            "serie": serie,
            "correlativo": correlativo,
            "tipo_envio_comprobante": tipo_envio_comprobante,
            "telefono_cliente": telefono_cliente,
            "correo_cliente": correo_cliente,
            "_carrito_original": carrito,  # para SUNAT: referencia a los items
            "_tipo_documento": tipo_doc,
            "_doc_cliente": doc_cliente,
            "_nombre_cliente": nombre_cliente,
            "_subtotal": subtotal,
            "_igv": igv,
            "_total": total_carrito,
        }
    except StockConflictError as sce:
        # Conflicto de stock detectado: revertimos y retornamos un dict reconocible por la API.
        conexion.rollback()
        print(f"⚠️ Conflicto de stock: {sce}")
        return {"stock_conflict": True, "message": str(sce)}
    except Exception as e:
        # Si falla algo más, revertimos todos los cambios para no dejar la DB a medias.
        conexion.rollback()
        print(f"❌ Error crítico en BD, transacción cancelada: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None
    finally:
        # Siempre cerramos la conexión para liberar recursos.
        conexion.close()


def preparar_json_api(tipo_comprobante, serie, correlativo, tipo_documento, documento, nombre_cliente, carrito, subtotal, igv, total, fecha=None):
    """Prepara el JSON de la venta en la forma que espera la API de facturación electrónica."""
    # Fecha de la venta; si no se pasa, usamos la fecha y hora actual.
    if fecha is None:
        fecha = datetime.now().isoformat()

    # Construimos la estructura principal del JSON con datos del comprobante y el cliente.
    payload = {
        "tipo_comprobante": tipo_comprobante,
        "serie": serie,
        "correlativo": correlativo,
        "cliente": {
            "tipo_documento": tipo_documento,
            "documento": documento,
            "nombre": nombre_cliente,
        },
        "items": [
            {
                "producto": item["medicamento"].nombre,
                "cantidad": item["cantidad"],
                "precio_unitario": float(item["medicamento"].precio),
                "subtotal": float(item["subtotal"]),
            }
            for item in carrito
        ],
        "totales": {
            "subtotal": float(subtotal),
            "igv": float(igv),
            "total": float(total),
        },
        "fecha": fecha,
    }

    # Devolvemos el JSON listo para enviar a la API.
    return payload


def enviar_venta_api(venta, api_url=None):
    """Envía los datos de la venta como JSON a una API de facturación electrónica simulada."""
    # 0) MODO SIMULACIÓN temporal para pruebas locales.
    #    Retornamos True aquí para que el flujo no haga llamadas reales.
    return True

    # 1) Leemos el token desde una variable de entorno segura.
    #    No escribir el token directamente en el código evita filtraciones.
    token = os.getenv("FACTURA_API_TOKEN")
    if not token:
        raise RuntimeError("No se encontró FACTURA_API_TOKEN en las variables de entorno.")

    # 2) La URL de la API también puede configurarse desde entorno.
    if api_url is None:
        api_url = os.getenv("FACTURA_API_URL", "https://api-simulada.example.com/ventas")

    # 3) Cabeceras necesarias para la API REST.
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 4) Construimos el payload JSON a partir de los datos de la venta.
    payload = {
        "tipo_comprobante": venta.get("tipo_comprobante"),
        "serie": venta.get("serie"),
        "correlativo": venta.get("correlativo"),
        "cliente": {
            "tipo_documento": venta.get("tipo_documento"),
            "documento": venta.get("documento"),
            "nombre": venta.get("nombre_cliente"),
        },
        "items": [
            {
                "producto": item["medicamento"].nombre,
                "cantidad": item["cantidad"],
                "precio_unitario": float(item["medicamento"].precio),
                "subtotal": float(item["subtotal"]),
            }
            for item in venta.get("carrito", [])
        ],
        "totales": {
            "subtotal": float(venta.get("subtotal", 0.0)),
            "igv": float(venta.get("igv", 0.0)),
            "total": float(venta.get("total", 0.0)),
        },
        "fecha": venta.get("fecha", datetime.now().isoformat()),
    }

    try:
        # 5) Enviamos la petición POST y usamos timeout para evitar esperas indefinidas.
        respuesta = requests.post(api_url, json=payload, headers=headers, timeout=10)
        respuesta.raise_for_status()

        # 6) Devolvemos el JSON de la API para que el proceso pueda validar el resultado.
        return respuesta.json()
    except requests.exceptions.RequestException as error:
        # 7) Capturamos cualquier error de red o de respuesta HTTP.
        print(f"❌ Error al enviar la venta a la API: {error}")
        return None


def cargar_medicamentos_bd():
    """Carga los medicamentos activos. Lanza excepción si la BD no está
    disponible: el POS debe mostrar un error claro, no un catálogo vacío."""
    conexion = conectar_bd()
    medicamentos = []

    if not conexion:
        raise RuntimeError("No se pudo conectar a la base de datos.")
    try:
        cursor = conexion.cursor()
        try:
            # 1. Probamos hacer un SELECT general primero para ver si hay filas
            cursor.execute("SELECT COUNT(*) FROM medicamentos")#seleccionar y contar todas las filas de la tabla medicamentos
            total_filas = cursor.fetchone()[0]#obtine ese valor y lo guarda en la variable total_filas
            print(f"🔍 [DEBUG DB]: Total de filas en la tabla medicamentos: {total_filas}")

            # 2. La consulta normal con el filtro de activos
            cursor.execute("""
                SELECT id, nombre, componente, laboratorio, precio, stock, requiere_receta, ventas_totales,
                       codigo_barras, fecha_vencimiento, unidades_por_blister, precio_blister
                FROM medicamentos
                WHERE activo = 1
            """)
            resultados = cursor.fetchall()
            print(f"🔍 [DEBUG DB]: Filas encontradas con activo = 1: {len(resultados)}")

            # 3. Cargamos TODAS las presentaciones activas en una sola consulta
            #    y las agrupamos por medicamento_id (evita N+1 queries).
            #    Si la migración agregar_presentaciones.sql aún no se ejecutó,
            #    se continúa con lista vacía (solo venta por unidad).
            presentaciones_por_med = {}
            try:
                cursor.execute(
                    "SELECT id, medicamento_id, nombre, factor, precio "
                    "FROM presentaciones WHERE activo = 1 ORDER BY factor"
                )
                for p in cursor.fetchall():
                    presentaciones_por_med.setdefault(int(p[1]), []).append({
                        "id": int(p[0]),
                        "nombre": str(p[2]),
                        "factor": float(p[3]),
                        "precio": float(p[4]),
                    })
            except Exception as e_pres:
                print(f"⚠️ Tabla 'presentaciones' no disponible (¿falta migración?): {e_pres}")

            for fila in resultados:
                med_id = int(fila[0])
                med = Medicamento(
                    id=med_id,
                    nombre=fila[1],
                    componente=fila[2],
                    laboratorio=fila[3],
                    precio=float(fila[4]),
                    stock=int(fila[5]),
                    requiere_receta=bool(fila[6]),
                    ventas_totales=float(fila[7]),
                    codigo_barras=fila[8],
                    fecha_vencimiento=fila[9],
                    unidades_por_blister=int(fila[10]) if fila[10] else 1,
                    precio_blister=float(fila[11]) if fila[11] else None,
                    presentaciones=presentaciones_por_med.get(med_id, []),
                )
                medicamentos.append(med)
        finally:
            cursor.close()

        print(f"✅ Se cargaron {len(medicamentos)} medicamentos activos desde MySQL.")
    except Exception as e:
        print(f"❌ ERROR CRÍTICO al cargar de la BD: {e}")
        raise
    finally:
        conexion.close()

    return medicamentos
    
def registrar_nuevo_medicamento(inventario):
    print("\n--- 📝 REGISTRO DE NUEVO MEDICAMENTO ---")
    nombre = input("Nombre comercial (ej: Apronax): ")
    
    existe_duplicado = False
    for med in inventario:
        if nombre.lower() == med.nombre.lower():
            existe_duplicado = True
            break
            
    if existe_duplicado:
        print("❌ Error: El medicamento ya está registrado. Operación cancelada.")
        return

    componente = input("Componente genérico (ej: Naproxeno): ")
    laboratorio = input("Laboratorio (ej: Bayer): ")
    precio = pedir_numero("Precio por unidad (s/.): ", float)
    stock = pedir_numero("Cantidad de stock inicial: ", int)
    
    receta_input = input("¿Requiere receta médica? (si/no): ").lower()
    requiere_receta = True if receta_input == "si" else False
    
    nuevo_med = Medicamento(nombre, componente, laboratorio, precio, stock, requiere_receta)
    inventario.append(nuevo_med)

    guardar_medicamento_bd(nuevo_med)
    print(f"\n✅ ¡{nombre} ha sido agregado al inventario con éxito!")


def eliminar_medicamento_inventario(inventario):
    print("\n--- 🗑️ ELIMINAR / DESCONTINUAR MEDICAMENTO ---")
    busqueda = input("Ingrese el nombre o componente del medicamento a retirar: ").lower()
    
    coincidencias = []
    for med in inventario:
        if busqueda in med.nombre.lower() or busqueda in med.componente.lower():
            coincidencias.append(med)
            
    if len(coincidencias) > 0:
        print("\nResultados encontrados:")
        for i, med in enumerate(coincidencias):
            print(f"[{i + 1}] {med.nombre} ({med.componente}) | Lab: {med.laboratorio}")
            
        seleccion = pedir_numero("\nSelecciona el número del medicamento a descontinuar: ", int)
        
        if 1 <= seleccion <= len(coincidencias):
            med_elegido = coincidencias[seleccion - 1]
            confirmacion = input(f"¿Está seguro de dar de baja '{med_elegido.nombre}'? (si/no): ").lower()
            
            if confirmacion == "si":
                # 1. Borrado lógico en la Base de Datos
                descontinuar_medicamento_bd(med_elegido.nombre)
                # 2. Retirar de la lista en tiempo de ejecución (Python)
                inventario.remove(med_elegido)
                print(f"✅ Se retiró '{med_elegido.nombre}' del inventario activo.")
            else:
                print(" Operación cancelada.")
        else:
            print("❌ Selección fuera de rango.")
    else:
        print("❌ No se encontraron medicamentos que coincidan.")


def ver_reporte_ganancias(inventario):
    print("\n--- 📊 REPORTE DE GANANCIAS TOTALES ---")
    gran_total = 0.0
    for med in inventario:
        if med.ventas_totales > 0:
            print(f"💰 {med.nombre}: s/.{med.ventas_totales:.2f} recaudados (Stock actual: {med.stock})")
            gran_total += med.ventas_totales
        
    print(f"\n💵 GANANCIA TOTAL DEL DÍA: s/.{round(gran_total, 2):.2f}")


def reabastecer_stock_medicamento(inventario):
    print("\n--- 📝 REGISTRO DE NUEVO STOCK DE MEDICAMENTO ---")
    busqueda = input("¿Qué medicamento o componente buscas? (ej: Panadol / Paracetamol): ").lower()
    
    coincidencias = []
    for med in inventario:
        if busqueda in med.nombre.lower() or busqueda in med.componente.lower():
            coincidencias.append(med)
        
    if len(coincidencias) > 0:
        print("\nResultados encontrados:")
        for i, med in enumerate(coincidencias):
            print(f"[{i + 1}] {med.nombre} ({med.componente}) | Lab: {med.laboratorio} | Stock: {med.stock}")
            
        seleccion = pedir_numero("\nSelecciona el número del medicamento a reabastecer: ", int)
            
        if 1 <= seleccion <= len(coincidencias):
            med_elegido = coincidencias[seleccion - 1]
            cantidad = pedir_numero(f"Escriba la cantidad de {med_elegido.nombre} a agregar: ", int)
            med_elegido.reabastecer_stock(cantidad)

            guardar_medicamento_bd(med_elegido)
        else:
            print("❌ Selección fuera de rango. Operación cancelada.")
    else:
        print("❌ No se encontraron medicamentos que coincidan con tu búsqueda.")


# =========================================================
# CAMBIO CLAVE 3: FLUJO DE VENTA DEL CLIENTE
# =========================================================
# Aquí se valida receta, stock, tipo de comprobante y se
# procesa la venta desde la interfaz del usuario.
# =========================================================
def realizar_venta_cliente(inventario):
    print("\n=== 🔍 BIENVENIDO A LA FARMACIA INTERACTIVA ===")
    # Inicia la sesión de compra del cliente con un carrito vacío.
    # Cada producto agregado vive solo dentro de esta venta hasta finalizar.
    carrito = []

    while True:
        print("\n--- 🛒 OPCIONES DE COMPRA ---")
        print("1. Agregar producto al carrito")
        print("2. Ver carrito")
        print("3. Finalizar compra")
        print("4. Cancelar venta")

        # Pedimos una opción numérica; si no es válida, repetimos.
        opcion_venta = pedir_numero("Seleccione una opción: ", int)

        if opcion_venta == 1:
            # El cliente busca un medicamento por nombre o componente.
            print(f"DEBUG: Medicamentos cargados actualmente en memoria: {len(inventario)}")
            busqueda = input("¿Qué medicamento o componente buscas? (ej: Panadol / Paracetamol): ").lower()

            coincidencias = []
            for med in inventario:
                # Buscamos coincidencias en nombre o componente.
                if busqueda in med.nombre.lower() or busqueda in med.componente.lower():
                    coincidencias.append(med)

            print(f"DEBUG: Coincidencias encontradas para '{busqueda}': {len(coincidencias)}")

            if len(coincidencias) > 0:
                print("\nResultados encontrados:")
                for i, med in enumerate(coincidencias):
                    print(f"[{i + 1}] ", end="")
                    med.mostrar_info()

                seleccion = pedir_numero("\nSelecciona el número del medicamento que deseas agregar: ", int)

                if 1 <= seleccion <= len(coincidencias):
                    med_elegido = coincidencias[seleccion - 1]

                    if med_elegido.requiere_receta:
                        # Si el medicamento necesita receta, solo se continúa la venta si el cliente la tiene.
                        print(f"⚠️ ATENCIÓN: {med_elegido.nombre} requiere receta médica.")
                        receta = input("¿El cliente cuenta con receta física/digital? (si/no): ").lower()
                        if receta != "si":
                            print("❌ Venta cancelada. No se puede vender este producto sin receta médica.")
                            continue

                    cantidad = pedir_numero(f"¿Cuántas unidades de {med_elegido.nombre} deseas agregar?: ", int)

                    if cantidad <= med_elegido.stock:
                        # Convertimos el precio y la cantidad a Decimal para evitar errores numéricos.
                        precio_exacto = Decimal(str(med_elegido.precio))
                        cantidad_exacta = Decimal(str(cantidad))
                        subtotal = (precio_exacto * cantidad_exacta).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                        # Cada item del carrito es un diccionario con:
                        #   medicamento, cantidad y subtotal.
                        # Si el mismo medicamento ya existe, agregar_al_carrito
                        # suma las cantidades y actualiza el subtotal.
                        agregar_al_carrito(carrito, med_elegido, cantidad, subtotal)
                        print(f"✅ {cantidad} unidades agregadas al carrito.")
                    else:
                        print(f"❌ Stock insuficiente. Quedan {med_elegido.stock} unidades.")
                else:
                    print("❌ Selección fuera de rango. Operación cancelada.")
            else:
                print("❌ No se encontraron medicamentos que coincidan con tu búsqueda.")

        elif opcion_venta == 2:
            # Muestra el carrito tal como está actualmente en memoria RAM.
            mostrar_carrito(carrito)

        elif opcion_venta == 3:
            # Si el carrito está vacío no se puede finalizar la compra.
            if not carrito:
                print("❌ Tu carrito está vacío. Agrega productos antes de finalizar.")
                continue

            print("\n--- TIPO DE COMPROBANTE ---")
            print("1. Boleta de Venta (DNI)")
            print("2. Factura (RUC)")
            tipo_op = pedir_numero("Seleccione tipo de comprobante: ", int)

            if tipo_op == 2:
                tipo_comp = "FACTURA"
                doc_cli = input("Ingrese RUC del cliente (11 dígitos): ")
                nombre_cli = input("Ingrese Razón Social / Empresa: ")
            else:
                tipo_comp = "BOLETA"
                doc_cli = input("Ingrese DNI del cliente (8 dígitos): ")
                nombre_cli = input("Ingrese Nombre Completo del Cliente: ")

            # Antes de registrar la venta, confirmamos nuevamente el stock.
            # Esto evita vender artículos que se hayan quedado sin existencias.
            for item in carrito:
                if item["cantidad"] > item["medicamento"].stock:
                    print(f"❌ Stock insuficiente para {item['medicamento'].nombre}.")
                    return

            # Registramos el comprobante completo en la base de datos.
            resultado_venta = registrar_venta_carrito_bd(tipo_comp, doc_cli, nombre_cli, carrito)

            if resultado_venta is not None:
                # Solo después de que la BD registre la venta, actualizamos el inventario local.
                for item in carrito:
                    medicamento = item["medicamento"]  # Extraemos el objeto Medicamento del item del carrito.
                    if medicamento.descontar_stock(item["cantidad"]):  # Descontamos el stock en memoria RAM.
                        ventas_actuales_decimal = Decimal(str(medicamento.ventas_totales))
                        medicamento.ventas_totales = (ventas_actuales_decimal + item["subtotal"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    else:
                        print(f"❌ Error al descontar el stock de {medicamento.nombre}.")

                # Preparamos el JSON con los datos de la venta.
                venta_api = preparar_json_api(
                    tipo_comprobante=tipo_comp,
                    serie=resultado_venta["serie"],
                    correlativo=resultado_venta["correlativo"],
                    tipo_documento="RUC" if tipo_comp == "FACTURA" else "DNI",
                    documento=doc_cli,
                    nombre_cliente=nombre_cli,
                    carrito=carrito,
                    subtotal=(calcular_total_carrito(carrito) / Decimal("1.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    igv=(calcular_total_carrito(carrito) - (calcular_total_carrito(carrito) / Decimal("1.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    total=calcular_total_carrito(carrito),
                )

                # Enviamos el JSON a la API en modo simulación seguro.
                api_resultado = enviar_venta_api(venta_api)
                if api_resultado:
                    print("✅ La venta fue enviada al servicio de facturación electrónica en modo simulación.")
                else:
                    print("⚠️ La venta no pudo enviarse a la API de facturación, pero el proceso local continuó.")

                # Generamos el comprobante físico en disco solo después de que la venta se guardó localmente.
                generar_archivo_comprobante_carrito(
                    tipo_comp,
                    resultado_venta["serie"],
                    resultado_venta["correlativo"],
                    doc_cli,
                    carrito,
                    calcular_total_carrito(carrito)
                )

                print(f"\n✅ Venta exitosa en sistema. Total pagado: s/.{calcular_total_carrito(carrito):.2f}")
                break
            else:
                print("❌ No se pudo completar la venta. Intenta nuevamente.")

        elif opcion_venta == 4:
            # El cliente decide cancelar la venta y el carrito se descarta.
            print("🛑 Venta cancelada. El carrito se ha descartado.")
            break

        else:
            # Respuesta segura para cualquier opción inválida.
            print("❌ Opción no válida. Intente de nuevo.")


# ==========================================
# CICLO PRINCIPAL DE LA APLICACIÓN
# ==========================================
if __name__ == "__main__":
    # Cargamos el inventario inicial desde la base de datos.
    inventario = cargar_medicamentos_bd()
    print(f"🛠️ [CONTROL DE ARRANQUE] Total de medicamentos en memoria: {len(inventario)}")

    while True:
        # Menú principal que separa modos de cliente y administrador.
        print("\n=========================================")
        print("      SISTEMA DE FARMACIA INTERACTIVA    ")
        print("=========================================")
        print("1. Entrar como Cliente / Paciente")
        print("2. Entrar como Administrador / Farmacéutico")
        print("3. Cerrar Farmacia y Salir")
        
        rol = pedir_numero("Seleccione una opción: ")
        
        if rol == 1:
            # Modo cliente: venta desde carrito y comprobante.
            realizar_venta_cliente(inventario)
        elif rol == 2:
            # Modo administrador: gestión de catalogo y stock.
            print("\n--- 🛠️ MODO ADMINISTRADOR ---")
            print("1. Registrar nuevo medicamento")
            print("2. Ver reporte de ganancias totales")
            print("3. Reabastecer medicamentos en el stock")
            print("4. Descontinuar / Eliminar medicamento")
            print("5. Volver al menú principal")
            
            opcion_admin = pedir_numero("Seleccione una opción de administrador: ")
            
            if opcion_admin == 1:
                registrar_nuevo_medicamento(inventario)
            elif opcion_admin == 2:
                ver_reporte_ganancias(inventario)
            elif opcion_admin == 3:
                reabastecer_stock_medicamento(inventario)
            elif opcion_admin == 4:
                eliminar_medicamento_inventario(inventario)
            elif opcion_admin == 5:
                print("🔄 Regresando al menú principal...")
            else:
                print("❌ Opción de administrador no válida.")
                
        elif rol == 3:
            # Finalizamos el programa.
            print("\nCerrando el sistema...")
            print("👋 ¡Hasta luego! Datos guardados en tiempo real en MySQL.")
            break
            
        else:
            print("❌ Opción no válida. Intente de nuevo.")
