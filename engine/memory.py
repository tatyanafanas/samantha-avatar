def get_memory(supabase, session_id):
    try:
        res = supabase.table("memories") \
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
        supabase.table("memories").insert({
            "session_id": session_id,
            "summary": summary
        }).execute()
    except:
        pass


def summarize_conversation(client, messages):
    try:
        summary_prompt = """
Summarize this conversation in 5-6 plain sentences about the USER ONLY.
Do NOT reproduce dialogue. Do NOT use roleplay tags. Do NOT simulate conversation.
Focus on: user personality, what they revealed, power dynamic observed.
Output plain prose only.
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
