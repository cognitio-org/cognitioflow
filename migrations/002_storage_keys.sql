-- Phase 2: files and recordings hold object-storage keys, not filesystem paths.
-- Keys look like courses/{cid}/files/{fid}/{name} and notes/{nid}/audio/{rid}.webm.
ALTER TABLE files RENAME COLUMN path TO key;
ALTER TABLE recordings RENAME COLUMN path TO key
