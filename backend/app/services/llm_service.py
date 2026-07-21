import ast

import structlog
from openai import OpenAI

from app.utils.prompt_builder import build_generation_prompt

log = structlog.get_logger()

LLM_USAGE_MARKERS = ["LLM_API_KEY", "OpenAI(", "Anthropic(", "chat.completions.create", "genai.GenerativeModel", "google.generativeai"]


class LlmService:
    @staticmethod
    async def generate_script(
        prompt_text: str,
        mcp_servers_info: list[dict],
        api_key: str,
        llm_provider: str,
        llm_model: str,
    ) -> tuple[str, bool, list]:
        system_prompt = build_generation_prompt(prompt_text, mcp_servers_info, llm_provider=llm_provider)

        if llm_provider == "openai":
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text},
                ],
                temperature=0.2,
            )
            code = response.choices[0].message.content.strip()
        elif llm_provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=llm_model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt_text}],
            )
            code = response.content[0].text.strip()
        elif llm_provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(llm_model)
            response = model.generate_content(
                f"{system_prompt}\n\n---\n\nUser request: {prompt_text}",
                generation_config=genai.types.GenerationConfig(temperature=0.2),
            )
            code = response.text.strip()
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        # Strip markdown fences if present
        if code.startswith("```python"):
            code = code[len("```python"):].strip()
        if code.startswith("```"):
            code = code[3:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()

        # Validate syntax
        try:
            ast.parse(code)
        except SyntaxError as e:
            log.warning("Generated script has syntax error, retrying", error=str(e))
            # Retry once with the error context
            retry_msg = f"The previous script had a syntax error: {e}. Fix it and return only the corrected Python code."
            if llm_provider == "openai":
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt_text},
                        {"role": "assistant", "content": code},
                        {"role": "user", "content": retry_msg},
                    ],
                    temperature=0.1,
                )
                code = response.choices[0].message.content.strip()
            elif llm_provider == "google":
                import google.generativeai as genai
                response = model.generate_content(
                    f"{system_prompt}\n\n---\n\nUser request: {prompt_text}\n\nPrevious attempt:\n{code}\n\n{retry_msg}",
                    generation_config=genai.types.GenerationConfig(temperature=0.1),
                )
                code = response.text.strip()
            if code.startswith("```python"):
                code = code[len("```python"):].strip()
            if code.startswith("```"):
                code = code[3:].strip()
            if code.endswith("```"):
                code = code[:-3].strip()
            ast.parse(code)  # If still invalid, let it raise

        # Detect if script uses LLM at runtime
        needs_llm = any(marker in code for marker in LLM_USAGE_MARKERS)
        llm_steps = []
        if needs_llm:
            llm_steps = [{"description": "Script contains LLM API calls for runtime reasoning"}]

        return code, needs_llm, llm_steps
