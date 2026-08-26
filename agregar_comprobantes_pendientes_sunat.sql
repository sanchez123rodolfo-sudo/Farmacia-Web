-- Script idempotente: crea la tabla para comprobantes pendientes o rechazados por SUNAT.
-- Permite al administrador corregir errores y reenviar sin perder la venta.
SET @db = 'farmacia_db';

-- Tabla principal de comprobantes pendientes/rechazados
SET @sql = (SELECT IF(
  NOT EXISTS (
    SELECT 1 FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'comprobantes_pendientes_sunat'
  ),
  'CREATE TABLE `comprobantes_pendientes_sunat` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `comprobante_id` INT NOT NULL COMMENT 'FK -> comprobantes.id (la venta ya está guardada)',
    `tipo_comprobante` ENUM('BOLETA','FACTURA') NOT NULL,
    `serie` VARCHAR(4) NOT NULL,
    `correlativo` INT NOT NULL,
    `estado` ENUM('PENDIENTE','RECHAZADO','ENVIADO','ACEPTADO') DEFAULT 'PENDIENTE',
    `codigo_respuesta` VARCHAR(10) NULL COMMENT 'Código HTTP o código de SUNAT (ej: 200, 0001)',
    `mensaje_respuesta` TEXT NULL COMMENT 'Mensaje descriptivo de SUNAT o error interno',
    `hash_cdr` VARCHAR(128) NULL COMMENT 'Hash del CDR (constancia de recepción) cuando es aceptado',
    `xml_respuesta` TEXT NULL COMMENT 'XML completo de respuesta de SUNAT',
    `intentos` INT DEFAULT 1,
    `max_intentos` INT DEFAULT 3,
    `payload_sunat` JSON NULL COMMENT 'JSON que se envió (o se enviará) a SUNAT para auditoría',
    `fecha_primer_intento` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `fecha_ultimo_intento` DATETIME NULL,
    `creado_en` DATETIME DEFAULT CURRENT_TIMESTAMP,
    `actualizado_en` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_estado` (`estado`),
    INDEX `idx_comprobante` (`comprobante_id`),
    FOREIGN KEY (`comprobante_id`) REFERENCES `comprobantes`(`id`) ON DELETE CASCADE
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci',
  'SELECT 1'
));
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
