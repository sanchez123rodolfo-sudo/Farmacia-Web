-- =========================================================
-- schema_postgres.sql — Esquema para PostgreSQL (Supabase / Render)
--
-- Es idempotente (CREATE TABLE IF NOT EXISTS): se ejecuta en cada
-- conexión para garantizar que las tablas existan, sin duplicar nada.
--
-- Tipos usados:
--   - id       : SERIAL primario (compatible con RETURNING id)
--   - dinero   : NUMERIC(10,2) (exacto, como DECIMAL de MySQL)
--   - booleanos: INTEGER 0/1 (mismo comportamiento que TINYINT(1) de MySQL)
--   - fechas   : TIMESTAMP / DATE
--   - payloads : TEXT (JSON serializado en la capa Python)
-- =========================================================

CREATE TABLE IF NOT EXISTS medicamentos (
    id                    SERIAL PRIMARY KEY,
    nombre                VARCHAR(150) NOT NULL,
    categoria             VARCHAR(100),
    codigo_barras         VARCHAR(50),
    componente            VARCHAR(150),
    laboratorio           VARCHAR(150),
    precio                NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    precio_blister        NUMERIC(10,2),
    stock                 INTEGER NOT NULL DEFAULT 0,
    unidades_por_blister  INTEGER DEFAULT 1,
    requiere_receta       INTEGER NOT NULL DEFAULT 0,
    ventas_totales        NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    fecha_vencimiento     DATE,
    activo                INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT uq_medicamentos_nombre UNIQUE (nombre),
    CONSTRAINT uq_medicamentos_codigo_barras UNIQUE (codigo_barras)
);

CREATE INDEX IF NOT EXISTS idx_medicamentos_activo ON medicamentos (activo);
CREATE INDEX IF NOT EXISTS idx_medicamentos_vencimiento ON medicamentos (fecha_vencimiento);

CREATE TABLE IF NOT EXISTS presentaciones (
    id                SERIAL PRIMARY KEY,
    medicamento_id    INTEGER NOT NULL,
    nombre            VARCHAR(50) NOT NULL,
    factor            NUMERIC(10,2) NOT NULL DEFAULT 1,
    precio            NUMERIC(10,2) NOT NULL,
    activo            INTEGER NOT NULL DEFAULT 1,
    creado_en         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_medicamento_presentacion UNIQUE (medicamento_id, nombre),
    CONSTRAINT fk_pres_medicamento FOREIGN KEY (medicamento_id)
        REFERENCES medicamentos (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS clientes (
    id                    SERIAL PRIMARY KEY,
    tipo_documento        VARCHAR(10) NOT NULL DEFAULT 'DNI',
    numero_documento      VARCHAR(15) NOT NULL,
    nombre_razon_social   VARCHAR(200) NOT NULL,
    direccion             VARCHAR(200),
    CONSTRAINT uq_clientes_numero_documento UNIQUE (numero_documento)
);

CREATE TABLE IF NOT EXISTS comprobantes (
    id                SERIAL PRIMARY KEY,
    tipo_comprobante  VARCHAR(20) NOT NULL,
    serie             VARCHAR(4) NOT NULL,
    correlativo       INTEGER NOT NULL,
    fecha             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cliente_id        INTEGER,
    subtotal          NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    igv               NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    total             NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    metodo_pago       VARCHAR(20),
    monto_pagado      NUMERIC(10,2),
    numero_operacion  VARCHAR(30),
    CONSTRAINT uq_serie_correlativo UNIQUE (serie, correlativo),
    CONSTRAINT fk_comp_cliente FOREIGN KEY (cliente_id)
        REFERENCES clientes (id) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comprobantes_fecha ON comprobantes (fecha);

CREATE TABLE IF NOT EXISTS detalle_comprobantes (
    id                    SERIAL PRIMARY KEY,
    comprobante_id        INTEGER NOT NULL,
    medicamento_id        INTEGER NOT NULL,
    cantidad              INTEGER NOT NULL,
    precio_unitario       NUMERIC(10,2) NOT NULL,
    subtotal_linea        NUMERIC(10,2) NOT NULL,
    presentacion_id       INTEGER,
    presentacion_nombre   VARCHAR(50),
    factor                NUMERIC(10,2),
    CONSTRAINT fk_detalle_comprobante FOREIGN KEY (comprobante_id)
        REFERENCES comprobantes (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_detalle_medicamento FOREIGN KEY (medicamento_id)
        REFERENCES medicamentos (id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_detalle_presentacion FOREIGN KEY (presentacion_id)
        REFERENCES presentaciones (id) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_detalle_comprobante_id ON detalle_comprobantes (comprobante_id);

CREATE TABLE IF NOT EXISTS comprobantes_pendientes_sunat (
    id                    SERIAL PRIMARY KEY,
    comprobante_id        INTEGER NOT NULL,
    tipo_comprobante      VARCHAR(20) NOT NULL,
    serie                 VARCHAR(4) NOT NULL,
    correlativo           INTEGER NOT NULL,
    estado                VARCHAR(15) NOT NULL DEFAULT 'PENDIENTE',
    codigo_respuesta      VARCHAR(10),
    mensaje_respuesta     TEXT,
    hash_cdr              VARCHAR(128),
    xml_respuesta         TEXT,
    intentos              INTEGER NOT NULL DEFAULT 1,
    max_intentos          INTEGER NOT NULL DEFAULT 3,
    payload_sunat         TEXT,
    fecha_primer_intento  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_ultimo_intento  TIMESTAMP,
    creado_en             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sunat_comprobante FOREIGN KEY (comprobante_id)
        REFERENCES comprobantes (id) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sunat_estado ON comprobantes_pendientes_sunat (estado);