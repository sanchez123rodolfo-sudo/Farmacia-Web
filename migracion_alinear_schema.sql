-- =========================================================
-- Migración: Alinear schema real con el código del sistema.
--
-- La BD real quedó desactualizada frente al código actual:
--  1) La tabla `presentaciones` NO tiene la columna `activo`
--     (borrado lógico) que el código usa en sus consultas
--     (WHERE activo = 1, desactivar_presentacion_bd).
--  2) `detalle_comprobantes` no guarda la auditoría de la
--     presentación vendida (presentacion_id, presentacion_nombre, factor).
--
-- Este script es IDEMPOTENTE: cada paso verifica antes de alterar.
-- Crea/actualiza SOLO lo que falta; no borra ningún dato.
-- Ejecutar con: mysql -u root -p farmacia_db < migracion_alinear_schema.sql
-- =========================================================
SET @db = 'farmacia_db';

-- 1) Borrado lógico en presentaciones: columna `activo`
--    (1 = activa, 0 = desactivada). Las existentes quedan activas.
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'presentaciones' AND COLUMN_NAME = 'activo'
  ),
  'ALTER TABLE `presentaciones` ADD COLUMN `activo` TINYINT(1) NOT NULL DEFAULT 1 COMMENT ''1 = activa, 0 = desactivada'' AFTER `precio`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) Auditoría de la presentación vendida en el detalle de venta.
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
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'detalle_comprobantes' AND COLUMN_NAME = 'factor'
  ),
  'ALTER TABLE `detalle_comprobantes` ADD COLUMN `factor` DECIMAL(10,2) NULL AFTER `presentacion_nombre`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3) Datos históricos: convertir unidades_por_blister/precio_blister
--    de medicamentos en presentaciones dinámicas (idempotente).
INSERT INTO `presentaciones` (`medicamento_id`, `nombre`, `factor`, `precio`, `activo`)
SELECT m.id, 'Blíster', m.unidades_por_blister, m.precio_blister, 1
FROM medicamentos m
WHERE m.activo = 1
  AND m.unidades_por_blister IS NOT NULL
  AND m.unidades_por_blister > 1
  AND m.precio_blister IS NOT NULL
  AND m.precio_blister > 0
ON DUPLICATE KEY UPDATE `precio` = VALUES(`precio`);

-- 4) Verificación final: columnas que el código espera.
SELECT TABLE_NAME, COLUMN_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @db
  AND ((TABLE_NAME = 'presentaciones' AND COLUMN_NAME = 'activo')
       OR (TABLE_NAME = 'detalle_comprobantes'
           AND COLUMN_NAME IN ('presentacion_id', 'presentacion_nombre', 'factor')))
ORDER BY TABLE_NAME, COLUMN_NAME;