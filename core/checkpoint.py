"""CheckpointManager — 采集断点续传，参考 Scrapling 设计"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("thunder.checkpoint")


@dataclass
class CheckpointData:
    """采集检查点数据 — 保存当前进度以便中断后恢复"""

    industry_slug: str = ""
    phase: str = "discover"  # "discover" | "collect" | "classify"
    keywords_processed: list[str] = field(default_factory=list)
    bloggers_processed: list[str] = field(default_factory=list)
    videos_collected: list[str] = field(default_factory=list)
    # 已入队的 comment_id 列表（避免重复入队）
    comments_enqueued: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class CheckpointManager:
    """管理采集进度的持久化与恢复。

    使用原子写入（临时文件 + rename）防止文件损坏。
    """

    CHECKPOINT_FILE = "checkpoint.json"

    def __init__(self, crawldir: str | Path, interval: float = 300.0):
        self.crawldir = Path(crawldir)
        self._checkpoint_path = self.crawldir / self.CHECKPOINT_FILE
        if interval < 0:
            raise ValueError("Checkpoint interval must be >= 0")
        self.interval = interval

    @property
    def has_checkpoint(self) -> bool:
        """检查是否存在未完成的检查点"""
        return self._checkpoint_path.exists()

    def save(self, data: CheckpointData) -> None:
        """原子写入检查点 — 先写 .tmp 再 rename"""
        from datetime import datetime, timezone

        self.crawldir.mkdir(parents=True, exist_ok=True)
        temp_path = self._checkpoint_path.with_suffix(".tmp")

        data.updated_at = datetime.now(timezone.utc).isoformat()
        try:
            serialized = json.dumps(data.__dict__, ensure_ascii=False, indent=2)
            temp_path.write_text(serialized, encoding="utf-8")
            temp_path.replace(self._checkpoint_path)
            log.debug(
                f"Checkpoint saved: phase={data.phase}, "
                f"keywords={len(data.keywords_processed)}, "
                f"bloggers={len(data.bloggers_processed)}"
            )
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def load(self) -> Optional[CheckpointData]:
        """加载检查点。不存在或损坏时返回 None"""
        if not self.has_checkpoint:
            return None

        try:
            text = self._checkpoint_path.read_text(encoding="utf-8")
            raw = json.loads(text)
            return CheckpointData(
                **{
                    k: v
                    for k, v in raw.items()
                    if k in CheckpointData.__dataclass_fields__
                }
            )
        except (json.JSONDecodeError, FileNotFoundError, TypeError) as e:
            log.warning(f"Checkpoint 加载失败（将重新开始）: {e}")
            return None

    def cleanup(self) -> None:
        """采集正常完成后删除检查点文件"""
        try:
            self._checkpoint_path.unlink(missing_ok=True)
            log.debug("Checkpoint 文件已清理")
        except Exception as e:
            log.warning(f"清理 Checkpoint 文件失败: {e}")
