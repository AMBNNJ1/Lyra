## Implementing Autonomy in a Local AI Agent

This document specifies the architecture and implementation plan to add robust autonomy to the local agent in this repository, based on the report “Implementing Autonomy in a Local AI Agent.” It maps concepts directly to the existing codebase (`src/neuro_mvp/*`, `tools/*`, `config.yaml`) and provides concrete steps to implement and integrate planning, memory-augmented reasoning, tool use, scheduling, and self-monitoring.

### 1) Architecture Overview

An autonomous agent runs a closed loop of perceive → plan → act → observe → learn, composed of:

- **LLM/VLM Core (Agent Brain)**
  - Runs locally (via `openai_compat.py` to LM Studio or `qwen.py`/transformers).
  - Role/prompt defines persona, goals, tools, and loop format.
  - VLM optional for image inputs (configured under `models.vlm` in `config.yaml`).

- **Memory System**
  - Working memory: rolling context window and step logs.
  - Short‑term memory: session/task state kept in Python structures.
  - Long‑term memory: Qdrant 

- **Goal and Planning Module**
  - Interprets long‑term goals (from config/persona) into medium‑term objectives and short‑term tasks.
  - Uses LLM prompts (planner role) to decompose tasks (CoT/ToT) with memory retrieval.

- **Tools and Actions**
  - Web search (`web_search_tool.py`), memory read/write (`memory.py`), TTS (`tts_kokoro.py`), VTS avatar control (`vts.py`), optional Python REPL, file I/O.
  - Tool catalog is exposed to the LLM via descriptions and a simple function-calling schema.

- **Execution Controller (Agent Loop)**
  - Orchestrates plan-act-observe-refine iterations.
  - Parses LLM outputs for actions, dispatches tools, captures observations, updates memory, and feeds back.

- **Critic/Evaluator (Self‑Monitoring)**
  - Secondary LLM pass or mode that scores outcomes vs. goals; proposes adjustments, retries, or termination.

### 2) Goals: Hierarchy and Management

Long‑term goals (encoded in persona/config):
- Learn about the user (#1)
- Learn about the world (#2)
- Entertain the user (#3)

Mechanics:
- Encode long‑term goals in `config.yaml` persona and store tagged anchor memories (e.g., `type=goal,long_term=true`).
- Maintain a runtime structure: `medium_term_goals: List[Goal]`, `task_queue: Deque[Task]`.
- At loop boundaries, derive/refresh medium‑term goals from context + memory, and generate/refresh short‑term tasks from planner prompts.
- Tag each medium‑term goal with which long‑term goal(s) it serves; prefer balanced rotation.

### 3) Memory‑Augmented Reasoning

- Retrieval before planning/answering: query Qdrant via `memory.py` (provider from `config.yaml`) for relevant user facts, prior tasks, and world knowledge.
- Working memory prompt sections: conversation summary, recent actions/observations, active goals, retrieved memories.
- Memory writing policy: after meaningful steps, embed summaries and store with metadata (topic, date, goal tags, quality score).
- Short‑term memory: session map (e.g., last N actions, transient variables) to avoid context bloat.
- Hybrid querying: merge short‑term session entries with long‑term results.

### 4) Execution Model

Plan‑Act‑Observe‑Refine loop with guardrails:
1. Select active goal/task (or spawn from planner).
2. Retrieve context/memories, build prompt.
3. Run LLM; if action suggested → dispatch tool → capture observation.
4. Update working/long‑term memory as needed.
5. Critic pass evaluates progress; adjust plan or proceed.
6. Check termination criteria (max iterations, success criteria, user interruption).

Pseudocode (controller skeleton):

```python
def agent_loop(controller: Controller, max_iters: int = 12):
    for _ in range(max_iters):
        goal = controller.select_goal()
        tasks = controller.ensure_tasks(goal)
        task = controller.next_task(tasks)

        retrieved = controller.retrieve_memories(goal, task)
        prompt = controller.build_prompt(goal, task, retrieved)

        llm_output = controller.run_llm(prompt)
        action = controller.parse_action(llm_output)

        if action:
            observation = controller.dispatch(action)
        else:
            observation = controller.observe_thought(llm_output)

        controller.update_working_memory(task, observation)
        controller.maybe_store_long_term(task, observation)

        critique = controller.criticize(goal, task, observation)
        controller.adjust_plan(tasks, critique)

        if controller.should_terminate(goal, tasks, critique):
            break
```

### 5) Tool Invocation Schema

Adopt a lightweight, model‑agnostic schema (compatible with ReAct and JSON function‑calling):

```json
{
  "thought": "I should search for latest AI art news.",
  "action": { "name": "search", "args": { "query": "latest ai art developments" } }
}
```

Controller behavior:
- If `action` present, call mapped Python function and append `observation` to working memory.
- If absent, treat as internal reasoning and continue.

Tool catalog (initial):
- search(query: str) → List[Result] — `web_search_tool.py`
- browse(url: str) → str — simple HTTP fetch + sanitizer
- retrieve_memory(query: str, top_k: int=8) → List[Memory] — via `memory.py`
- store_memory(text: str, metadata: dict) → id — via `memory.py`
- tts_say(text: str) → Path — via `tts_kokoro.py`
- vts_trigger(hotkey: str) — via `vts.py`
- py_eval(code: str, inputs: dict) → dict — safe, sandboxed Python

### 6) Mapping to Current Repository

- `src/neuro_mvp/openai_compat.py`: wraps local OpenAI‑compatible LLMs (LM Studio). Extend with a helper to run system/instruction prompts for planner/critic roles.
- `src/neuro_mvp/qwen.py`: optional local VLM path. Keep disabled by default unless vision needed.
- `src/neuro_mvp/memory.py`: central memory interface. Ensure it exposes `search_memories`, `add_memory`, and tagging.
- `src/neuro_mvp/memory_qdrant.py` and `memory_local.py`: storage backends. Confirm embeddings and metadata fields (topic, goal_tags, quality, kind=user/world/tool_result).
- `src/neuro_mvp/web_search_tool.py`: web search; ensure it returns structured {title, url, snippet}.
- `src/neuro_mvp/tts_kokoro.py`: text‑to‑speech for entertainment/feedback.
- `src/neuro_mvp/vts.py`: avatar control; can reflect sentiment/arousal from `sentiment.py`.
- `config.yaml`: set `conversation.window_messages`, `memory.*`, `models.*`; encode long‑term goals in persona.

Add new module:
- `src/neuro_mvp/agent_loop.py`: controller, planner, critic, tool registry, schemas.

### 7) Implementation Steps

1) Controller and Schemas
- Create `src/neuro_mvp/agent_loop.py` with:
  - `Tool` protocol, `ToolRegistry` (name → callable, description, args schema, safety limits).
  - `Goal`, `Task`, `Observation` dataclasses with metadata (ids, tags, served_long_term_goals).
  - `Controller` class implementing the loop and lifecycle methods shown above.

2) Prompt Templates
- Add planner and critic templates in `src/neuro_mvp/agent_loop.py` or `src/neuro_mvp/prompts.py`:
  - Planner: given long/medium‑term goals, recent context, and retrieved memories, output tasks JSON.
  - Critic: assess observation vs. success criteria; suggest next action or revision.

3) Memory Integration
- Update `memory.py` to ensure:
  - `add_memory(text: str, metadata: dict)` stores embeddings and metadata.
  - `search_memories(query: str, top_k: int)` returns text + metadata.
  - Add `importance` and `kind` fields and a simple heuristic `should_remember(text) -> bool`.

4) Tool Implementations
- Ensure `web_search_tool.py` exposes `search(query)` and optionally `browse(url)`.
- Add a lightweight `py_eval` (restricted globals, timeout) for calculations.
- Wrap memory ops as tools: `retrieve_memory`, `store_memory` (thin adapters around `memory.py`).

5) Action Parsing
- Support both ReAct and JSON function‑calling:
  - If JSON with `action` present → dispatch.
  - Else regex parse `Action:`/`Action Input:` blocks.
  - Always capture a `thought` field for traceability.

6) Success Criteria and Termination
- Define per‑task criteria (e.g., summary < N tokens, search results >= M relevant items).
- Global guards: max tool calls per loop, max iterations per goal, backoff on repeated failures.

7) Scheduling
- Add a simple scheduler in `run_agent.py` or a new `scripts/run_agent_continuous.ps1` is already present; integrate `agent_loop` to run:
  - On new user input events.
  - Periodic background cycles (idle windows) with time‑based triggers for world‑learning.

8) Persona and Goals in Config
- In `config.yaml`, keep long‑term goals in persona text and optionally add a structured `goals:` block:
  - `goals.long_term: [learn_user, learn_world, entertain_user]`
  - `goals.rotation: balanced`

9) Logging and Traces
- Log each cycle: goal id, task, tool, observation length, memory writes, critic score.
- Optionally add a small dashboard (`tools/memory_dashboard.py` exists) to browse goal/task history.

10) Safety and Offline Preference
- Respect `models.device` and `memory.tool_target` in `config.yaml`.
- Rate limit external web access; prefer local sources.

### 8) Minimal Controller API Sketch

```python
class Controller:
    def select_goal(self) -> Goal: ...
    def ensure_tasks(self, goal: Goal) -> list[Task]: ...
    def next_task(self, tasks: list[Task]) -> Task: ...
    def retrieve_memories(self, goal: Goal, task: Task) -> list[Memory]: ...
    def build_prompt(self, goal: Goal, task: Task, memories) -> str: ...
    def run_llm(self, prompt: str) -> str | dict: ...
    def parse_action(self, llm_output) -> Action | None: ...
    def dispatch(self, action: Action) -> Observation: ...
    def observe_thought(self, llm_output) -> Observation: ...
    def update_working_memory(self, task: Task, obs: Observation) -> None: ...
    def maybe_store_long_term(self, task: Task, obs: Observation) -> None: ...
    def criticize(self, goal: Goal, task: Task, obs: Observation) -> Critique: ...
    def adjust_plan(self, tasks: list[Task], critique: Critique) -> None: ...
    def should_terminate(self, goal: Goal, tasks: list[Task], critique: Critique) -> bool: ...
```

### 9) Example Loop Scenarios

- Learning and sharing world knowledge: Search → Browse → Summarize → Store → Present via TTS/VTS.
- User profiling: Ask → Parse → Store user preference memory → Tailor next tasks.
- Complex planning: Multi‑tool iterations with critic‑guided refinements and validity checks.

### 10) Bring‑Up Checklist

- [ ] Create `src/neuro_mvp/agent_loop.py` and wire into `run_agent.py`.
- [ ] Expose tool registry with `search`, `browse`, `retrieve_memory`, `store_memory`, `tts_say`, `vts_trigger`, `py_eval`.
- [ ] Add planner/critic prompt templates.
- [ ] Implement action parser (JSON + ReAct).
- [ ] Verify `memory.py` provides required methods and metadata.
- [ ] Add success criteria and termination guardrails.
- [ ] Add logging of cycles and memory writes.
- [ ] Test Example 1–3 end‑to‑end with dry‑run mode (no external calls).
- [ ] Enable background scheduling using existing PowerShell scripts.

This plan aligns with the current repository and can be implemented incrementally. Start with the controller, tool registry, and memory wiring; then layer planner/critic prompts and scheduling. Once stable, iterate on quality checks and UI/telemetry.


### Idle Auto-Continue

- Enable natural, goal-aligned behavior during pauses in chat.
- When `conversation.idle_auto_continue` is true (default), the agent will wait `conversation.idle_timeout_sec` (default 10s) for input; if none arrives, it self-continues with a brief, proactive message that reflects on goals and proposes the next small step.
- In fully non-blocking mode (`conversation.require_input: false`), the same behavior uses `conversation.autodrive_input_timeout_sec` (default 10s).
- These toggles are wired into `run_agent.py` continuous mode so the agent “feels alive” without spamming.



