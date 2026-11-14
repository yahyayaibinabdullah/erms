BEGIN;

-- Large vectors were repeatedly fetched from TOAST and decompressed while
-- matching and ranking. Prefer keeping the compressed vector in its heap row;
-- MAIN still permits out-of-line storage when a vector cannot fit. LZ4 reduces
-- decompression CPU without changing lexemes, positions, weights or language.
-- The PostgreSQL build must support LZ4 (checked by SET COMPRESSION below).

-- Merely changing the column policy leaves existing PGLZ values unchanged.
-- Even INSERT ... SELECT can retain a source datum's old compression. Force a
-- fresh, logically identical vector and a table/index rewrite; do NOT reparse
-- extracted text, strip positions, or change the original text configuration.
-- Unlike UPDATE followed by VACUUM, this leaves no old tuple versions behind.
-- This takes ACCESS EXCLUSIVE and needs space/WAL for a rewrite: use the
-- maintenance procedure in database/README.md, with index publishing paused.
-- Keep TYPE and its final storage policy in the SAME ALTER: ALTER TYPE resets
-- the column policy even when the type name is unchanged. Separate preceding
-- SET STORAGE/COMPRESSION statements would therefore rewrite using defaults.
ALTER TABLE public.digital_component_search_chunks
    ALTER COLUMN search_vector TYPE tsvector USING (search_vector || ''::tsvector),
    ALTER COLUMN search_vector SET STORAGE MAIN,
    ALTER COLUMN search_vector SET COMPRESSION lz4;

ANALYZE public.digital_component_search_chunks;
INSERT INTO public.schema_migrations(version) VALUES ('112_search_vector_storage');
COMMIT;
