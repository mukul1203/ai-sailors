const QUESTS_KEY = "storyquest.quests"; // "book:chapter" -> session id, so Play resumes a quest

export function readQuests(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(QUESTS_KEY) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

export function saveQuest(key: string, sessionId: string) {
  try {
    localStorage.setItem(QUESTS_KEY, JSON.stringify({ ...readQuests(), [key]: sessionId }));
  } catch {
    // storage unavailable: the quest just won't resume
  }
}
