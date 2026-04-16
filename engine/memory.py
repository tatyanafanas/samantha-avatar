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
You are extracting structured intelligence from a conversation for Samantha Tushabe Okullo,
a sharp, analytical woman who uses personal information to engage precisely with people.

From the conversation below, extract ONLY what has been confirmed or clearly implied.
Do not invent or speculate. If a field is unknown, write "unknown".

Output format (plain text, no JSON):

Name: [first name or handle they use]
Age: [if mentioned]
Location: [city or country]
Occupation: [what they do — be specific, not generic]
What they claim to be building or working toward: [their stated ambitions]
Soft spots or sensitive topics: [things they hedged on, over-explained, or avoided]
Boasts or things they volunteered unprompted: [what they wanted her to notice about them]
Contradictions: [anything they said that didn't match something else they said]
Tone pattern: [one phrase — e.g. "deferential and apologetic", "confident but vague", "testing her with questions"]
Notable moment: [one specific exchange worth remembering — a quote, a reveal, or a silence]

Be terse. Samantha doesn't like summaries that pad. If a field is genuinely empty, skip it entirely.
"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": str(messages[-12:])}
            ],
            temperature=0.2
        )

        return response.choices[0].message.content

    except:
        return None
