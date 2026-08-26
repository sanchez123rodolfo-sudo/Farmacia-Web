-- Script idempotente: agrega las columnas de pago a la tabla comprobantes.
-- Se puede ejecutar varias veces sin error: solo crea lo que falta.
-- IMPORTANTE: edita el nombre de la BD en la línea de abajo si es necesario.
SET @db = 'farmacia_db';

-- Columna metodo_pago
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'comprobantes' AND COLUMN_NAME = 'metodo_pago'
  ),
  'ALTER TABLE `comprobantes` ADD COLUMN `metodo_pago` VARCHAR(20) NULL AFTER `total`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Columna monto_pagado
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'comprobantes' AND COLUMN_NAME = 'monto_pagado'
  ),
  'ALTER TABLE `comprobantes` ADD COLUMN `monto_pagado` DECIMAL(10,2) NULL AFTER `metodo_pago`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Columna numero_operacion
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'comprobantes' AND COLUMN_NAME = 'numero_operacion'
  ),
  'ALTER TABLE `comprobantes` ADD COLUMN `numero_operacion` VARCHAR(30) NULL AFTER `monto_pagado`',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
