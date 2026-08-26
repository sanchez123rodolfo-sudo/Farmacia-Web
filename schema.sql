-- =========================================================
-- schema.sql — Esquema completo y unificado de la base de datos
--              para el Sistema de Farmacia Interactiva
--
-- Generado a partir del analisis exhaustivo de:
--   - Practica_POO_Farmacia.py  (capa de acceso a datos)
--   - app.py                    (endpoints Flask)
--   - sunat_service.py          (integracion SUNAT)
--   - query_db.py               (consultas de auditoria)
--   - 7 archivos de migracion .sql existentes
--
-- Ejecutar con:
--   mysql -u root -p < schema.sql
--   o desde MySQL Workbench: File > Open SQL Script > schema.sql
--
-- Base de datos: farmacia_db
-- Motor: InnoDB (soporta transacciones y FOREIGN KEYs)
-- Charset: utf8mb4 (soporte completo para caracteres unicode)
-- =========================================================

-- ── 1. CREAR LA BASE DE DATOS ─────────────────────────────
CREATE DATABASE IF NOT EXISTS `farmacia_db`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `farmacia_db`;

-- Desactivar verificacion de FKs durante la creacion para
-- evitar orden de dependencias problematico.
SET @old_foreign_checks = @@foreign_key_checks;
SET foreign_key_checks = 0;


-- =========================================================
-- 2. TABLA: medicamentos
-- =========================================================
-- Inventario principal de productos farmaceuticos.
-- El stock SIEMPRE se mide en unidades minimas (tableta,
-- mililitro, gramo, unidad). Las presentaciones (Caja,
-- Blister, Frasco) convierten sus cantidades a unidades
-- base usando factor_conversion en la tabla presentaciones.
-- =========================================================
CREATE TABLE IF NOT EXISTS `medicamentos` (
    `id`                    INT             AUTO_INCREMENT PRIMARY KEY,
    `nombre`                VARCHAR(150)    NOT NULL,
    `categoria`             VARCHAR(100)    NULL,
    `codigo_barras`         VARCHAR(50)     NULL,
    `componente`            VARCHAR(150)    NULL,
    `laboratorio`           VARCHAR(150)    NULL,
    `precio`                DECIMAL(10,2)   NOT NULL DEFAULT 0.00
                            COMMENT 'Precio por unidad minima (tableta/ml/und)',
    `precio_blister`        DECIMAL(10,2)   NULL
                            COMMENT 'DEPRECATED: usar tabla presentaciones',
    `stock`                 INT             NOT NULL DEFAULT 0
                            COMMENT 'Siempre en unidades minimas',
    `unidades_por_blister`  INT             NULL DEFAULT 1
                            COMMENT 'DEPRECATED: usar tabla presentaciones',
    `requiere_receta`       TINYINT(1)      NOT NULL DEFAULT 0,
    `ventas_totales`        DECIMAL(10,2)   NOT NULL DEFAULT 0.00
                            COMMENT 'Suma de subtotales de todas las ventas',
    `fecha_vencimiento`     DATE            NULL,
    `activo`                TINYINT(1)      NOT NULL DEFAULT 1
                            COMMENT '0 = descontinuado (borrado logico)',

    UNIQUE KEY `uc_nombre` (`nombre`),
    UNIQUE KEY `uc_codigo_barras` (`codigo_barras`),
    INDEX `idx_fecha_vencimiento` (`fecha_vencimiento`),
    INDEX `idx_activo` (`activo`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =========================================================
-- 3. TABLA: presentaciones
-- =========================================================
-- Formas de venta para cada medicamento (Caja, Blister,
-- Frasco, Tubo, etc.). Cada presentacion declara cuantas
-- unidades base contiene (factor_conversion) y su precio.
--
-- Al vender: unidades_a_descontar = cantidad * factor_conversion
-- Ejemplo: 2 Cajas x factor 30 = -60 tabletas del stock.
-- =========================================================
CREATE TABLE IF NOT EXISTS `presentaciones` (
    `id`                INT             AUTO_INCREMENT PRIMARY KEY,
    `medicamento_id`    INT             NOT NULL,
    `nombre`            VARCHAR(50)     NOT NULL
                        COMMENT 'Etiqueta visible en el POS: Caja, Blister, Frasco...',
    `factor_conversion` DECIMAL(10,2)   NOT NULL DEFAULT 1
                        COMMENT 'Unidades base que contiene esta presentacion',
    `precio`            DECIMAL(10,2)   NOT NULL
                        COMMENT 'Precio de venta por esta presentacion',
    `activo`            TINYINT(1)      NOT NULL DEFAULT 1,
    `creado_en`         TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY `uq_medicamento_presentacion` (`medicamento_id`, `nombre`),
    CONSTRAINT `fk_pres_medicamento`
        FOREIGN KEY (`medicamento_id`)
        REFERENCES `medicamentos`(`id`)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =========================================================
-- 4. TABLA: clientes
-- =========================================================
-- Registro de clientes (personas naturales con DNI o
-- empresas con RUC). Se usa upsert (ON DUPLICATE KEY UPDATE)
-- para evitar duplicados por numero_documento.
-- =========================================================
CREATE TABLE IF NOT EXISTS `clientes` (
    `id`                    INT             AUTO_INCREMENT PRIMARY KEY,
    `tipo_documento`        VARCHAR(10)     NOT NULL DEFAULT 'DNI'
                            COMMENT 'DNI o RUC',
    `numero_documento`      VARCHAR(15)     NOT NULL
                            COMMENT '8 digitos (DNI) o 11 digitos (RUC)',
    `nombre_razon_social`   VARCHAR(200)    NOT NULL,
    `direccion`             VARCHAR(200)    NULL,

    UNIQUE KEY `uc_numero_documento` (`numero_documento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =========================================================
-- 5. TABLA: comprobantes
-- =========================================================
-- Cabecera de cada venta emitida. Contiene los totales,
-- metodo de pago y datos del cliente.
-- Tipos: BOLETA (DNI), FACTURA (RUC), NOTA_VENTA.
-- Serie: B001 (boleta), F001 (factura), NV01 (nota venta).
-- El correlativo es autoincremental por serie con
-- proteccion contra carreras (UNIQUE + retry en Python).
-- =========================================================
CREATE TABLE IF NOT EXISTS `comprobantes` (
    `id`                INT             AUTO_INCREMENT PRIMARY KEY,
    `tipo_comprobante`  VARCHAR(20)     NOT NULL
                        COMMENT 'BOLETA, FACTURA o NOTA_VENTA',
    `serie`             VARCHAR(4)      NOT NULL
                        COMMENT 'B001, F001, NV01',
    `correlativo`       INT             NOT NULL,
    `fecha`             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `cliente_id`        INT             NULL,
    `subtotal`          DECIMAL(10,2)   NOT NULL DEFAULT 0.00
                        COMMENT 'Base gravable (total / 1.18)',
    `igv`               DECIMAL(10,2)   NOT NULL DEFAULT 0.00
                        COMMENT 'Impuesto General a las Ventas (18%)',
    `total`             DECIMAL(10,2)   NOT NULL DEFAULT 0.00
                        COMMENT 'subtotal + igv',
    `metodo_pago`       VARCHAR(20)     NULL
                        COMMENT 'Efectivo, Yape, Plin, Tarjeta',
    `monto_pagado`      DECIMAL(10,2)   NULL
                        COMMENT 'Monto recibido del cliente',
    `numero_operacion`  VARCHAR(30)     NULL
                        COMMENT 'Codigo de operacion Yape/Plin/voucher',

    UNIQUE KEY `uq_serie_correlativo` (`serie`, `correlativo`),
    INDEX `idx_fecha` (`fecha`),
    INDEX `idx_cliente` (`cliente_id`),

    CONSTRAINT `fk_comp_cliente`
        FOREIGN KEY (`cliente_id`)
        REFERENCES `clientes`(`id`)
        ON DELETE SET NULL
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =========================================================
-- 6. TABLA: detalle_comprobantes
-- =========================================================
-- Linea por linea de cada comprobante. Guarda copia del
-- precio, presentacion y factor_conversion para preservar
-- la integridad historica aunque el producto cambie de
-- precio o se desactive una presentacion.
-- =========================================================
CREATE TABLE IF NOT EXISTS `detalle_comprobantes` (
    `id`                    INT             AUTO_INCREMENT PRIMARY KEY,
    `comprobante_id`        INT             NOT NULL,
    `medicamento_id`        INT             NOT NULL,
    `cantidad`              INT             NOT NULL
                            COMMENT 'Unidades vendidas (en terminos de la presentacion)',
    `precio_unitario`       DECIMAL(10,2)   NOT NULL
                            COMMENT 'Precio al momento de la venta',
    `subtotal_linea`        DECIMAL(10,2)   NOT NULL
                            COMMENT 'cantidad * precio_unitario',
    `presentacion_id`       INT             NULL
                            COMMENT 'FK -> presentaciones.id (NULL = venta por unidad)',
    `presentacion_nombre`   VARCHAR(50)     NULL
                            COMMENT 'Copia del nombre de la presentacion (auditoria)',
    `factor_conversion`     DECIMAL(10,2)   NULL
                            COMMENT 'Copia del factor al momento de la venta (auditoria)',

    INDEX `idx_comprobante` (`comprobante_id`),
    INDEX `idx_medicamento` (`medicamento_id`),

    CONSTRAINT `fk_detalle_comprobante`
        FOREIGN KEY (`comprobante_id`)
        REFERENCES `comprobantes`(`id`)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    CONSTRAINT `fk_detalle_medicamento`
        FOREIGN KEY (`medicamento_id`)
        REFERENCES `medicamentos`(`id`)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    CONSTRAINT `fk_detalle_presentacion`
        FOREIGN KEY (`presentacion_id`)
        REFERENCES `presentaciones`(`id`)
        ON DELETE SET NULL
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =========================================================
-- 7. TABLA: comprobantes_pendientes_sunat
-- =========================================================
-- Tabla auxiliar para facturacion electronica.
-- Almacena comprobantes que SUNAT rechazo o que aun no
-- se pudieron enviar (error de red). El administrador
-- puede revisar, corregir y reenviar desde el panel.
--
-- El comprobante original en `comprobantes` NUNCA se borra
-- para garantizar la trazabilidad contable.
-- =========================================================
CREATE TABLE IF NOT EXISTS `comprobantes_pendientes_sunat` (
    `id`                    INT             AUTO_INCREMENT PRIMARY KEY,
    `comprobante_id`        INT             NOT NULL
                            COMMENT 'FK -> comprobantes.id (la venta ya esta guardada)',
    `tipo_comprobante`      VARCHAR(20)     NOT NULL,
    `serie`                 VARCHAR(4)      NOT NULL,
    `correlativo`           INT             NOT NULL,
    `estado`                VARCHAR(15)     NOT NULL DEFAULT 'PENDIENTE'
                            COMMENT 'PENDIENTE, RECHAZADO, ENVIADO, ACEPTADO',
    `codigo_respuesta`      VARCHAR(10)     NULL
                            COMMENT 'Codigo HTTP o codigo de SUNAT (ej: 200, 0001)',
    `mensaje_respuesta`     TEXT            NULL
                            COMMENT 'Mensaje descriptivo de SUNAT o error interno',
    `hash_cdr`              VARCHAR(128)    NULL
                            COMMENT 'Hash del CDR cuando es aceptado',
    `xml_respuesta`         TEXT            NULL
                            COMMENT 'XML completo de respuesta de SUNAT',
    `intentos`              INT             NOT NULL DEFAULT 1,
    `max_intentos`          INT             NOT NULL DEFAULT 3,
    `payload_sunat`         JSON            NULL
                            COMMENT 'JSON que se envio a SUNAT para auditoria',
    `fecha_primer_intento`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `fecha_ultimo_intento`  DATETIME        NULL,
    `creado_en`             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `actualizado_en`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,

    INDEX `idx_estado` (`estado`),
    INDEX `idx_comprobante` (`comprobante_id`),

    CONSTRAINT `fk_sunat_comprobante`
        FOREIGN KEY (`comprobante_id`)
        REFERENCES `comprobantes`(`id`)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Restaurar verificacion de FKs
SET foreign_key_checks = @old_foreign_checks;


-- =========================================================
-- 8. DATOS INICIALES (Opcional)
-- =========================================================
-- Descomenta y edita si quieres poblar la BD con datos
-- de prueba al crearla.
-- =========================================================

-- INSERT INTO `medicamentos`
--   (nombre, categoria, componente, laboratorio, precio, stock, requiere_receta, activo)
-- VALUES
--   ('Paracetamol 500mg', 'Analgesico', 'Paracetamol', 'Farmacias Peru', 12.50, 100, 0, 1),
--   ('Amoxicilina 250mg', 'Antibiotico', 'Amoxicilina', 'Lab.Generico', 28.00, 50, 1, 1),
--   ('Ibuprofeno 400mg', 'Antiinflamatorio', 'Ibuprofeno', 'Bayer', 15.00, 80, 0, 1),
--   ('Omeprazol 20mg', 'Gastrointestinal', 'Omeprazol', 'Farmacias Peru', 22.00, 60, 0, 1),
--   ('Vitamina C', 'Vitaminas', 'Acido ascorbico', 'Farmacias Peru', 18.50, 200, 0, 1);


-- =========================================================
-- VERIFICACION FINAL
-- =========================================================
-- Ejecuta estas consultas para confirmar que todo se creo
-- correctamente.
-- =========================================================
SELECT 'Tables created:' AS info;
SELECT TABLE_NAME, TABLE_ROWS, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'farmacia_db'
ORDER BY TABLE_NAME;

SELECT 'Foreign keys:' AS info;
SELECT
    kcu.TABLE_NAME,
    kcu.COLUMN_NAME,
    kcu.REFERENCED_TABLE_NAME,
    kcu.REFERENCED_COLUMN_NAME,
    kcu.CONSTRAINT_NAME
FROM information_schema.KEY_COLUMN_USAGE kcu
WHERE kcu.TABLE_SCHEMA = 'farmacia_db'
  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY kcu.TABLE_NAME, kcu.COLUMN_NAME;

SELECT 'Unique constraints:' AS info;
SELECT TABLE_NAME, INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'farmacia_db' AND NON_UNIQUE = 0
GROUP BY TABLE_NAME, INDEX_NAME
ORDER BY TABLE_NAME;

SELECT 'Schema created successfully!' AS resultado;
