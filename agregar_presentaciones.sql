-- =========================================================
-- Migración: Presentaciones dinámicas con factores de conversión
--
-- Concepto:
--   - El stock de `medicamentos` SIEMPRE se mide en su unidad mínima
--     (tableta, mililitro, gramo, unidad).
--   - Cada producto puede definir N presentaciones de venta en la tabla
--     `presentaciones` (Caja, Blíster, Frasco, Tubo...), cada una con su
--     `factor_conversion` = cuántas unidades base contiene y su `precio`.
--   - Al vender: unidades_a_descontar = cantidad * factor_conversion.
--
-- Idempotente: verifica antes de crear tablas/columnas/filas.
-- Ejecutar con: mysql -u root -p farmacia_db < agregar_presentaciones.sql
-- =========================================================
SET @db = 'farmacia_db';

-- 1) Tabla de presentaciones (una fila por cada forma de venta del producto)
CREATE TABLE IF NOT EXISTS `presentaciones` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `medicamento_id` INT NOT NULL,
    `nombre` VARCHAR(50) NOT NULL COMMENT 'Etiqueta visible en el POS: Caja, Blister, Frasco...',
    `factor_conversion` DECIMAL(10,2) NOT NULL DEFAULT 1 COMMENT 'Unidades base que contiene esta presentación',
    `precio` DECIMAL(10,2) NOT NULL COMMENT 'Precio de venta por esta presentación',
    `activo` TINYINT(1) NOT NULL DEFAULT 1,
    `creado_en` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uq_medicamento_presentacion` (`medicamento_id`, `nombre`),
    CONSTRAINT `fk_pres_medicamento` FOREIGN KEY (`medicamento_id`)
        REFERENCES `medicamentos`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) Auditoría en el detalle de venta: qué presentación se vendió y con qué factor
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'detalle_comprobantes' AND COLUMN_NAME = 'presentacion_id'
  ),
  'ALTER TABLE `detalle_comprobantes` ADD COLUMN `presentacion_id` INT NULL AFTER `subtotal_linea`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'detalle_comprobantes' AND COLUMN_NAME = 'presentacion_nombre'
  ),
  'ALTER TABLE `detalle_comprobantes` ADD COLUMN `presentacion_nombre` VARCHAR(50) NULL AFTER `presentacion_id`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'detalle_comprobantes' AND COLUMN_NAME = 'factor_conversion'
  ),
  'ALTER TABLE `detalle_comprobantes` ADD COLUMN `factor_conversion` DECIMAL(10,2) NULL AFTER `presentacion_nombre`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3) Migración de datos: convertir las columnas antiguas de blíster
--    (unidades_por_blister / precio_blister) en filas de la nueva tabla.
INSERT INTO `presentaciones` (`medicamento_id`, `nombre`, `factor_conversion`, `precio`, `activo`)
SELECT m.id, 'Blíster', m.unidades_por_blister, m.precio_blister, 1
FROM medicamentos m
WHERE m.activo = 1
  AND m.unidades_por_blister IS NOT NULL
  AND m.unidades_por_blister > 1
  AND m.precio_blister IS NOT NULL
  AND m.precio_blister > 0
ON DUPLICATE KEY UPDATE `precio` = VALUES(`precio`);

-- =========================================================
-- EJEMPLOS de nuevas presentaciones (descomenta y ajusta):
--
-- Caja de 30 tabletas a S/ 45.00 para 'Paracetamol 500mg':
-- INSERT INTO presentaciones (medicamento_id, nombre, factor_conversion, precio)
-- SELECT id, 'Caja', 30, 45.00 FROM medicamentos WHERE LOWER(nombre) = LOWER('Paracetamol 500mg');
--
-- Frasco de 120 ml a S/ 18.50 para un jarabe (el stock se cuenta en ml):
-- INSERT INTO presentaciones (medicamento_id, nombre, factor_conversion, precio)
-- SELECT id, 'Frasco 120ml', 120, 18.50 FROM medicamentos WHERE LOWER(nombre) = LOWER('Jarabe X');
-- =========================================================

-- Verificación final
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'detalle_comprobantes'
  AND COLUMN_NAME IN ('presentacion_id', 'presentacion_nombre', 'factor_conversion')
ORDER BY ORDINAL_POSITION;

SELECT p.nombre AS presentacion, m.nombre AS medicamento,
       p.factor_conversion, p.precio
FROM presentaciones p
JOIN medicamentos m ON m.id = p.medicamento_id
ORDER BY m.nombre, p.factor_conversion;

SELECT 'Migración completada: ventas por presentación dinámica habilitadas.' AS resultado;
