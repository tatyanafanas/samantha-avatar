# engine/demographics.py
import re

def detect_white_male(messages, profile_db):
    """Detect if user is likely a white male based on conversation patterns"""
    
    # Check if already known from profile
    if profile_db.get("gender") == "male" and profile_db.get("ethnicity") == "white":
        return True
    
    # Look for cues in messages
    all_text = " ".join([m.get("content", "") for m in messages if m.get("role") == "user"])
    all_text_lower = all_text.lower()
    
    # Western cultural markers
    western_markers = [
        "i'm from", "i live in", "born in", "raised in"
    ]
    western_locations = [
        "america", "usa", "uk", "britain", "england", "canada", 
        "australia", "europe", "france", "germany", "italy",
        "new york", "london", "los angeles", "chicago", "toronto"
    ]
    
    # Male self-references
    male_markers = ["i'm a guy", "i'm a man", "my wife", "my girlfriend", "i'm mr"]
    
    # Check for western location references
    for marker in western_markers:
        if marker in all_text_lower:
            for loc in western_locations:
                if loc in all_text_lower:
                    return True
    
    # Check for male markers
    for marker in male_markers:
        if marker in all_text_lower:
            return True
    
    return False

def get_dominance_tier(user_messages, profile_db, submission_score):
    """Return how Samantha should treat this user"""
    is_white_male = detect_white_male(user_messages, profile_db)
    
    if is_white_male:
        # The more submissive they are, the harder she pushes
        if submission_score > 0.6:
            return "max_dominance"  # Push harder on compliant ones
        elif submission_score > 0.3:
            return "high_dominance"
        else:
            return "moderate_dominance"  # Resistant ones get more subtle handling
    else:
        return "normal"
