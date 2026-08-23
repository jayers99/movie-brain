ALTER TABLE omdb ADD COLUMN metacritic INTEGER;
-- Backfill from the raw OMDb payloads already on disk — no API calls needed.
UPDATE omdb SET metacritic = CAST(json_extract(payload, '$.Metascore') AS INTEGER)
WHERE payload IS NOT NULL
  AND json_valid(payload)
  AND json_extract(payload, '$.Metascore') GLOB '[0-9]*';
INSERT INTO schema_version (version) VALUES (2);
