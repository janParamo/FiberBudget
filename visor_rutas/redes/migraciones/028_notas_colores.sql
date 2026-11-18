-- Notas de la mufa: color de fondo de la caja y color del texto (null: los de siempre). Formato #rrggbb.
ALTER TABLE redes.notas ADD COLUMN IF NOT EXISTS color_fondo text CHECK (color_fondo IS NULL OR color_fondo ~ '^#[0-9a-fA-F]{6}$');
ALTER TABLE redes.notas ADD COLUMN IF NOT EXISTS color_texto text CHECK (color_texto IS NULL OR color_texto ~ '^#[0-9a-fA-F]{6}$');
