-- Phase 6: course scaffolding.
-- brief: structured tutor brief; courses.tutor_prompt is compiled from it (empty brief = keep the stored prompt).
-- slug: derived from the course name, unique per owner (user_id NULL counts as one owner).

ALTER TABLE courses ADD COLUMN IF NOT EXISTS brief JSONB DEFAULT '{}';
ALTER TABLE courses ADD COLUMN IF NOT EXISTS slug TEXT;
UPDATE courses SET brief='{}' WHERE brief IS NULL;
UPDATE courses SET slug=id WHERE slug IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_owner_slug ON courses ((COALESCE(user_id, '')), slug);
