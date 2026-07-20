"""
重试策略 - 验证失败时追加修正提示并重试
"""
from __future__ import annotations

from harness.core.verifier import VerificationResult


def should_retry(
    verification: VerificationResult,
    attempt: int,
    max_retries: int,
) -> bool:
    """验证不通过且未超过最大重试次数时返回 True。"""
    if verification.passed:
        return False
    return attempt < max_retries


def build_retry_prompt(original_prompt: str, verification: VerificationResult) -> str:
    """在原始 user prompt 末尾追加验证失败原因。"""
    failures = verification.failure_messages()
    if not failures:
        return original_prompt

    lines = "\n".join(f"- {msg}" for msg in failures)
    return (
        f"{original_prompt}\n\n"
        f"[系统提示] 上次分析未通过验证，原因：\n{lines}\n"
        f"请修正后重新分析。"
    )
