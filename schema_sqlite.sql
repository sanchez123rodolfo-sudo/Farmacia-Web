-- Schema adaptado para SQLite (Render Nube)

CREATE TABLE IF NOT EXISTS medicamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    categoria TEXT,
    codigo_barras TEXT UNIQUE,
    componente TEXT,
    laboratorio TEXT,
    precio REAL NOT NULL DEFAULT 0.00,
    precio_blister REAL,
    stock INTEGER NOT NULL DEFAULT 0,
    unidades_por_blister INTEGER DEFAULT 1,
    requiere_receta INTEGER NOT NULL DEFAULT 0,
    ventas_totales REAL NOT NULL DEFAULT 0.00,
    fecha_vencimiento TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS presentaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medicamento_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    factor REAL NOT NULL DEFAULT 1,
    precio REAL NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(medicamento_id, nombre),
    FOREIGN KEY (medicamento_id) REFERENCES medicamentos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_documento TEXT NOT NULL DEFAULT 'DNI',
    numero_documento TEXT NOT NULL UNIQUE,
    nombre_razon_social TEXT NOT NULL,
    direccion TEXT
);

CREATE TABLE IF NOT EXISTS comprobantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_comprobante TEXT NOT NULL,
    serie TEXT NOT NULL,
    correlativo INTEGER NOT NULL,
    fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cliente_id INTEGER,
    subtotal REAL NOT NULL DEFAULT 0.00,
    igv REAL NOT NULL DEFAULT 0.00,
    total REAL NOT NULL DEFAULT 0.00,
    metodo_pago TEXT,
    monto_pagado REAL,
    numero_operacion TEXT,
    UNIQUE(serie, correlativo),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS detalle_comprobantes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comprobante_id INTEGER NOT NULL,
    medicamento_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal_linea REAL NOT NULL,
    presentacion_id INTEGER,
    presentacion_nombre TEXT,
    factor REAL,
    FOREIGN KEY (comprobante_id) REFERENCES comprobantes(id) ON DELETE CASCADE,
    FOREIGN KEY (medicamento_id) REFERENCES medicamentos(id) ON DELETE RESTRICT,
    FOREIGN KEY (presentacion_id) REFERENCES presentaciones(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS comprobantes_pendientes_sunat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comprobante_id INTEGER NOT NULL,
    tipo_comprobante TEXT NOT NULL,
    serie TEXT NOT NULL,
    correlativo INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'PENDIENTE',
    codigo_respuesta TEXT,
    mensaje_respuesta TEXT,
    hash_cdr TEXT,
    xml_respuesta TEXT,
    intentos INTEGER NOT NULL DEFAULT 1,
    max_intentos INTEGER NOT NULL DEFAULT 3,
    payload_sunat TEXT,
    fecha_primer_intento TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_ultimo_intento TEXT,
    creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (comprobante_id) REFERENCES comprobantes(id) ON DELETE CASCADE
);