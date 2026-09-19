-- Files carried only their upload filename, so the Files screen read "Schutze slides 4.txt" and the
-- tutor's authority order (WG > lecture > slides > textbook) had nothing in the row to stand on.
-- label: what the file is called on screen. Empty means "use the filename".
-- role:  what kind of course material it is — wg, lecture, slides, reader, cases, assignment, admin, note.
ALTER TABLE files ADD COLUMN IF NOT EXISTS label TEXT DEFAULT '';
ALTER TABLE files ADD COLUMN IF NOT EXISTS role  TEXT DEFAULT '';
