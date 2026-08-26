-- =========================================================
-- Agrega la columna `categoria` a la tabla `medicamentos`.
-- Idempotente: si la columna ya existe, no hace nada.
-- Ejecutar con: mysql -u root -p farmacia_db < agregar_categoria_medicamentos.sql
-- =========================================================
SET @db = DATABASE();

SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db
      AND TABLE_NAME = 'medicamentos'
      AND COLUMN_NAME = 'categoria'
  ),
  'ALTER TABLE `medicamentos` ADD COLUMN `categoria` VARCHAR(100) NULL AFTER `nombre`',
  'SELECT 1'
));

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos'
ORDER BY ORDINAL_POSITION;
