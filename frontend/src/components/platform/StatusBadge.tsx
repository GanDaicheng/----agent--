import type { ModuleStatus } from "@/features/platform/platform-config";
import { STATUS_LABEL } from "@/features/platform/platform-config";

import styles from "./StatusBadge.module.css";

type Props = {
  status: ModuleStatus;
  /** 更小的尺寸用于卡片角落，默认尺寸用于标题旁。 */
  size?: "sm" | "md";
};

export function StatusBadge({ status, size = "md" }: Props) {
  return (
    <span
      className={styles.badge}
      data-status={status}
      data-size={size}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}
