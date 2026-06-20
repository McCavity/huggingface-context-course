from mcp.server.fastmcp import FastMCP
import json

mcp = FastMCP("text-processor")

@mcp.tool()
def analyze_text(text: str) -> str:
    """Analyze text and return statistics.
    
    Args:
        text: The input text to analyze
    
    Returns:
        JSON string with analysis results
    """
    words = text.split()
    chars = len(text)
    chars_no_spaces = len(text.replace(" ", ""))
    sentences = text.count(".") + text.count("!") + text.count("?")
    
    avg_word_length = round(chars_no_spaces / len(words), 2) if words else 0
    avg_sentence_length = round(len(words) / max(sentences, 1), 2)
    
    return json.dumps({
        "total_characters": chars,
        "characters_without_spaces": chars_no_spaces,
        "total_words": len(words),
        "total_sentences": max(sentences, 1),
        "average_word_length": avg_word_length,
        "average_sentence_length": avg_sentence_length,
        "unique_words": len(set(word.lower() for word in words))
    })

@mcp.tool()
def extract_keywords(text: str, count: int = 5) -> str:
    """Extract keywords (most common words) from text.
    
    Args:
        text: The input text
        count: Number of keywords to return (default 5)
    
    Returns:
        JSON string with keywords and frequencies
    """
    # Remove common words
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "is", "are", "was", "were", "be", "been", "by", "from"
    }
    
    words = text.lower().split()
    filtered = [w.strip(".,!?;:") for w in words if w.lower() not in stopwords]
    
    from collections import Counter
    word_freq = Counter(filtered)
    top_words = word_freq.most_common(count)
    
    return json.dumps({
        "keywords": [{"word": w, "frequency": f} for w, f in top_words]
    })

@mcp.tool()
def check_reading_level(text: str) -> str:
    """Estimate reading difficulty level.
    
    Args:
        text: The input text
    
    Returns:
        JSON string with reading level estimate
    """
    sentences = max(text.count(".") + text.count("!") + text.count("?"), 1)
    words = len(text.split())
    syllables = text.count("a") + text.count("e") + text.count("i") + text.count("o") + text.count("u")
    
    if words == 0:
        return json.dumps({"error": "No text to analyze"})
    
    # Flesch Kincaid Grade
    grade = (0.39 * (words / sentences)) + (11.8 * (syllables / words)) - 15.59
    grade = max(0, round(grade, 1))
    
    if grade < 6:
        level = "Elementary School"
    elif grade < 9:
        level = "Middle School"
    elif grade < 13:
        level = "High School"
    else:
        level = "College/Academic"
    
    return json.dumps({
        "grade_level": grade,
        "reading_level": level
    })

@mcp.tool()
def reverse_text(text: str) -> str:
    """Reverse a string.
    
    Args:
        text: The input text
    
    Returns:
        The reversed text
    """
    return text[::-1]

if __name__ == "__main__":
    mcp.run()
