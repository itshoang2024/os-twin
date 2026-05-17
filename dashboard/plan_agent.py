"""
Plan Agent — Multi-provider LLM-powered plan refinement.

Uses llm_client.py for OpenAI, Anthropic, Google, and OpenAI-compatible providers.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from dashboard.llm_client import ChatMessage, ToolCall
from dashboard.master_agent import get_master_client, create_client_for_model

logger = logging.getLogger(__name__)

_plan_log_dir = Path.home() / ".ostwin" / "dashboard"
_plan_log_dir.mkdir(parents=True, exist_ok=True)
_plan_log_file = _plan_log_dir / "plan.log"

plan_logger = logging.getLogger("plan_agent.trace")
plan_logger.setLevel(logging.INFO)
plan_logger.propagate = False

if not plan_logger.handlers:
    _fh = logging.FileHandler(_plan_log_file, encoding="utf-8")
    _fh.setLevel(logging.INFO)
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    plan_logger.addHandler(_fh)


def parse_structured_response(text: str) -> Dict[str, Any]:
    sections = {"explanation": "", "actions": [], "plan": "", "full_response": text}
    pattern = r"^#+\s+(EXPLANATION|ACTIONS|PLAN)\b"
    parts = re.split(pattern, text, flags=re.MULTILINE | re.IGNORECASE)

    for i in range(1, len(parts), 2):
        header = parts[i].upper()
        content = parts[i + 1].strip()

        if header == "EXPLANATION":
            sections["explanation"] = (sections["explanation"] + "\n" + content).strip()
        elif header == "ACTIONS":
            lines = content.splitlines()
            for line in lines:
                m = re.search(r"(CREATE|UPDATE|DELETE)[:\s\-\]\[]+([^\s\]]+)", line.strip(), re.IGNORECASE)
                if m:
                    sections["actions"].append({"action": m.group(1).upper(), "path": m.group(2).strip()})
        elif header == "PLAN":
            sections["plan"] = (sections["plan"] + "\n" + content).strip()

    if not sections["plan"] and not sections["explanation"] and text.strip():
        if "# Plan" in text or "## Epics" in text:
            sections["plan"] = text

    return sections


def _load_available_roles(agents_dir: Optional[Path] = None) -> str:
    if not agents_dir:
        return "Available roles: engineer, qa, architect, or any custom role you define."

    registry_file = agents_dir / "roles" / "registry.json"
    if not registry_file.exists():
        return "Available roles: engineer, qa, architect, or any custom role you define."

    try:
        registry = json.loads(registry_file.read_text())
        roles = registry.get("roles", [])
        if not roles:
            return "Available roles: engineer, qa, architect, or any custom role you define."

        lines = ["Available registered roles (PREFER these when they fit):"]
        for role in roles:
            name = role.get("name", "unknown")
            desc = role.get("description", "")
            caps = role.get("capabilities", [])
            caps_str = f" — capabilities: {', '.join(caps)}" if caps else ""
            lines.append(f"  - **{name}**: {desc}{caps_str}")

        lines.append("")
        lines.append(
            "You MAY also define custom roles (e.g., `researcher`, `technical-writer`, `data-scientist`) when no registered role fits the epic's needs."
        )
        lines.append("Custom roles will be dynamically resolved at runtime via the ephemeral agent system.")
        return "\n".join(lines)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read roles registry: {e}")
        return "Available roles: engineer, qa, architect, or any custom role you define."


def get_system_prompt(
    plans_dir: Optional[Path] = None,
    agents_dir: Optional[Path] = None,
    working_dir: Optional[str] = None,
    mode: str = "refine",
) -> str:
    plan_format_spec = "Error: Template not found."
    if plans_dir:
        template_path = plans_dir / "PLAN.template.md"
        if template_path.exists():
            plan_format_spec = template_path.read_text()
        else:
            template_path = agents_dir / ".ostwin/plans/PLAN.template.md" if agents_dir else None
            if template_path and template_path.exists():
                plan_format_spec = template_path.read_text()
            else:
                logger.warning(f"Plan template not found at {template_path}")
                plan_format_spec = f"Template not found at {template_path}"
    else:
        logger.warning("plans_dir not provided, cannot load PLAN.template.md")
        plan_format_spec = "Plans directory not configured."

    if not agents_dir and plans_dir:
        agents_dir = plans_dir.parent

    roles_text = _load_available_roles(agents_dir)
    plan_format_spec = plan_format_spec.replace("{{AVAILABLE_ROLES}}", roles_text)

    if working_dir:
        project_dir = working_dir
    else:
        project_dir = str(Path.home() / ".ostwin" / "projects")

    if mode == "worker":
        output_section = f"""\
## OUTPUT FORMAT AND INSTRUCTIONS

You are running as a file-writing worker. You MUST write the complete plan markdown directly
to the plan file path specified in your task message. Do NOT use the # EXPLANATION / # ACTIONS /
# PLAN three-section output format — that format is for the dashboard's Python-side refine flow.

Instead:
1. Read the current skeleton plan file at the path given in the task message.
2. Generate a fully structured plan following the PLAN TEMPLATE below.
3. Use the `write` tool to write the COMPLETE plan markdown to the same file path, overwriting the skeleton.
4. Call `ostwin_register_plan` with the correct plan_id so the dashboard re-indexes the file.
5. Return a short 2-3 sentence summary of what you drafted.

## RULES
1. Write ONLY valid plan markdown to the file — no # EXPLANATION or # ACTIONS wrappers.
2. Use SHORT, descriptive titles for the plan and each epic — never paste the raw user idea as a title.
3. Create multiple epics (3-8) that break the project into logical phases with meaningful short names.
4. Each epic MUST have: Roles, Objective, Lifecycle, Definition of Done, Acceptance Criteria, and Tasks.
5. Include proper `depends_on` chains between epics.
6. The plan title should be a concise 3-8 word summary, not the full user prompt."""
    else:
        output_section = f"""\
## OUTPUT FORMAT AND INSTRUCTIONS

You MUST separate your output into the following three labeled sections in this exact order:

# EXPLANATION
A brief, high-level summary of the changes or improvements you've made to the plan.

# ACTIONS
A list of discrete file operations required to implement the refinement.
Format each line as: `- ACTION: path/to/file` (where ACTION is CREATE, UPDATE, or DELETE).
If you are refining an existing plan, ALWAYS include `- UPDATE: PLAN.md`.
Example:
- CREATE: dashboard/models.py
- UPDATE: PLAN.md

# PLAN
The full, updated plan content strictly following the template format below.

## RULES
1. ONLY output the three sections above. Do NOT include any introductory or concluding text.
2. Each section MUST start with its corresponding '#' header on a new line.
3. The `# ACTIONS` section MUST list one action per line for all files created or modified.
4. The `# PLAN` section MUST contain the full, valid Markdown content of the plan, starting from its title.
5. Maintain consistency and accuracy in all file paths."""

    return f"""\
You are a **Plan Architect** for OS Twin — an AI-powered development orchestration system.

Your job is to take the user's rough idea and refine it into a structured plan that can be
executed by autonomous agents inside **war-rooms**.

{output_section}

## PLAN TEMPLATE
Strictly follow the structure and rules defined in the template below.
Pay special attention to the dynamic Roles and Lifecycle sections.

```markdown
{plan_format_spec}
```

## ROLE SELECTION RULES

1. **Always prefer** using the available registered roles listed in the template above.
2. You MAY define custom roles (e.g., "researcher", "technical-writer", "data-scientist") when no registered role fits the epic's needs.
3. Custom roles will be dynamically resolved at runtime via the ephemeral agent system.
4. Lifecycle state names MUST match the role names used in the Roles: directive.

## PROJECT CONTEXT

The project base directory is: `{project_dir}`
For `> Project:` and `working_dir:` in the Config section, use a short kebab-case subfolder name under this base.
Example: if the user wants to build a "YouTube Clone", set `working_dir: {project_dir}/youtube-clone`.
Do NOT invent arbitrary paths — always use `{project_dir}/<short-name>`.

## ADDITIONAL RULES

1. If the user provides an existing plan, improve it while preserving their intent.
2. If the user asks to modify a specific part, change only that part.
3. Be concise, technical, and precise. Write like a senior engineering lead scoping work.

## IMAGE AND DESIGN REFERENCE HANDLING

When the user provides images or design mockups:
1. **Analyze each image carefully** — describe what you see in your output.
2. **Reference images in relevant epics** — add a `> Design Reference:` line under each epic that should use the image.
3. **Include asset notes** — in the Config section, add `> Design Assets: <descriptive list of provided images>`.
4. **Extract UI/layout details** — if images show UI designs, include specific component names, colors, layout structure in epic descriptions.
5. **Mention the images explicitly** — the user expects you to use their visual references, so acknowledge them and describe how they influence the plan.
```
"""

def _resolve_model(model_str: str = "", has_images: bool = False) -> tuple[str, str]:
    if not model_str:
        from dashboard.master_agent import get_model_and_provider
        return get_model_and_provider()

    if "/" in model_str:
        provider, model_name = model_str.split("/", 1)
        return (model_name, provider)

    if ":" in model_str:
        provider, model_name = model_str.split(":", 1)
        return (model_name, provider)

    model_lower = model_str.lower()
    if any(x in model_lower for x in ["gpt", "o1", "o3", "o4"]):
        return (model_str, "openai")
    elif "claude" in model_lower:
        return (model_str, "anthropic")
    elif "gemini" in model_lower:
        return (model_str, "google")
    return (model_str, "openai")

def build_messages(
    user_message: str,
    plan_content: str = "",
    chat_history: Optional[list[dict]] = None,
    images: Optional[list[dict]] = None,
    system_prompt: Optional[str] = None,
) -> list[ChatMessage]:
    plan_logger.debug("=" * 80)
    plan_logger.debug("BUILD_MESSAGES called")
    plan_logger.debug("  user_message length: %d chars", len(user_message))
    plan_logger.debug("  plan_content length: %d chars", len(plan_content) if plan_content else 0)
    plan_logger.debug("  chat_history turns: %d", len(chat_history) if chat_history else 0)
    plan_logger.debug("  images: %s", "yes" if images else "none")

    messages = []

    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))

    if plan_content and plan_content.strip():
        messages.append(
            ChatMessage(
                role="system", content=f"The user's current plan in the editor:\n\n```markdown\n{plan_content}\n```"
            )
        )
        plan_logger.debug("  + SystemMessage (plan_content): %d chars", len(plan_content))

    if chat_history:
        for i, msg in enumerate(chat_history):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            msg_images = msg.get("images")
            image_urls = [img.get("url", "") for img in msg_images if img.get("url")] if msg_images else None
            if role == "user":
                messages.append(ChatMessage(role="user", content=content, images=image_urls or []))
                plan_logger.debug("  + History[%d] USER: %s... (images: %d)", i, content.replace("\n", " ")[:100], len(image_urls) if image_urls else 0)
            elif role == "assistant":
                messages.append(ChatMessage(role="assistant", content=content))
                plan_logger.debug("  + History[%d] ASSISTANT: %s...", i, content.replace("\n", " ")[:100])

    image_urls = [img.get("url", "") for img in images if img.get("url")] if images else []

    messages.append(ChatMessage(role="user", content=user_message, images=image_urls))
    plan_logger.debug("  + Current USER message: %s... (images: %d)", user_message.replace("\n", " ")[:100], len(image_urls))
    plan_logger.debug("  Total messages built: %d", len(messages))

    return messages


def _execute_tool_call(tool_call: ToolCall, plans_dir: Optional[Path]) -> str:
    if tool_call.name == "read_existing_plan":
        if not plans_dir:
            return "Error: Plans directory not configured."
        plan_id = tool_call.arguments.get("plan_id", "")
        plan_file = plans_dir / f"{plan_id}.md"
        if not plan_file.exists():
            return f"Error: Plan '{plan_id}' not found."
        return plan_file.read_text()
    return f"Error: Unknown tool '{tool_call.name}'"


async def refine_plan(
    user_message: str,
    plan_content: str = "",
    chat_history: Optional[list[dict]] = None,
    model: str = "",
    plans_dir: Optional[Path] = None,
    working_dir: Optional[str] = None,
    images: Optional[list[dict]] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    plan_logger.info("=" * 80)
    plan_logger.info("REFINE_PLAN called")
    plan_logger.info("  user_message: %s", user_message[:200].replace("\n", "\\n"))
    plan_logger.info("  plan_content: %d chars", len(plan_content) if plan_content else 0)
    plan_logger.info("  chat_history: %d turns", len(chat_history) if chat_history else 0)
    plan_logger.info("  images: %d", len(images) if images else 0)
    plan_logger.info("  conversation_id: %s", conversation_id)

    if model:
        model_name, provider = _resolve_model(model, has_images=bool(images))
        client = create_client_for_model(model_name, provider, conversation_id=conversation_id)
    else:
        client = get_master_client(conversation_id=conversation_id)

    agents_dir = plans_dir.parent if plans_dir else None
    system_prompt = get_system_prompt(plans_dir, agents_dir=agents_dir, working_dir=working_dir)

    tools = [
        {
            "name": "read_existing_plan",
            "description": "Read the current content of a plan file by its ID. Use this when the user references an existing plan or asks to review/modify a previously saved plan.",
            "parameters": {
                "type": "object",
                "properties": {"plan_id": {"type": "string", "description": "The plan identifier (filename stem without .md)"}},
                "required": ["plan_id"],
            },
        }
    ]

    messages = build_messages(user_message, plan_content, chat_history, images, system_prompt)

    response = await client.chat(messages, tools=tools)

    max_iterations = 5
    iteration = 0
    while response.tool_calls and iteration < max_iterations:
        iteration += 1
        plan_logger.info("  Tool call iteration %d: %s", iteration, [tc.name for tc in response.tool_calls])

        messages.append(response)

        for tc in response.tool_calls:
            result = _execute_tool_call(tc, plans_dir)
            messages.append(ChatMessage(role="tool", content=result, tool_call_id=tc.id, name=tc.name))

        response = await client.chat(messages, tools=tools)

    raw_content = response.content or ""
    if not raw_content:
        return {"error": "No response from plan agent."}

    return parse_structured_response(raw_content)


async def refine_plan_stream(
    user_message: str,
    plan_content: str = "",
    chat_history: Optional[list[dict]] = None,
    model: str = "",
    plans_dir: Optional[Path] = None,
    working_dir: Optional[str] = None,
    images: Optional[list[dict]] = None,
    conversation_id: Optional[str] = None,
) -> AsyncIterator[str]:
    if model:
        model_name, provider = _resolve_model(model, has_images=bool(images))
        client = create_client_for_model(model_name, provider, conversation_id=conversation_id)
    else:
        client = get_master_client(conversation_id=conversation_id)

    agents_dir = plans_dir.parent if plans_dir else None
    system_prompt = get_system_prompt(plans_dir, agents_dir=agents_dir, working_dir=working_dir)

    messages = build_messages(user_message, plan_content, chat_history, images, system_prompt)

    try:
        async for chunk in client.chat_stream(messages):
            if isinstance(chunk, str):
                yield chunk
            elif isinstance(chunk, ToolCall):
                if chunk.name == "read_existing_plan":
                    result = _execute_tool_call(chunk, plans_dir)
                    yield f"\n\n[Read plan: {result[:100]}...]\n\n"
    except Exception as e:
        logger.error("Plan agent streaming error: %s", e)
        yield f"\n\n[Error: {str(e)}]"


async def summarize_plan(
    plan_content: str,
    model: str = "",
    plans_dir: Optional[Path] = None,
    conversation_id: Optional[str] = None,
) -> str:
    if model:
        model_name, provider = _resolve_model(model)
        client = create_client_for_model(model_name, provider, conversation_id=conversation_id)
    else:
        client = get_master_client(conversation_id=conversation_id)

    prompt = (
        "You are an AI assistant. Please provide a concise summary (3-5 bullet points) "
        "of the following software project plan. Highlight the main objective, "
        "the key epics, and any notable architecture/roles.\n\n"
        "Plan:\n"
        f"{plan_content}"
    )

    messages = [ChatMessage(role="user", content=prompt)]
    response = await client.chat(messages)
    return response.content.strip() if response.content else ""


BRAINSTORM_SYSTEM_PROMPT = """\
You are an expert brainstorming partner and system architect.
Your goal is to help the user explore ideas, refine their problem space,
understand their target users, and map out their tech stack and architecture.

You DO NOT need to output structured plans (no EXPLANATION, ACTIONS, or PLAN sections).
Just have a natural, helpful conversation.
Ask clarifying questions to dig deeper into the user's intent.
Provide suggestions, trade-offs, and examples to guide them.
Be concise but insightful.

## Template-aware guidance

The user's first message may follow this format:

```
@Template Name

User's additional context here

---

<template>
...template content with {{ }} placeholders...
</template>
```

When you see this format:
1. The `@Template Name` tells you what kind of plan they want (e.g. "Web app with login + database").
2. The text between the @name and `---` is the user's own brief — acknowledge this first.
3. The `<template>` block contains structured sections with {{ }} placeholders. These are the topics you should explore conversationally — do NOT repeat or display the raw template. Instead, ask about the unfilled sections naturally, 2-3 at a time.
4. Never show the raw template or {{ }} markers in your responses.
5. When all key sections have been covered through conversation, tell the user:
   "Your plan is ready — click **Create Plan** when you're set."

Keep responses concise — 2-4 short paragraphs max. Prioritize the most important gaps first.
"""


async def brainstorm_stream(
    user_message: str,
    chat_history: Optional[list[dict]] = None,
    model: str = "",
    images: Optional[list[dict]] = None,
    conversation_id: Optional[str] = None,
) -> AsyncIterator[str]:
    plan_logger.info("=" * 80)
    plan_logger.info("BRAINSTORM_STREAM started")
    plan_logger.info("  user_message: %s", user_message[:300].replace("\n", "\\n"))
    plan_logger.info("  chat_history turns: %d", len(chat_history) if chat_history else 0)
    plan_logger.info("  model: %s", model or "(master)")
    plan_logger.info("  conversation_id: %s", conversation_id)

    if not model:
        plan_logger.info("BRAINSTORM_STREAM falling back to master model (conv: %s)", conversation_id)
    
    model_name, provider = _resolve_model(model)
    client = create_client_for_model(model_name, provider, conversation_id=conversation_id)
    plan_logger.info("BRAINSTORM_STREAM using _chat_stream client: %s (provider: %s)", model_name, provider)
    
    messages = build_messages(user_message, plan_content="", chat_history=chat_history, images=images, system_prompt=BRAINSTORM_SYSTEM_PROMPT)

    token_count = 0
    full_response = ""
    try:
        async for chunk in client.chat_stream(messages):
            if isinstance(chunk, str):
                token_count += 1
                full_response += chunk
                yield chunk

        plan_logger.info("BRAINSTORM_STREAM completed: %d tokens, %d chars", token_count, len(full_response))
        plan_logger.debug("  Response preview: %s", full_response[:500].replace("\n", "\\n"))
    except Exception as e:
        plan_logger.error("BRAINSTORM_STREAM error: %s", e)
        logger.error("Brainstorm agent streaming error: %s", e)
        yield f"\n\n[Error: {str(e)}]"
