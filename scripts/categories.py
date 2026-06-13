"""Shared rule-based hashtag/title/channel → category mapping."""

# (keywords list, category name) — first match wins per keyword set
CATEGORY_RULES: list[tuple[list[str], str]] = [
    (["recipe", "cooking", "food", "eat", "kitchen", "baking", "chef", "meal", "dinner", "lunch", "breakfast"], "Food & Cooking"),
    (["comedy", "funny", "humor", "meme", "lol", "joke", "prank", "satirisch", "satire", "snl", "sketch"], "Comedy"),
    (["news", "politik", "nachrichten", "breaking", "bbc", "cnn", "journalism", "documentary", "history", "historical"], "News & Docs"),
    (["music", "song", "rap", "hiphop", "pop", "rnb", "r&b", "edm", "techno", "bass", "artist", "concert", "festival", "vevo", "official video", "official audio"], "Music"),
    (["fitness", "gym", "workout", "sport", "running", "yoga", "crossfit", "training", "lifting", "hoop dance", "dance tutorial"], "Fitness & Sport"),
    (["travel", "reise", "urlaub", "vacation", "explore", "adventure", "backpacking", "wanderlust"], "Travel"),
    (["tech", "coding", "programmer", "ai", "software", "developer", "gadget", "apple", "android", "google", "chatgpt", "claude", "anthropic", "llm", "openai"], "Tech"),
    (["art", "design", "drawing", "painting", "illustration", "creative", "sketch", "diy", "crafts", "sculpt", "heimwerker", "carpentry", "woodwork", "molter"], "Art & Design"),
    (["animal", "dog", "cat", "pet", "wildlife", "cute", "tiere", "haustier"], "Animals & Pets"),
    (["dance", "tanz", "choreo", "choreography", "ballet"], "Dance"),
    (["beauty", "makeup", "skincare", "fashion", "style", "ootd", "outfit", "mode"], "Beauty & Fashion"),
    (["car", "auto", "vehicle", "racing", "motorcycle", "tesla", "bmw", "mercedes"], "Cars & Vehicles"),
    (["gaming", "game", "playstation", "xbox", "nintendo", "esport", "twitch", "streamer", "survivor.io", "gamer"], "Gaming"),
    (["science", "education", "lernen", "psychology", "philosophy", "wissen", "documentary", "explainer", "how to", "anleitung", "guide", "tutorial"], "Education & Science"),
    (["business", "startup", "entrepreneur", "money", "investing", "finance", "stocks", "crypto", "geld", "shark tank"], "Business & Finance"),
    (["germany", "berlin", "deutschland", "german", "deutsch"], "Germany"),
    (["anime", "manga", "one piece", "naruto", "luffy"], "Anime"),
    (["board game", "boardgame", "caverna", "andor", "tabletop", "warhammer"], "Board Games"),
]


def derive_categories(text_tokens: list[str]) -> list[str]:
    """Map a list of text tokens (hashtags, words) to category names."""
    if not text_tokens:
        return []
    tokens_lower = [t.lower() for t in text_tokens]
    found = []
    for keywords, category in CATEGORY_RULES:
        if any(any(kw in tok for kw in keywords) for tok in tokens_lower):
            if category not in found:
                found.append(category)
    return found


def categorise_youtube_video(title: str, channel: str) -> list[str]:
    """Derive categories from a YouTube video title + channel name."""
    combined = (title or "") + " " + (channel or "")
    tokens = combined.lower().split()
    # Also pass the full combined string as one token for multi-word matches
    return derive_categories(tokens + [combined.lower()])
