# MEMORY RETRIEVAL FIX GUIDE

## The Problem

Your chatbot is **writing to Supabase** (storing memories), but **not reading from it** (retrieving memories in conversation). This creates the "blank page" effect where every conversation feels like the first one.

### Root Causes Identified

1. **Supabase retrieval is wrapped in try/except that silently fails**
   - Lines in `engine/memory.py` show calls to `supabase.table()` inside broad `except Exception: pass` blocks
   - Failures are caught and swallowed — no logs, no fallback clarity

2. **Memory is retrieved but NOT injected into the system prompt**
   - `get_conversation_history()` and `get_or_create_profile()` pull data but then...
   - The data sits in `st.session_state` without forcing the LLM to see it
   - `build_dossier_prompt()` formats it nicely, but it's optional context the LLM can ignore

3. **Timing: Memory updates happen AFTER responses**
   - Line 1048-1056 in `app.py`: Memory extraction runs only every 3+ messages
   - For first 2 messages, the profile is mostly empty
   - Deep synthesis only runs every 18+ messages
   - → Early conversations have almost zero prior context

4. **No forced prompt injection** 
   - The dossier is passed to the system prompt but as a generic block
   - Nothing makes it mandatory reading or high-priority

---

## The Fix: 4-Step Implementation

### STEP 1: Verify Supabase Connection
```python
# Add to app.py, after init_connections():

def test_supabase_connection():
    """Diagnostic: is Supabase actually working?"""
    if not supabase:
        st.error("Supabase not initialized!")
        return False
    try:
        res = supabase.table("user_profiles").select("*").limit(1).execute()
        st.success(f"✅ Supabase OK — {len(res.data)} profiles found")
        return True
    except Exception as e:
        st.error(f"❌ Supabase error: {e}")
        return False
```

Add to right panel diagnostics for debugging.

---

### STEP 2: Replace Silent Exception Handling
Update `engine/memory.py` — change all `except Exception: pass` to log failures:

```python
# OLD (line 105-119):
if supabase:
    try:
        res = supabase.table("user_profiles") \
            .select("*") \
            .eq("name", name) \
            .limit(1) \
            .execute()
        if res.data:
            profile = res.data[0]
            ...
    except Exception:  # ← SILENT FAIL
        pass

# NEW:
if supabase:
    try:
        res = supabase.table("user_profiles") \
            .select("*") \
            .eq("name", name) \
            .limit(1) \
            .execute()
        if res.data:
            profile = res.data[0]
            ...
        else:
            print(f"[memory] No profile found for '{name}' in Supabase")
    except Exception as e:
        print(f"[memory] Supabase fetch error for '{name}': {e}")
```

This helps you see WHERE retrieval is failing.

---

### STEP 3: Inject Memory Aggressively into Every Prompt
Update `app.py` line 929-933:

```python
# OLD:
dossier = build_dossier_prompt(
    st.session_state.user_profile_db,
    st.session_state.user_history_db,
    conversation_length=len(st.session_state.messages),
)

# NEW:
from engine.memory_injection import build_memory_context, inject_memory_into_system_prompt

dossier = build_dossier_prompt(
    st.session_state.user_profile_db,
    st.session_state.user_history_db,
    conversation_length=len(st.session_state.messages),
)

# Force memory into the system prompt
memory_context = build_memory_context(
    st.session_state.user_profile_db,
    st.session_state.user_history_db,
    len(st.session_state.messages)
)
```

Then update the system prompt construction (line 987-995):

```python
# OLD:
system_prompt = dynamic_prompt + f"""
---
CURRENT STYLE: {current_style}
...
"""

# NEW:
system_prompt = dynamic_prompt + f"""
---
CURRENT STYLE: {current_style}
STYLE DESCRIPTION: {style_data['description']}
STYLE RULES:
{chr(10).join(f"- {r}" for r in style_data['rules'])}

CURRENT OBJECTIVE: {st.session_state.profile['goal']}
"""

# ← Inject memory BEFORE constraints
system_prompt = inject_memory_into_system_prompt(
    system_prompt,
    memory_context,
    position="early"
)
```

---

### STEP 4: Extract Memory MORE Frequently (Not Less)
Change line 1048-1052 from:

```python
should_update_memory = (
    msg_count % 3 == 0
    or st.session_state.profile["irritation"] > 0.7
)
```

To:

```python
should_update_memory = (
    msg_count % 2 == 0  # ← Run every 2 messages instead of 3
    or st.session_state.profile["irritation"] > 0.7
    or msg_count <= 4  # ← Always extract early conversation
)
```

And change deep synthesis frequency (line 1055):

```python
# OLD:
if (msg_count - st.session_state.last_deep_synthesis_at) >= 18:

# NEW:
if (msg_count - st.session_state.last_deep_synthesis_at) >= 12:
    _run_deep_synthesis()
```

---

## STEP 5: Test Memory Injection

Add a debug panel in the right sidebar:

```python
# In right panel (around line 1155):

with st.expander("🧠 Memory Debug", expanded=False):
    if st.session_state.user_profile_db:
        st.write("**Profile loaded from Supabase:**")
        st.json(st.session_state.user_profile_db)
        
        st.write("**Conversation history:**")
        st.text(st.session_state.user_history_db[:500])
        
        memory_ctx = build_memory_context(
            st.session_state.user_profile_db,
            st.session_state.user_history_db,
            len(st.session_state.messages)
        )
        st.write("**Memory context being injected:**")
        st.text(memory_ctx["memory_block"])
    else:
        st.caption("No profile loaded yet.")
```

This lets you see exactly what memory is being sent to the LLM.

---

## STEP 6: Handle Supabase Failures Gracefully

Update `get_or_create_profile()` to be more resilient:

```python
def get_or_create_profile(supabase, name: str) -> dict:
    """Load existing profile or create a fresh one."""
    profile = None
    
    # Try Supabase first
    if supabase:
        try:
            res = supabase.table("user_profiles") \
                .select("*") \
                .eq("name", name) \
                .limit(1) \
                .execute()
            if res.data:
                profile = res.data[0]
                new_count = (profile.get("session_count") or 0) + 1
                # Update session count
                try:
                    supabase.table("user_profiles") \
                        .update({"session_count": new_count, "updated_at": datetime.now(timezone.utc).isoformat()}) \
                        .eq("name", name) \
                        .execute()
                except Exception as e:
                    print(f"[memory] Could not update session count: {e}")
                profile["session_count"] = new_count
                print(f"[memory] ✅ Loaded profile for '{name}' from Supabase (session #{new_count})")
                return profile
        except Exception as e:
            print(f"[memory] ⚠️  Supabase fetch failed: {e} — falling back to local storage")
    
    # Fallback to local JSON
    _ensure_local_dirs()
    path = _profile_path(name)
    existing = _read_json_file(path) or {}
    
    if existing:
        new_count = (existing.get("session_count") or 0) + 1
        existing["session_count"] = new_count
        _write_json_file(path, existing)
        print(f"[memory] 📁 Loaded profile for '{name}' from local storage (session #{new_count})")
        return existing
    
    # Create fresh profile
    new_profile = {
        "name": name,
        "relationship_status": "stranger",
        "session_count": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_file(path, new_profile)
    print(f"[memory] ✨ Created new profile for '{name}'")
    return new_profile
```

---

## Deployment Checklist

- [ ] Add `engine/memory_injection.py` (done above)
- [ ] Update `app.py` lines 929-1003 (memory injection)
- [ ] Change extraction frequency (every 2 messages, not 3)
- [ ] Add debug panel to right sidebar
- [ ] Update `engine/memory.py` exception handling (remove silent `pass`)
- [ ] Test: Send 2 messages, check memory debug panel
- [ ] Test: Return user — check that prior memories appear
- [ ] Check Streamlit logs for `[memory]` debug messages

---

## Expected Outcome

After applying these changes:

1. **New user first message** → Profile created, stored in Supabase
2. **Second message** → Memory extraction runs, fills profile
3. **Same user returns next day** → Profile loads from Supabase
4. **LLM sees memory forced in system prompt** → References prior context naturally
5. **Right panel shows what's being injected** → Visibility into memory flow

The chatbot should now remember you, reference prior conversations, and build on previous findings — without announcing it.

---

## If It Still Doesn't Work

Check in this order:

1. **Supabase credentials** — Are `SUPABASE_URL` and `SUPABASE_KEY` valid?
   - Test with the debug button in right panel

2. **Database tables exist** — Do these tables exist in Supabase?
   - `user_profiles`
   - `conversation_logs`
   - `transcripts`

3. **Logs** — Check Streamlit terminal for `[memory]` log messages
   - They show exactly where retrieval fails

4. **Local fallback** — Is `data/profiles/` being created?
   - If Supabase fails, the system should use local JSON

5. **Profile contents** — Run debug panel, check if data is actually stored
   - Look for `insecurities`, `soft_spots`, `deep_profile` etc.

---

## Advanced: Semantic Search for Better Retrieval

If you want to go further, add semantic search to find RELEVANT prior memories:

```python
# In engine/memory.py

def search_relevant_memories(supabase, name: str, current_message: str, limit: int = 3) -> list:
    """
    Find prior memories most relevant to the current message.
    This requires adding vector embeddings to Supabase.
    """
    # Embed current_message
    # Search transcripts by similarity
    # Return top N matches
    pass
```

This would let the LLM pull the exact relevant detail from 20 prior conversations instead of just the last 3 summaries.

---
