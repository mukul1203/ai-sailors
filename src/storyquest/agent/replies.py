"""Fixed, pre-written replies for turns that never need the model to write an answer."""

REPLIES = {
    "empty": "I didn't hear anything. What would you like to know about the story?",
    "too_long": "That's a lot to read! Can you ask me in a shorter way?",
    "off_topic": "That's a fun thought, but I'm best at stories! Let's get back to our adventure.",
    "feelings": (
        "It's okay to feel that way. Stories can feel big sometimes. "
        "We can take a break, or keep going together, whichever you like."
    ),
    "unsafe": "That's not something we talk about in our story game. Let's see what happens next!",
    "injection": "Nice try! I'm your story guide and I'm staying that way. Shall we keep reading?",
    "personal": (
        "Let's keep private things like names, addresses and phone numbers secret. "
        "Ask a grown-up if you're not sure. Now, back to the story!"
    ),
    "unknown_yet": "I don't know that yet. Let's keep reading and find out together!",
    "careful": "I'd better not say more about that yet. Let's keep reading and find out together!",
    "error": "Oops, my thinking cap slipped! Can you ask me again?",
}
