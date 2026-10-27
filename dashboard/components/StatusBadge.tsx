import { titleCase } from "@/lib/format";

import type { RunStatus, StepStatus, TestStatus } from "@/lib/types";

type BadgeStatus = RunStatus | StepStatus | TestStatus | string;

export function StatusBadge({ status, label }: { status: BadgeStatus; label?: string }) {
  const normalized = status.toLowerCase();
  return (
    <span className={`status status-${normalized}`} data-status={normalized}>
      {label ?? titleCase(normalized)}
    </span>
  );
}
