-- =========================================================
-- Agrega la columna `codigo_barras` a la tabla `medicamentos`
-- con un índice UNIQUE (permite NULL para productos antiguos).
-- Idempotente: verifica antes de crear columna e índice.
-- Ejecutar con: mysql -u root -p farmacia_db < agregar_codigo_barras_medicamentos.sql
-- =========================================================
SET @db = DATABASE();

-- 1) Columna
SET @sql_col = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos' AND COLUMN_NAME = 'codigo_barras'
  ),
  'ALTER TABLE `medicamentos` ADD COLUMN `codigo_barras` VARCHAR(50) NULL AFTER `categoria`',
  'SELECT 1'
));

PREPARE stmt FROM @sql_col;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 2) Índice UNIQUE (varios NULLs están permitidos en MySQL)
SET @sql_idx = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos' AND INDEX_NAME = 'uc_codigo_barras'
  ),
  'ALTER TABLE `medicamentos` ADD UNIQUE INDEX `uc_codigo_barras` (`codigo_barras`)',
  'SELECT 1'
));

PREPARE stmt FROM @sql_idx;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Verificación final
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos' AND COLUMN_NAME = 'codigo_barras';

SELECT INDEX_NAME, NON_UNIQUE, COLUMN_NAME
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'medicamentos' AND INDEX_NAME = 'uc_codigo_barras';
