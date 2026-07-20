"""
Placeholder for ScriptExecutor — full implementation in Task 5.
"""
from app.models import Script, Execution
from sqlalchemy.ext.asyncio import AsyncSession


class ScriptExecutor:
    @staticmethod
    async def run(script: Script, session: AsyncSession) -> Execution:
        raise NotImplementedError("ScriptExecutor.run() will be implemented in Task 5")
