import type { ReactNode } from "react";

import type { ModuleStatus } from "@/features/platform/platform-config";

import { StatusBadge } from "./StatusBadge";
import styles from "./CapabilityCard.module.css";

type Props = {
  title: string;
  status?: ModuleStatus;
  /** 标题下方的补充说明，用于标注数据的真实性质。 */
  caption?: string;
  description?: string;
  items?: string[];
  /** chain 用等宽字体展示依赖链路。 */
  variant?: "list" | "chain";
  footer?: ReactNode;
};

export function CapabilityCard({
  title,
  status,
  caption,
  description,
  items,
  variant = "list",
  footer,
}: Props) {
  return (
    <article className={styles.card}>
      <header className={styles.head}>
        <h3 className={styles.title}>{title}</h3>
        {status ? <StatusBadge status={status} size="sm" /> : null}
      </header>

      {caption ? <p className={styles.caption}>{caption}</p> : null}
      {description ? <p className={styles.description}>{description}</p> : null}

      {items && items.length > 0 ? (
        <ul className={styles.items} data-variant={variant}>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}

      {footer ? <div className={styles.footer}>{footer}</div> : null}
    </article>
  );
}
