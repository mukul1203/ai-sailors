-- The wrong answers a child has already tried on the current beat (card ids, as json).
ALTER TABLE sessions ADD COLUMN wrong_cards TEXT NOT NULL DEFAULT '[]';
