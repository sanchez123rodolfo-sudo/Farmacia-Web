-- =========================================================
-- Migración: Agregar soporte para venta por Unidad y Blíster
-- Agrega las columnas `unidades_por_blister` y `precio_blister`
-- a la tabla `medicamentos`.
-- Idempotente: verifica antes de crear cada columna.
-- Ejecutar con: mysql -u root -p farmacia_db < agregar_venta_por_blister.sql
-- =========================================================
SET @db = 'farmacia_db';

-- 1) Columna unidades_por_blister (cuántas pastillas tiene un blíster)
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos' AND COLUMN_NAME = 'unidades_por_blister'
  ),
  'ALTER TABLE `medicamentos` ADD COLUMN `unidades_por_blister` INT NULL DEFAULT 1 AFTER `stock`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) Columna precio_blister (precio con descuento por el blíster completo)
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos' AND COLUMN_NAME = 'precio_blister'
  ),
  'ALTER TABLE `medicamentos` ADD COLUMN `precio_blister` DECIMAL(10,2) NULL AFTER `precio`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Verificación final
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos'
  AND COLUMN_NAME IN ('unidades_por_blister', 'precio_blister')
ORDER BY ORDINAL_POSITION;

SELECT 'Migración completada: unidades_por_blister y precio_blister agregados.' AS resultado;
