def get_memory(supabase, session_id):
    try:
        res = supabase.table("samantha_memory") \
            .select("summary") \
            .eq("session_id", session_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if res.data:
            return res.data[0]["summary"]
    except:
        pass

    return "No prior memory."


def save_memory(supabase, session_id, summary):
    try:
        supabase.table("samantha_memory").insert({
            "session_id": session_id,
            "summary": summary
        }).execute()
    except:
        pass


def summarize_conversation(client, messages):
    try:
        summary_prompt = """
Summarize this conversation for Samantha's dossier on this person.
Extract and label:
- Name (if given)
- Occupation or role (if mentioned)
- Any ambitions they stated
- Any insecurities, hedges, or apologies
- Contradictions between what they said at different points
- Things they said to impress her (boasts)
- Soft spots: topics that shifted their tone

Be terse. Write it like a psychological profile, not a recap.
"""
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": str(messages[-10:])}
            ],
            temperature=0.3
        )

        return response.choices[0].message.content

    except:
        return None
