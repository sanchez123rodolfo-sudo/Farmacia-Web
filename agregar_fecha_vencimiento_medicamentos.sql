-- Migración: Agregar columna fecha_vencimiento a la tabla medicamentos
-- Ejecutar en MySQL Workbench o consola: source ruta/agregar_fecha_vencimiento_medicamentos.sql

USE farmacia_db;

-- Agregar la columna fecha_vencimiento después de 'stock'
ALTER TABLE medicamentos
    ADD COLUMN fecha_vencimiento DATE NULL AFTER stock;

-- Índice para consultas rápidas de medicamentos por vencer
CREATE INDEX idx_fecha_vencimiento ON medicamentos (fecha_vencimiento);

SELECT '✅ Columna fecha_vencimiento agregada correctamente.' AS resultado;
