Plan: User-Companion Memory Isolation
Goal
Implement complete memory and conversation isolation between each user-companion pair. When a user chats with Nova, then switches to Sage, each companion has completely separate memories and conversation history.
Approach: Composite User ID
Use {user_id}_{character_id} as the memory scope identifier instead of just user_id.
Files to Modify
1. web/server.py - Session Management
Changes:
Modify _session_for_user(user_id, character) to accept character parameter
Change session key from user_id to {user_id}_{character_id}
Update _resolve_session() to pass character to session creation
Update _refresh_session_character() to create new session instead of just updating character reference
Key code locations:
Lines 281-299: _session_for_user() - add character param, change session key
Lines 302-307: _refresh_session_character() - rework to get/create isolated session
Lines 310-373: _resolve_session() - load character and pass to session creation
2. src/neuro_mvp/web_session.py - Memory Client Initialization
Changes:
Modify __init__ to build composite user_id from user_id + character_id
Pass composite ID to MemoryClient
Key code locations:
Lines 63-77: __init__ - create composite user_id before MemoryClient creation
3. tools/memory_cli.py - CLI Tools Update
Changes:
Add --companion-id / -c argument to all memory commands
Update make_memory() to accept and use companion_id
Build composite user_id when companion_id is provided
Implementation Steps
Step 1: Update web/server.py Session Management

def _session_for_user(user_id: str, character: Optional[Character] = None) -> WebAgentSession:
    cfg = ensure_base_config()
    char_id = character.id if character else DEFAULT_CHARACTER_ID
    session_key = f"{user_id}_{char_id}"  # Composite key

    with _SESSIONS_LOCK:
        sess = SESSIONS.get(session_key)
        if sess is None:
            # ... create session with composite user_id for memory
            composite_user_id = f"{user_id}_{char_id}"
            sess = WebAgentSession(c2, user_id=composite_user_id, character=character)
            SESSIONS[session_key] = sess
        return sess
Step 2: Update _resolve_session() in server.py
Load user's selected character before creating session
Pass character to _session_for_user()
Step 3: Update _refresh_session_character() in server.py

def _refresh_session_character(user_id: str, character: Character) -> WebAgentSession:
    """Get or create session for user+character combination."""
    return _session_for_user(user_id, character)
Step 4: Update character selection endpoint
When user selects a new character, call _session_for_user(user_id, new_character) to get/create the isolated session
Step 5: Update CLI tools
Add --companion-id argument
Build composite user_id when provided
Memory Isolation Result
User	Companion	Memory user_id	Session Key
alice	nova	alice_nova	alice_nova
alice	sage	alice_sage	alice_sage
bob	nova	bob_nova	bob_nova
No Migration Needed
Existing memories under plain user_id will be orphaned (user's choice: "Start Fresh")
New memories will use composite IDs automatically
Testing Checklist
 User A + Nova: write memory, verify retrieval
 User A + Sage: verify cannot see Nova's memory
 Switch back to Nova: verify original memory still there
 New user B + Nova: verify cannot see User A's Nova memories
 Chat history resets when switching companions

 Implementation Complete
I've implemented the user-companion memory isolation as planned. Here's what was changed:
1. web/server.py - Session Management
_session_for_user() (lines 281-311):
Now accepts optional character parameter
Creates composite session key: {user_id}_{character_id}
Memory is scoped using the composite user_id
_refresh_session_character() (lines 314-320):
Changed to get/create an isolated session instead of just updating character reference
Returns the session for the user+character pair
_resolve_session() (line 381):
Removed the line that was overwriting session.mem.user_id, allowing proper composite key usage
2. tools/memory_cli.py - CLI Tools
make_memory() (lines 16-35):
Now accepts companion_id parameter
Builds composite user_id: {user_id}_{companion_id} when provided
All commands:
Added --companion-id / -c argument to all subparsers
Example: python -m tools.memory_cli export --user-id alice --companion-id nova
Memory Isolation Result
User	Companion	Memory user_id	Session Key
alice	nova	alice_nova	alice_nova
alice	sage	alice_sage	alice_sage
bob	nova	bob_nova	bob_nova
Key Benefits
Each user+companion pair has completely separate memories
Chat history resets when switching companions
Existing memories under plain user_id will be orphaned (fresh start)
No database migration needed