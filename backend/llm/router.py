import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


LLM_ASSIGNMENTS = {
    "intake": "claude",
    "planning": "claude",
    "research": "groq",
    "search": "groq",
    "code": "claude",
    "review": "claude",
    "simulation": "groq",
    "pricing": "groq",
    "competitor_intel": "groq",
    "deployment": "groq",
    "summarization": "groq",
    "json_extraction": "groq",
    "general": "groq",
}


def get_llm_response(
    task: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 3000,
    temperature: float = 0.2,
) -> str:
    """
    Routes to the right LLM based on task type.

    Full fallback chain:
    preferred provider -> GPT-4 -> Groq

    Always returns a string and never raises an exception.
    """

    preferred = LLM_ASSIGNMENTS.get(task, "groq")

    print(
        f"[LLM Router] task={task}, preferred={preferred}"
    )

    # Preferred Claude
    if preferred == "claude":
        try:
            result = _try_claude(
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            )

            if result:
                print(
                    f"[LLM Router] Claude succeeded ({len(result)} chars)"
                )
                return result

        except Exception as e:
            print(
                f"[LLM Router] Claude unavailable — "
                f"falling back to Groq: {e}"
            )

        # GPT-4 fallback
        try:
            result = _try_gpt4(
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            )

            if result:
                print(
                    f"[LLM Router] GPT-4 succeeded ({len(result)} chars)"
                )
                return result

        except Exception as e:
            print(
                f"[LLM Router] GPT-4 unavailable — "
                f"falling back to Groq: {e}"
            )

        # Groq fallback
        try:
            result = _try_groq(
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            )

            if result:
                print(
                    f"[LLM Router] Groq succeeded ({len(result)} chars)"
                )
                return result

        except Exception as e:
            print(
                f"[LLM Router] Groq failed: {e}"
            )

    else:
        # Preferred Groq
        try:
            result = _try_groq(
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            )

            if result:
                print(
                    f"[LLM Router] Groq succeeded ({len(result)} chars)"
                )
                return result

        except Exception as e:
            print(
                f"[LLM Router] Groq failed: {e}"
            )

        # Claude fallback
        try:
            result = _try_claude(
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            )

            if result:
                print(
                    f"[LLM Router] Claude succeeded ({len(result)} chars)"
                )
                return result

        except Exception as e:
            print(
                f"[LLM Router] Claude unavailable — "
                f"falling back to GPT-4: {e}"
            )

        # GPT-4 fallback
        try:
            result = _try_gpt4(
                system_prompt,
                user_message,
                max_tokens,
                temperature,
            )

            if result:
                print(
                    f"[LLM Router] GPT-4 succeeded ({len(result)} chars)"
                )
                return result

        except Exception as e:
            print(
                f"[LLM Router] GPT-4 failed: {e}"
            )

    error_msg = (
        "# OUTPUT GENERATION FAILED\n\n"
        f"All LLM providers failed for task: `{task}`\n\n"
        "**Troubleshooting:**\n"
        "1. Check `GROQ_API_KEY` is set in `.env`\n"
        "2. Check the backend terminal for specific error messages\n"
        "3. Verify the backend has internet access\n"
        "4. Check if Groq API is rate-limited at console.groq.com\n"
    )

    print(
        f"[LLM Router] ALL LLMs FAILED for task={task}"
    )

    return error_msg


def get_available_llms() -> dict:
    """Returns which LLMs are currently configured."""

    return {
        "groq": bool(os.getenv("GROQ_API_KEY")),
        "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
        "gpt4": bool(os.getenv("OPENAI_API_KEY")),
    }


def _try_claude(
    system: str,
    user: str,
    max_tokens: int,
    temp: float,
) -> str | None:
    """
    Try Anthropic Claude.

    Returns None on failure.
    """

    try:
        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            return None

        import anthropic

        client = anthropic.Anthropic(
            api_key=api_key
        )

        try:
            model = "claude-opus-4-6"

            msg = client.messages.create(
                model=model,
                max_tokens=min(max_tokens, 8096),
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": user,
                    }
                ],
            )
        except Exception:
            # Preserve compatibility with the older Claude model
            model = "claude-3-5-sonnet-20241022"

            msg = client.messages.create(
                model=model,
                max_tokens=min(max_tokens, 8096),
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": user,
                    }
                ],
            )

        content = msg.content

        if content and hasattr(content[0], "text"):
            return content[0].text.strip()

        if isinstance(content, str):
            return content.strip()

        return None

    except Exception as e:
        print(
            f"[LLM Router] Claude failed: "
            f"{type(e).__name__}: {str(e)[:120]}"
        )
        return None


def _try_gpt4(
    system: str,
    user: str,
    max_tokens: int,
    temp: float,
) -> str | None:
    """
    Try OpenAI GPT-4o.

    Returns None on failure.
    """

    try:
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            return None

        from openai import OpenAI

        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=max_tokens,
            temperature=temp,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
        )

        content = response.choices[0].message.content

        if content:
            return content.strip()

        return None

    except Exception as e:
        print(
            f"[LLM Router] GPT-4 failed: "
            f"{type(e).__name__}: {str(e)[:120]}"
        )
        return None


def _try_groq(
    system: str,
    user: str,
    max_tokens: int,
    temp: float,
) -> str | None:
    """
    Try Groq using llama-3.3-70b-versatile.

    Returns None on failure.
    """

    try:
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            print(
                "[LLM Router] GROQ_API_KEY not set in .env"
            )
            return None

        from groq import Groq

        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            max_tokens=max_tokens,
            temperature=temp,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
        )

        content = response.choices[0].message.content

        if content:
            return content.strip()

        return None

    except Exception as e:
        print(
            f"[LLM Router] Groq failed: "
            f"{type(e).__name__}: {str(e)[:120]}"
        )
        return None
